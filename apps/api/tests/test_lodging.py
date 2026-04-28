"""楽天トラベル API クライアントのユニットテスト。"""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from src.evidence.lodging import RakutenLodgingError, fetch_lodging_options

# --- SimpleHotelSearch 用モック ---
# {"hotels": [{"hotel": [{"hotelBasicInfo": {...}}, {"hotelRatingInfo": {...}}]}, ...]}
_SIMPLE_HOTEL_ENTRY = {
    "hotel": [
        {
            "hotelBasicInfo": {
                "hotelNo": 12345,
                "hotelName": "箱根温泉旅館 テスト館",
                "latitude": 35.23,
                "longitude": 139.10,
                "hotelInformationUrl": "https://travel.rakuten.co.jp/hotel/12345/",
                "hotelMinCharge": 15000,
            }
        },
        {
            "hotelRatingInfo": {
                "serviceAverage": 4.5,
            }
        },
    ]
}

_SIMPLE_RESPONSE = {"hotels": [_SIMPLE_HOTEL_ENTRY]}

# --- VacantHotelSearch 用モック ---
# roomInfo[].dailyCharge.stayDate[0].rakutenCharge が実際の1泊料金
_VACANT_HOTEL_ENTRY = {
    "hotel": [
        {
            "hotelBasicInfo": {
                "hotelNo": 99999,
                "hotelName": "箱根空室あり旅館",
                "latitude": 35.24,
                "longitude": 139.11,
                "hotelInformationUrl": "https://travel.rakuten.co.jp/hotel/99999/",
                "hotelMinCharge": 18000,
            }
        },
        {
            "hotelRatingInfo": {
                "reviewAverage": 4.3,
            }
        },
        {
            "roomInfo": [
                {
                    "roomBasicInfo": {"roomName": "スタンダードツイン"},
                    "dailyCharge": {
                        "stayDate": [
                            {"stayDate": "20260601", "rakutenCharge": 20000, "total": 20000}
                        ]
                    },
                }
            ]
        },
    ]
}

_VACANT_RESPONSE = {"hotels": [_VACANT_HOTEL_ENTRY]}
_VACANT_EMPTY_RESPONSE = {"hotels": []}


def _make_mock_resp(json_data):
    mock = MagicMock()
    mock.json.return_value = json_data
    mock.raise_for_status.return_value = None
    return mock


