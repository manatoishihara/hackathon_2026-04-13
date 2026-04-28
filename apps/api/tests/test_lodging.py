"""楽天トラベル VacantHotelSearch API クライアントのユニットテスト。

Task A3 (2026-04-28): SimpleHotelSearch から VacantHotelSearch に移行済み。
mock 構造は roomInfo[].dailyCharge.total を per_person price source として使う。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.evidence.lodging import RakutenLodgingError, fetch_lodging_options

# VacantHotelSearch formatVersion=1 (デフォルト) の典型的なレスポンス構造:
# {"hotels": [{"hotel": [
#     {"hotelBasicInfo": {...}},
#     {"hotelRatingInfo": {...}},   # optional (reviewAverage を持つ)
#     {"roomInfo": [{"roomBasicInfo": {...}}, {"dailyCharge": {"total": int, ...}}]},
# ]}, ...]}
_MOCK_HOTEL_ENTRY = {
    "hotel": [
        {
            "hotelBasicInfo": {
                "hotelNo": 12345,
                "hotelName": "箱根温泉旅館 テスト館",
                "latitude": 35.23,
                "longitude": 139.10,
                "hotelInformationUrl": "https://travel.rakuten.co.jp/hotel/12345/",
            }
        },
        {
            "hotelRatingInfo": {
                "serviceAverage": 4.5,
            }
        },
        {
            "roomInfo": [
                {"roomBasicInfo": {"planName": "スタンダード"}},
                # total=30000 (1 室合計) / adult_num=2 → per_person=15000
                {"dailyCharge": {"stayDate": "2026-06-01", "total": 30000, "chargeFlag": 1}},
            ]
        },
    ]
}

_MOCK_RESPONSE = {"hotels": [_MOCK_HOTEL_ENTRY]}


class TestFetchLodgingOptions:

    def test_returns_lodging_options(self, monkeypatch):
        monkeypatch.setenv("RAKUTEN_APPLICATION_ID", "test_app_id")
        monkeypatch.setenv("RAKUTEN_ACCESS_KEY", "test_access_key")

        mock_resp = MagicMock()
        mock_resp.json.return_value = _MOCK_RESPONSE
        mock_resp.raise_for_status.return_value = None

        with patch("src.evidence.lodging.requests.get", return_value=mock_resp):
            result = fetch_lodging_options(
                region="箱根",
                checkin_date="2026-06-01",
                checkout_date="2026-06-02",
                adult_num=2,
                max_charge_per_night=30000,  # 1 室上限 (per_person=15000 × adult=2 = 30000)
                lat=35.23,
                lng=139.10,
            )

        assert len(result) == 1
        hotel = result[0]
        assert hotel.name == "箱根温泉旅館 テスト館"
        # roomInfo[].dailyCharge.total=30000 / adult_num=2 → per_person=15000
        assert hotel.price_jpy_per_night == 15000
        assert hotel.place_id == "rakuten_12345"
        assert hotel.lat == 35.23
        assert hotel.lng == 139.10
        assert hotel.url == "https://travel.rakuten.co.jp/hotel/12345/"

    def test_filters_by_max_charge(self, monkeypatch):
        monkeypatch.setenv("RAKUTEN_APPLICATION_ID", "test_app_id")
        monkeypatch.setenv("RAKUTEN_ACCESS_KEY", "test_access_key")

        mock_resp = MagicMock()
        # _MOCK_RESPONSE: total=30000 (1 室合計) / adult=2 → per_person=15000
        mock_resp.json.return_value = _MOCK_RESPONSE
        mock_resp.raise_for_status.return_value = None

        with patch("src.evidence.lodging.requests.get", return_value=mock_resp):
            result = fetch_lodging_options(
                region="箱根",
                checkin_date="2026-06-01",
                checkout_date="2026-06-02",
                adult_num=2,
                max_charge_per_night=10000,  # 1 室上限 10000 < 30000 → フィルタされる
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

        # 座標なし → API 呼ばず空リスト返却
        result = fetch_lodging_options("箱根", "2026-06-01", "2026-06-02", 2, 20000)
        assert result == []

    def test_returns_empty_on_no_hotels(self, monkeypatch):
        monkeypatch.setenv("RAKUTEN_APPLICATION_ID", "test_app_id")
        monkeypatch.setenv("RAKUTEN_ACCESS_KEY", "test_access_key")

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"hotels": []}
        mock_resp.raise_for_status.return_value = None

        with patch("src.evidence.lodging.requests.get", return_value=mock_resp):
            result = fetch_lodging_options("存在しない地域", "2026-06-01", "2026-06-02", 2, 5000, lat=35.0, lng=139.0)

        assert result == []

    def test_raises_on_network_error(self, monkeypatch):
        import requests as req
        monkeypatch.setenv("RAKUTEN_APPLICATION_ID", "test_app_id")
        monkeypatch.setenv("RAKUTEN_ACCESS_KEY", "test_access_key")

        with patch("src.evidence.lodging.requests.get", side_effect=req.RequestException("timeout")):
            with pytest.raises(RakutenLodgingError):
                fetch_lodging_options("箱根", "2026-06-01", "2026-06-02", 2, 20000, lat=35.23, lng=139.10)

    def test_skips_malformed_hotel_entry(self, monkeypatch):
        monkeypatch.setenv("RAKUTEN_APPLICATION_ID", "test_app_id")
        monkeypatch.setenv("RAKUTEN_ACCESS_KEY", "test_access_key")

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "hotels": [
                {"hotel": [{"hotelBasicInfo": {}}]},  # name なし → None → スキップ
                _MOCK_HOTEL_ENTRY,
            ]
        }
        mock_resp.raise_for_status.return_value = None

        with patch("src.evidence.lodging.requests.get", return_value=mock_resp):
            result = fetch_lodging_options("箱根", "2026-06-01", "2026-06-02", 2, 30000, lat=35.23, lng=139.10)

        assert len(result) == 1
        assert result[0].name == "箱根温泉旅館 テスト館"

    def test_extracts_review_average_when_present(self, monkeypatch):
        """Phase 3 polish 案 D 第 3 段 (2026-04-28): hotelRatingInfo.reviewAverage が
        あれば LodgingOption.rating として引き継がれる。"""
        monkeypatch.setenv("RAKUTEN_APPLICATION_ID", "test_app_id")
        monkeypatch.setenv("RAKUTEN_ACCESS_KEY", "test_access_key")

        # reviewAverage を含む mock (VacantHotelSearch 構造)
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
                            }
                        },
                        {
                            "hotelRatingInfo": {
                                "serviceAverage": 4.5,
                                "reviewAverage": 4.2,  # Phase 3 polish で追加抽出
                            }
                        },
                        {
                            "roomInfo": [
                                {"roomBasicInfo": {"planName": "プラン"}},
                                {"dailyCharge": {"stayDate": "2026-06-01", "total": 36000, "chargeFlag": 1}},
                            ]
                        },
                    ]
                }
            ]
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_response
        mock_resp.raise_for_status.return_value = None

        with patch("src.evidence.lodging.requests.get", return_value=mock_resp):
            result = fetch_lodging_options(
                "箱根", "2026-06-01", "2026-06-02", 2, 40000, lat=35.5, lng=139.5,
            )

        assert len(result) == 1
        assert result[0].rating == 4.2

    def test_rating_none_when_review_average_missing(self, monkeypatch):
        """hotelRatingInfo.reviewAverage が無いエントリは rating=None。"""
        monkeypatch.setenv("RAKUTEN_APPLICATION_ID", "test_app_id")
        monkeypatch.setenv("RAKUTEN_ACCESS_KEY", "test_access_key")

        mock_resp = MagicMock()
        mock_resp.json.return_value = _MOCK_RESPONSE  # reviewAverage 含まない (serviceAverage のみ)
        mock_resp.raise_for_status.return_value = None

        with patch("src.evidence.lodging.requests.get", return_value=mock_resp):
            result = fetch_lodging_options(
                "箱根", "2026-06-01", "2026-06-02", 2, 30000, lat=35.23, lng=139.10,
            )

        assert len(result) == 1
        assert result[0].rating is None  # 評価情報無しは None で保持

    def test_rating_clamped_to_valid_range(self, monkeypatch):
        """API レスポンスが想定外の範囲外の値を返した場合、None で安全側に倒す。"""
        monkeypatch.setenv("RAKUTEN_APPLICATION_ID", "test_app_id")
        monkeypatch.setenv("RAKUTEN_ACCESS_KEY", "test_access_key")

        # 6.0 (5 超) や 文字列 など無効値 → None に
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
                            }
                        },
                        {"hotelRatingInfo": {"reviewAverage": 7.5}},  # 範囲外
                        {
                            "roomInfo": [
                                {"roomBasicInfo": {"planName": "プラン"}},
                                {"dailyCharge": {"stayDate": "2026-06-01", "total": 20000, "chargeFlag": 1}},
                            ]
                        },
                    ]
                }
            ]
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_response
        mock_resp.raise_for_status.return_value = None

        with patch("src.evidence.lodging.requests.get", return_value=mock_resp):
            result = fetch_lodging_options(
                "箱根", "2026-06-01", "2026-06-02", 2, 30000, lat=35.5, lng=139.5,
            )

        assert len(result) == 1
        assert result[0].rating is None  # 0〜5 範囲外は無視


# ==============================
# Task A3 (2026-04-28): VacantHotelSearch 移行 — 実価格 (per-person 1 泊) を取得
# 旧 SimpleHotelSearch の hotelMinCharge は「目安最安値」で日付/人数/空室を考慮しなかった。
# VacantHotelSearch に移行し、roomInfo[].dailyCharge.total を adultNum で割って
# 1 人 1 泊料金を算出する。
# ==============================


class TestVacantHotelSearch:
    """VacantHotelSearch endpoint への移行検証。"""

    def test_vacant_hotel_search_endpoint_and_params(self, monkeypatch):
        """endpoint URL と必須 params (checkinDate/checkoutDate/adultNum YYYYMMDD) が送信される。"""
        monkeypatch.setenv("RAKUTEN_APPLICATION_ID", "test_app_id")
        monkeypatch.setenv("RAKUTEN_ACCESS_KEY", "pk_test_key")

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"hotels": []}
        mock_resp.raise_for_status.return_value = None

        with patch("src.evidence.lodging.requests.get", return_value=mock_resp) as mock_get:
            fetch_lodging_options(
                region="箱根",
                checkin_date="2026-06-01",
                checkout_date="2026-06-02",
                adult_num=2,
                max_charge_per_night=30000,
                lat=35.2327,
                lng=139.1069,
            )

        assert mock_get.call_count == 1
        call_args = mock_get.call_args
        # 第 1 引数 or kwargs["url"] で URL を確認
        url = call_args.args[0] if call_args.args else call_args.kwargs.get("url")
        assert url == "https://openapi.rakuten.co.jp/engine/api/Travel/VacantHotelSearch/20170426"

        params = call_args.kwargs["params"]
        assert params["checkinDate"] == "20260601"   # YYYY-MM-DD → YYYYMMDD
        assert params["checkoutDate"] == "20260602"
        assert params["adultNum"] == 2
        assert params["latitude"] == 35.2327
        assert params["longitude"] == 139.1069
        assert params["datumType"] == 1
        assert params["maxCharge"] == 30000

    def test_vacant_hotel_search_extracts_per_person_price_from_total(self, monkeypatch):
        """roomInfo[].dailyCharge.total を adultNum で割って per_person を計算。"""
        monkeypatch.setenv("RAKUTEN_APPLICATION_ID", "test_app_id")
        monkeypatch.setenv("RAKUTEN_ACCESS_KEY", "pk_test_key")

        mock_response = {
            "hotels": [
                {
                    "hotel": [
                        {
                            "hotelBasicInfo": {
                                "hotelNo": 19684,
                                "hotelName": "箱根湯本温泉 ホテル おかだ",
                                "latitude": 35.2266,
                                "longitude": 139.0922,
                                "hotelInformationUrl": "https://hb.afl.rakuten.co.jp/test",
                            }
                        },
                        {"hotelRatingInfo": {"reviewAverage": 4.38}},
                        {
                            "roomInfo": [
                                {"roomBasicInfo": {"planName": "素泊まり"}},
                                {"dailyCharge": {"stayDate": "2026-06-01", "total": 26400, "rakutenCharge": 13200, "chargeFlag": 0}},
                            ]
                        },
                    ]
                }
            ]
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_response
        mock_resp.raise_for_status.return_value = None

        with patch("src.evidence.lodging.requests.get", return_value=mock_resp):
            options = fetch_lodging_options(
                region="箱根",
                checkin_date="2026-06-01",
                checkout_date="2026-06-02",
                adult_num=2,
                max_charge_per_night=30000,
                lat=35.2327,
                lng=139.1069,
            )

        assert len(options) == 1
        opt = options[0]
        assert opt.name == "箱根湯本温泉 ホテル おかだ"
        assert opt.price_jpy_per_night == 13200  # 26400 / 2
        assert opt.url == "https://hb.afl.rakuten.co.jp/test"
        assert opt.rating == 4.38
        assert opt.place_id == "rakuten_19684"

    def test_vacant_hotel_search_handles_multiple_room_plans_picks_min(self, monkeypatch):
        """roomInfo に複数プランがある場合は最安値の total を採用。"""
        monkeypatch.setenv("RAKUTEN_APPLICATION_ID", "test_app_id")
        monkeypatch.setenv("RAKUTEN_ACCESS_KEY", "pk_test_key")

        mock_response = {
            "hotels": [
                {
                    "hotel": [
                        {"hotelBasicInfo": {"hotelNo": 1, "hotelName": "宿A", "latitude": 35.0, "longitude": 139.0}},
                        {"roomInfo": [
                            {"roomBasicInfo": {"planName": "プラン1"}},
                            {"dailyCharge": {"stayDate": "2026-06-01", "total": 30000, "chargeFlag": 1}},
                        ]},
                        {"roomInfo": [
                            {"roomBasicInfo": {"planName": "プラン2"}},
                            {"dailyCharge": {"stayDate": "2026-06-01", "total": 20000, "chargeFlag": 1}},
                        ]},
                    ]
                }
            ]
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_response
        mock_resp.raise_for_status.return_value = None

        with patch("src.evidence.lodging.requests.get", return_value=mock_resp):
            options = fetch_lodging_options(
                region="箱根", checkin_date="2026-06-01", checkout_date="2026-06-02",
                adult_num=2, max_charge_per_night=30000, lat=35.0, lng=139.0,
            )

        assert len(options) == 1
        assert options[0].price_jpy_per_night == 10000  # min(30000, 20000) / 2

    def test_vacant_hotel_search_respects_max_charge_filter(self, monkeypatch):
        """maxCharge を超える total は client 側でも除外される。"""
        monkeypatch.setenv("RAKUTEN_APPLICATION_ID", "test_app_id")
        monkeypatch.setenv("RAKUTEN_ACCESS_KEY", "pk_test_key")

        mock_response = {
            "hotels": [
                {
                    "hotel": [
                        {"hotelBasicInfo": {"hotelNo": 1, "hotelName": "高級宿", "latitude": 35.0, "longitude": 139.0}},
                        {"roomInfo": [
                            {"roomBasicInfo": {"planName": "プラン"}},
                            {"dailyCharge": {"stayDate": "2026-06-01", "total": 100000, "chargeFlag": 1}},
                        ]},
                    ]
                }
            ]
        }
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_response
        mock_resp.raise_for_status.return_value = None

        with patch("src.evidence.lodging.requests.get", return_value=mock_resp):
            options = fetch_lodging_options(
                region="箱根", checkin_date="2026-06-01", checkout_date="2026-06-02",
                adult_num=2, max_charge_per_night=30000, lat=35.0, lng=139.0,
            )

        # total=100000 > maxCharge=30000 → 除外
        assert options == []
