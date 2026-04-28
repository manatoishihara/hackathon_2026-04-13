<<<<<<< HEAD
"""楽天トラベル API クライアントのユニットテスト。

Phase 3 polish 案 D (2026-04-28): 公式 API spec 準拠書き換え後の test。
- region keyword → lat/lng + searchRadius 検索に変更
- accessKey 必須化 (新仕様)
- checkinDate / checkoutDate / adultNum / maxCharge は SimpleHotelSearch には存在しない
"""
=======
"""楽天トラベル SimpleHotelSearch API クライアントのユニットテスト。"""
>>>>>>> ceb6e75acce3b8a26f8b2b9ec473a1d540a81072

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.evidence.lodging import RakutenLodgingError, fetch_lodging_options

<<<<<<< HEAD
_MOCK_HOTEL_ENTRY = [
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
]
=======
# formatVersion=1 (デフォルト) の実際のレスポンス構造
# {"hotels": [{"hotel": [{"hotelBasicInfo": {...}}, {"hotelRatingInfo": {...}}]}, ...]}
_MOCK_HOTEL_ENTRY = {
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
>>>>>>> ceb6e75acce3b8a26f8b2b9ec473a1d540a81072

_MOCK_RESPONSE = {"hotels": [_MOCK_HOTEL_ENTRY]}


def _set_creds(monkeypatch):
    monkeypatch.setenv("RAKUTEN_APPLICATION_ID", "1234567890123456789")
    monkeypatch.setenv("RAKUTEN_ACCESS_KEY", "test_access_key")


class TestFetchLodgingOptions:

    def test_returns_lodging_options(self, monkeypatch):
<<<<<<< HEAD
        _set_creds(monkeypatch)
=======
        monkeypatch.setenv("RAKUTEN_APPLICATION_ID", "test_app_id")
        monkeypatch.setenv("RAKUTEN_ACCESS_KEY", "test_access_key")
>>>>>>> ceb6e75acce3b8a26f8b2b9ec473a1d540a81072

        mock_resp = MagicMock()
        mock_resp.json.return_value = _MOCK_RESPONSE
        mock_resp.raise_for_status.return_value = None

        with patch("src.evidence.lodging.requests.get", return_value=mock_resp):
<<<<<<< HEAD
            result = fetch_lodging_options(lat=35.23, lng=139.10)
=======
            result = fetch_lodging_options(
                region="箱根",
                checkin_date="2026-06-01",
                checkout_date="2026-06-02",
                adult_num=2,
                max_charge_per_night=20000,
                lat=35.23,
                lng=139.10,
            )
>>>>>>> ceb6e75acce3b8a26f8b2b9ec473a1d540a81072

        assert len(result) == 1
        hotel = result[0]
        assert hotel.name == "箱根温泉旅館 テスト館"
<<<<<<< HEAD
        assert hotel.price_jpy_per_night == 15000  # SimpleHotelSearch は hotelMinCharge を使う
=======
        assert hotel.price_jpy_per_night == 15000  # hotelMinCharge を使用
>>>>>>> ceb6e75acce3b8a26f8b2b9ec473a1d540a81072
        assert hotel.place_id == "rakuten_12345"
        assert hotel.lat == 35.23
        assert hotel.lng == 139.10
        assert hotel.url == "https://travel.rakuten.co.jp/hotel/12345/"

    def test_filters_by_max_charge(self, monkeypatch):
        monkeypatch.setenv("RAKUTEN_APPLICATION_ID", "test_app_id")
        monkeypatch.setenv("RAKUTEN_ACCESS_KEY", "test_access_key")

        mock_resp = MagicMock()
        mock_resp.json.return_value = _MOCK_RESPONSE  # hotelMinCharge=15000
        mock_resp.raise_for_status.return_value = None

        with patch("src.evidence.lodging.requests.get", return_value=mock_resp):
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
<<<<<<< HEAD
        monkeypatch.setenv("RAKUTEN_ACCESS_KEY", "test_access_key")

        with pytest.raises(RakutenLodgingError, match="RAKUTEN_APPLICATION_ID"):
            fetch_lodging_options(lat=35.23, lng=139.10)

    def test_raises_when_access_key_missing(self, monkeypatch):
        """Phase 3 polish 案 D: accessKey 新仕様で必須化、未設定時は raise。"""
        monkeypatch.setenv("RAKUTEN_APPLICATION_ID", "1234567890123456789")
        monkeypatch.delenv("RAKUTEN_ACCESS_KEY", raising=False)

        with pytest.raises(RakutenLodgingError, match="RAKUTEN_ACCESS_KEY"):
            fetch_lodging_options(lat=35.23, lng=139.10)

    def test_returns_empty_on_no_hotels(self, monkeypatch):
        _set_creds(monkeypatch)
=======
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
>>>>>>> ceb6e75acce3b8a26f8b2b9ec473a1d540a81072

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"hotels": []}
        mock_resp.raise_for_status.return_value = None

        with patch("src.evidence.lodging.requests.get", return_value=mock_resp):