class TestFetchLodgingOptionsVacant:
    """VacantHotelSearch が成功するケース（優先パス）。"""

    def test_uses_vacant_price_when_available(self, monkeypatch):
        monkeypatch.setenv("RAKUTEN_APPLICATION_ID", "test_app_id")
        monkeypatch.setenv("RAKUTEN_ACCESS_KEY", "test_access_key")

        # VacantHotelSearch が 1 件返す → SimpleHotelSearch は呼ばれない
        with patch("src.evidence.lodging.requests.get", return_value=_make_mock_resp(_VACANT_RESPONSE)) as mock_get:
            result = fetch_lodging_options(
                region="箱根",
                checkin_date="2026-06-01",
                checkout_date="2026-06-02",
                adult_num=2,
                max_charge_per_night=30000,
                lat=35.23,
                lng=139.10,
            )

        assert len(result) == 1
        hotel = result[0]
        assert hotel.name == "箱根空室あり旅館"
        assert hotel.price_jpy_per_night == 20000  # total = 1室あたりの1泊合計料金
        assert hotel.rating == 4.3
        assert hotel.place_id == "rakuten_99999"
        # VacantHotelSearch のみ呼ばれ SimpleHotelSearch は呼ばれない
        assert mock_get.call_count == 1
        assert "VacantHotelSearch" in mock_get.call_args[0][0]

    def test_vacant_price_takes_minimum_across_rooms(self, monkeypatch):
        """複数部屋タイプがある場合は最安値を採用する。"""
        monkeypatch.setenv("RAKUTEN_APPLICATION_ID", "test_app_id")
        monkeypatch.setenv("RAKUTEN_ACCESS_KEY", "test_access_key")

        multi_room_entry = {
            "hotel": [
                {
                    "hotelBasicInfo": {
                        "hotelNo": 111,
                        "hotelName": "多部屋テスト宿",
                        "latitude": 35.0,
                        "longitude": 139.0,
                        "hotelMinCharge": 10000,
                    }
                },
                {
                    "roomInfo": [
                        {
                            "roomBasicInfo": {"roomName": "和室"},
                            "dailyCharge": {
                                "stayDate": [{"stayDate": "20260601", "rakutenCharge": 12500, "total": 25000}]
                            },
                        },
                        {
                            "roomBasicInfo": {"roomName": "洋室"},
                            "dailyCharge": {
                                "stayDate": [{"stayDate": "20260601", "rakutenCharge": 9000, "total": 18000}]
                            },
                        },
                    ]
                },
            ]
        }

        with patch("src.evidence.lodging.requests.get", return_value=_make_mock_resp({"hotels": [multi_room_entry]})):
            result = fetch_lodging_options(
                "箱根", "2026-06-01", "2026-06-02", 2, 30000, lat=35.0, lng=139.0
            )

        assert len(result) == 1
        assert result[0].price_jpy_per_night == 18000  # 2 部屋中の最安値

    def test_falls_back_to_simple_when_vacant_empty(self, monkeypatch):
        """VacantHotelSearch が 0 件なら SimpleHotelSearch にフォールバックする。"""
        monkeypatch.setenv("RAKUTEN_APPLICATION_ID", "test_app_id")
        monkeypatch.setenv("RAKUTEN_ACCESS_KEY", "test_access_key")

        responses = [
            _make_mock_resp(_VACANT_EMPTY_RESPONSE),  # VacantHotelSearch: 0 件
            _make_mock_resp(_SIMPLE_RESPONSE),          # SimpleHotelSearch: 1 件
        ]

        with patch("src.evidence.lodging.requests.get", side_effect=responses) as mock_get:
            result = fetch_lodging_options(
                "箱根", "2026-06-01", "2026-06-02", 2, 20000, lat=35.23, lng=139.10
            )

        assert len(result) == 1
        assert result[0].name == "箱根温泉旅館 テスト館"
        assert result[0].price_jpy_per_night == 15000  # hotelMinCharge（参考価格）
        assert mock_get.call_count == 2
        assert "SimpleHotelSearch" in mock_get.call_args[0][0]

    def test_falls_back_to_simple_when_vacant_http_error(self, monkeypatch):
        """VacantHotelSearch が HTTP エラーなら SimpleHotelSearch にフォールバックする。"""
        import requests as req

        monkeypatch.setenv("RAKUTEN_APPLICATION_ID", "test_app_id")
        monkeypatch.setenv("RAKUTEN_ACCESS_KEY", "test_access_key")

        vacant_resp = _make_mock_resp({})
        vacant_resp.raise_for_status.side_effect = req.HTTPError("403")

        simple_resp = _make_mock_resp(_SIMPLE_RESPONSE)

        with patch("src.evidence.lodging.requests.get", side_effect=[vacant_resp, simple_resp]):
            result = fetch_lodging_options(
                "箱根", "2026-06-01", "2026-06-02", 2, 20000, lat=35.23, lng=139.10
            )

        assert len(result) == 1
        assert result[0].name == "箱根温泉旅館 テスト館"

    def test_checkin_checkout_sent_as_yyyymmdd(self, monkeypatch):
        """VacantHotelSearch に checkinDate が YYYYMMDD 形式で送られる。"""
        monkeypatch.setenv("RAKUTEN_APPLICATION_ID", "test_app_id")
        monkeypatch.setenv("RAKUTEN_ACCESS_KEY", "test_access_key")

        with patch("src.evidence.lodging.requests.get", return_value=_make_mock_resp(_VACANT_RESPONSE)) as mock_get:
            fetch_lodging_options(
                "箱根", "2026-06-01", "2026-06-02", 2, 30000, lat=35.23, lng=139.10
            )

        call_params = mock_get.call_args[1]["params"]
        assert call_params["checkinDate"] == "20260601"
        assert call_params["checkoutDate"] == "20260602"
        assert call_params["adultNum"] == 2
        assert call_params["maxCharge"] == 30000


