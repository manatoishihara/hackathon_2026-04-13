"""楽天トラベル SimpleHotelSearch API クライアントのユニットテスト。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.evidence.lodging import RakutenLodgingError, fetch_lodging_options

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
                max_charge_per_night=20000,
                lat=35.23,
                lng=139.10,
            )

        assert len(result) == 1
        hotel = result[0]
        assert hotel.name == "箱根温泉旅館 テスト館"
        assert hotel.price_jpy_per_night == 15000  # hotelMinCharge を使用
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
            result = fetch_lodging_options("箱根", "2026-06-01", "2026-06-02", 2, 20000, lat=35.23, lng=139.10)

        assert len(result) == 1
        assert result[0].name == "箱根温泉旅館 テスト館"