<<<<<<< HEAD
            result = fetch_lodging_options(lat=35.23, lng=139.10)
=======
            result = fetch_lodging_options("存在しない地域", "2026-06-01", "2026-06-02", 2, 5000, lat=35.0, lng=139.0)
>>>>>>> ceb6e75acce3b8a26f8b2b9ec473a1d540a81072

        assert result == []

    def test_raises_on_network_error(self, monkeypatch):
        import requests as req
<<<<<<< HEAD
        _set_creds(monkeypatch)

        with patch("src.evidence.lodging.requests.get", side_effect=req.RequestException("timeout")):
            with pytest.raises(RakutenLodgingError):
                fetch_lodging_options(lat=35.23, lng=139.10)

    def test_skips_malformed_hotel_entry(self, monkeypatch):
        _set_creds(monkeypatch)
=======
        monkeypatch.setenv("RAKUTEN_APPLICATION_ID", "test_app_id")
        monkeypatch.setenv("RAKUTEN_ACCESS_KEY", "test_access_key")

        with patch("src.evidence.lodging.requests.get", side_effect=req.RequestException("timeout")):
            with pytest.raises(RakutenLodgingError):
                fetch_lodging_options("箱根", "2026-06-01", "2026-06-02", 2, 20000, lat=35.23, lng=139.10)

    def test_skips_malformed_hotel_entry(self, monkeypatch):
        monkeypatch.setenv("RAKUTEN_APPLICATION_ID", "test_app_id")
        monkeypatch.setenv("RAKUTEN_ACCESS_KEY", "test_access_key")
>>>>>>> ceb6e75acce3b8a26f8b2b9ec473a1d540a81072

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "hotels": [
                {"hotel": [{"hotelBasicInfo": {}}]},  # name なし → None → スキップ
                _MOCK_HOTEL_ENTRY,
            ]
        }
        mock_resp.raise_for_status.return_value = None

        with patch("src.evidence.lodging.requests.get", return_value=mock_resp):
<<<<<<< HEAD
            result = fetch_lodging_options(lat=35.23, lng=139.10)
=======
            result = fetch_lodging_options("箱根", "2026-06-01", "2026-06-02", 2, 20000, lat=35.23, lng=139.10)
>>>>>>> ceb6e75acce3b8a26f8b2b9ec473a1d540a81072

        assert len(result) == 1
        assert result[0].name == "箱根温泉旅館 テスト館"

    def test_payload_uses_new_spec(self, monkeypatch):
        """Phase 3 polish 案 D: 新 endpoint + accessKey + lat/lng + searchRadius + datumType=1。"""
        _set_creds(monkeypatch)

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"hotels": []}
        mock_resp.raise_for_status.return_value = None

        with patch("src.evidence.lodging.requests.get", return_value=mock_resp) as m:
            fetch_lodging_options(lat=35.23, lng=139.10)

        args, kwargs = m.call_args
        # 新 endpoint
        assert args[0] == "https://openapi.rakuten.co.jp/engine/api/Travel/SimpleHotelSearch/20170426"
        params = kwargs["params"]
        # accessKey 必須
        assert params["accessKey"] == "test_access_key"
        # 緯度経度 + 半径
        assert params["latitude"] == 35.23
        assert params["longitude"] == 139.10
        assert params["searchRadius"] == 3.0
        # 世界測地系 (WGS84、度単位)
        assert params["datumType"] == 1
        # formatVersion=2 で JSON アクセス簡素化
        assert params["formatVersion"] == 2
        # checkinDate / checkoutDate / adultNum / maxCharge / keyword は spec に
        # 存在しないので含まれない
        assert "checkinDate" not in params
        assert "checkoutDate" not in params
        assert "adultNum" not in params
        assert "maxCharge" not in params
        assert "keyword" not in params

    def test_raises_on_invalid_search_radius(self, monkeypatch):
        """API 仕様 0.1〜3.0 km 外の値は事前 validation で raise。"""
        _set_creds(monkeypatch)
        with pytest.raises(RakutenLodgingError, match="searchRadius"):
            fetch_lodging_options(lat=35.23, lng=139.10, search_radius_km=5.0)
        with pytest.raises(RakutenLodgingError, match="searchRadius"):
            fetch_lodging_options(lat=35.23, lng=139.10, search_radius_km=0.05)