class TestFetchLodgingOptionsSimple:
    """SimpleHotelSearch フォールバックのケース。"""

    def test_returns_lodging_options(self, monkeypatch):
        monkeypatch.setenv("RAKUTEN_APPLICATION_ID", "test_app_id")
        monkeypatch.setenv("RAKUTEN_ACCESS_KEY", "test_access_key")

        # VacantHotelSearch → 0 件 → SimpleHotelSearch → 1 件
        responses = [_make_mock_resp(_VACANT_EMPTY_RESPONSE), _make_mock_resp(_SIMPLE_RESPONSE)]

        with patch("src.evidence.lodging.requests.get", side_effect=responses):
            result = fetch_lodging_options(
                region="箱根",
                checkin_date="2026-06-01",
                checkout_date="2026-06-02",
                adult_num=2,
                max_charge_per_night=20000,
                lat=35.23,
                lng=139.10,
            )

        assert len(result) == 1
        hotel = result[0]
        assert hotel.name == "箱根温泉旅館 テスト館"
        assert hotel.price_jpy_per_night == 15000
        assert hotel.place_id == "rakuten_12345"
        assert hotel.lat == 35.23
        assert hotel.lng == 139.10
        assert hotel.url == "https://travel.rakuten.co.jp/hotel/12345/"

    def test_filters_by_max_charge(self, monkeypatch):
        monkeypatch.setenv("RAKUTEN_APPLICATION_ID", "test_app_id")
        monkeypatch.setenv("RAKUTEN_ACCESS_KEY", "test_access_key")

        # VacantHotelSearch → 0 件 → SimpleHotelSearch → 上限超で除外
        responses = [_make_mock_resp(_VACANT_EMPTY_RESPONSE), _make_mock_resp(_SIMPLE_RESPONSE)]

        with patch("src.evidence.lodging.requests.get", side_effect=responses):
            result = fetch_lodging_options(
                region="箱根",
                checkin_date="2026-06-01",
                checkout_date="2026-06-02",
                adult_num=2,
                max_charge_per_night=10000,  # 上限 10000 < 15000 → フィルタされる
                lat=35.23,
                lng=139.10,
            )

        assert result == []

    def test_raises_when_app_id_missing(self, monkeypatch):
        monkeypatch.delenv("RAKUTEN_APPLICATION_ID", raising=False)
        monkeypatch.delenv("RAKUTEN_ACCESS_KEY", raising=False)

        with pytest.raises(RakutenLodgingError, match="RAKUTEN_APPLICATION_ID"):
            fetch_lodging_options("箱根", "2026-06-01", "2026-06-02", 2, 20000, lat=35.23, lng=139.10)

    def test_returns_empty_when_no_coords(self, monkeypatch):
        monkeypatch.setenv("RAKUTEN_APPLICATION_ID", "test_app_id")
        monkeypatch.setenv("RAKUTEN_ACCESS_KEY", "test_access_key")

        result = fetch_lodging_options("箱根", "2026-06-01", "2026-06-02", 2, 20000)
        assert result == []

    def test_returns_empty_on_no_hotels_both_apis(self, monkeypatch):
        monkeypatch.setenv("RAKUTEN_APPLICATION_ID", "test_app_id")
        monkeypatch.setenv("RAKUTEN_ACCESS_KEY", "test_access_key")

        empty = _make_mock_resp({"hotels": []})
        empty2 = _make_mock_resp({"hotels": []})

        with patch("src.evidence.lodging.requests.get", side_effect=[empty, empty2]):
            result = fetch_lodging_options("存在しない地域", "2026-06-01", "2026-06-02", 2, 5000, lat=35.0, lng=139.0)

        assert result == []

    def test_raises_on_simple_network_error(self, monkeypatch):
        """VacantHotelSearch が 0 件で SimpleHotelSearch がネットワークエラーの場合 raise する。"""
        import requests as req

        monkeypatch.setenv("RAKUTEN_APPLICATION_ID", "test_app_id")
        monkeypatch.setenv("RAKUTEN_ACCESS_KEY", "test_access_key")

        vacant_resp = _make_mock_resp(_VACANT_EMPTY_RESPONSE)

        with patch(
            "src.evidence.lodging.requests.get",
            side_effect=[vacant_resp, req.RequestException("timeout")],
        ):
            with pytest.raises(RakutenLodgingError):
                fetch_lodging_options("箱根", "2026-06-01", "2026-06-02", 2, 20000, lat=35.23, lng=139.10)

    def test_skips_malformed_hotel_entry(self, monkeypatch):
        monkeypatch.setenv("RAKUTEN_APPLICATION_ID", "test_app_id")
        monkeypatch.setenv("RAKUTEN_ACCESS_KEY", "test_access_key")

        malformed_response = {
            "hotels": [
                {"hotel": [{"hotelBasicInfo": {}}]},  # name なし → None → スキップ
                _SIMPLE_HOTEL_ENTRY,
            ]
        }

        responses = [_make_mock_resp(_VACANT_EMPTY_RESPONSE), _make_mock_resp(malformed_response)]

        with patch("src.evidence.lodging.requests.get", side_effect=responses):
            result = fetch_lodging_options("箱根", "2026-06-01", "2026-06-02", 2, 20000, lat=35.23, lng=139.10)

        assert len(result) == 1
        assert result[0].name == "箱根温泉旅館 テスト館"

    def test_extracts_review_average_when_present(self, monkeypatch):
        """hotelRatingInfo.reviewAverage があれば rating として引き継がれる。"""
        monkeypatch.setenv("RAKUTEN_APPLICATION_ID", "test_app_id")
        monkeypatch.setenv("RAKUTEN_ACCESS_KEY", "test_access_key")

        mock_response = {
            "hotels": [
                {
                    "hotel": [
                        {
                            "hotelBasicInfo": {
                                "hotelNo": 555,
                                "hotelName": "評価あり旅館",
                                "latitude": 35.5,
                                "longitude": 139.5,
                                "hotelMinCharge": 18000,
                            }
                        },
                        {
                            "hotelRatingInfo": {
                                "serviceAverage": 4.5,
                                "reviewAverage": 4.2,
                            }
                        },
                    ]
                }
            ]
        }

        responses = [_make_mock_resp(_VACANT_EMPTY_RESPONSE), _make_mock_resp(mock_response)]

        with patch("src.evidence.lodging.requests.get", side_effect=responses):
            result = fetch_lodging_options(
                "箱根", "2026-06-01", "2026-06-02", 2, 30000, lat=35.5, lng=139.5,
            )

        assert len(result) == 1
        assert result[0].rating == 4.2

    def test_rating_none_when_review_average_missing(self, monkeypatch):
        """hotelRatingInfo.reviewAverage が無いエントリは rating=None。"""
        monkeypatch.setenv("RAKUTEN_APPLICATION_ID", "test_app_id")
        monkeypatch.setenv("RAKUTEN_ACCESS_KEY", "test_access_key")

        responses = [_make_mock_resp(_VACANT_EMPTY_RESPONSE), _make_mock_resp(_SIMPLE_RESPONSE)]

        with patch("src.evidence.lodging.requests.get", side_effect=responses):
            result = fetch_lodging_options(
                "箱根", "2026-06-01", "2026-06-02", 2, 20000, lat=35.23, lng=139.10,
            )

        assert len(result) == 1
        assert result[0].rating is None

    def test_rating_clamped_to_valid_range(self, monkeypatch):
        """範囲外の reviewAverage は None に。"""
        monkeypatch.setenv("RAKUTEN_APPLICATION_ID", "test_app_id")
        monkeypatch.setenv("RAKUTEN_ACCESS_KEY", "test_access_key")

        mock_response = {
            "hotels": [
                {
                    "hotel": [
                        {
                            "hotelBasicInfo": {
                                "hotelNo": 777,
                                "hotelName": "範囲外評価宿",
                                "latitude": 35.5,
                                "longitude": 139.5,
                                "hotelMinCharge": 10000,
                            }
                        },
                        {"hotelRatingInfo": {"reviewAverage": 7.5}},  # 範囲外
                    ]
                }
            ]
        }

        responses = [_make_mock_resp(_VACANT_EMPTY_RESPONSE), _make_mock_resp(mock_response)]

        with patch("src.evidence.lodging.requests.get", side_effect=responses):
            result = fetch_lodging_options(
                "箱根", "2026-06-01", "2026-06-02", 2, 20000, lat=35.5, lng=139.5,
            )

        assert len(result) == 1
        assert result[0].rating is None
