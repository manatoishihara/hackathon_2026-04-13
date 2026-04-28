"""Places API クライアントのユニットテスト（モック）と integration テスト。"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from src.evidence.places import PlacesError, search_by_text

# ==============================
# Unit tests
# ==============================


def test_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    with pytest.raises(PlacesError, match="未設定"):
        search_by_text("箱根 温泉")


@patch("src.evidence.places.requests.post")
def test_search_builds_request_correctly(mock_post):
    mock_post.return_value = MagicMock(ok=True, status_code=200, **{"json.return_value": {"places": []}})
    search_by_text("箱根 温泉", api_key="fake-key", max_results=7)

    args, kwargs = mock_post.call_args
    assert args[0] == "https://places.googleapis.com/v1/places:searchText"
    assert kwargs["headers"]["X-Goog-Api-Key"] == "fake-key"
    # FieldMask に必須フィールドが含まれている
    fm = kwargs["headers"]["X-Goog-FieldMask"]
    assert "places.id" in fm
    assert "places.displayName" in fm
    assert "places.regularOpeningHours.weekdayDescriptions" in fm
    # payload
    body = kwargs["json"]
    assert body["textQuery"] == "箱根 温泉"
    assert body["languageCode"] == "ja"
    assert body["regionCode"] == "jp"
    assert body["pageSize"] == 7
    # Phase 3 polish (2026-04-28、iconic spot coverage 改善):
    # rankPreference を明示しておく (RELEVANCE は現状の Google デフォルトと
    # 同等だが、将来 Google API のデフォルト変更への防御として明示維持)。
    assert body["rankPreference"] == "RELEVANCE"


@patch("src.evidence.places.requests.post")
def test_search_default_max_results_is_20(mock_post):
    """Phase 3 polish (2026-04-28): max_results default を 10 → 20 に拡張済。

    iconic spot (大涌谷・芦ノ湖等) が Google relevance ranking 11+ 位に来た
    場合に取り逃さないため、Google Places API New 上限の 20 を default に。
    """
    mock_post.return_value = MagicMock(
        ok=True, status_code=200, **{"json.return_value": {"places": []}}
    )
    search_by_text("箱根 観光地", api_key="fake-key")
    body = mock_post.call_args[1]["json"]
    assert body["pageSize"] == 20


@patch("src.evidence.places.requests.post")
def test_empty_results_returns_empty_list(mock_post):
    """架空のスポット名で 0 件ヒットしても空リストで返す（例外にしない）。"""
    mock_post.return_value = MagicMock(ok=True, status_code=200, **{"json.return_value": {}})
    result = search_by_text("架空のスポット名xyzzy", api_key="fake-key")
    assert result == []


@patch("src.evidence.places.requests.post")
def test_http_error_raises_places_error(mock_post):
    mock_post.return_value = MagicMock(ok=False, status_code=403, text="FORBIDDEN")
    with pytest.raises(PlacesError, match="403"):
        search_by_text("箱根 温泉", api_key="fake-key")


@patch("src.evidence.places.requests.post")
def test_network_exception_wrapped_as_places_error(mock_post):
    import requests

    mock_post.side_effect = requests.ConnectionError("boom")
    with pytest.raises(PlacesError, match="ConnectionError"):
        search_by_text("箱根 温泉", api_key="fake-key")


@patch("src.evidence.places.requests.post")
def test_response_parsed_to_place_point(mock_post):
    mock_post.return_value = MagicMock(
        ok=True,
        status_code=200,
        **{
            "json.return_value": {
                "places": [
                    {
                        "id": "ChIJabc123",
                        "displayName": {"text": "箱根神社"},
                        "formattedAddress": "神奈川県足柄下郡箱根町元箱根80-1",
                        "location": {"latitude": 35.204, "longitude": 139.025},
                        "regularOpeningHours": {
                            "weekdayDescriptions": [
                                "月曜日: 9:00～17:00",
                                "火曜日: 9:00～17:00",
                            ]
                        },
                        "priceLevel": "PRICE_LEVEL_MODERATE",
                        "rating": 4.5,
                        "userRatingCount": 1200,
                        "types": ["place_of_worship", "tourist_attraction"],
                    }
                ]
            }
        },
    )
    result = search_by_text("箱根 神社", api_key="fake-key")
    assert len(result) == 1
    p = result[0]
    assert p.place_id == "ChIJabc123"
    assert p.name == "箱根神社"
    assert p.lat == 35.204
    assert p.lng == 139.025
    assert p.price_level == 2  # MODERATE -> 2
    assert p.rating == 4.5
    assert p.user_ratings_total == 1200
    assert "tourist_attraction" in p.category
    assert len(p.opening_hours) == 2
    assert p.relevance_tags == []


@patch("src.evidence.places.requests.post")
def test_missing_optional_fields_become_none(mock_post):
    mock_post.return_value = MagicMock(
        ok=True,
        status_code=200,
        **{
            "json.return_value": {
                "places": [
                    {
                        "id": "x1",
                        "displayName": {"text": "ミニマル"},
                        "formattedAddress": "",
                        "location": {"latitude": 0.0, "longitude": 0.0},
                    }
                ]
            }
        },
    )
    result = search_by_text("q", api_key="fake-key")
    assert len(result) == 1
    p = result[0]
    assert p.rating is None
    assert p.user_ratings_total is None
    assert p.price_level is None
    assert p.opening_hours == []
    assert p.category == []


# ==============================
# priceRange (Places API New) パーステスト (Phase 3 polish 第 9 段, 2026-04-28)
# ==============================


def test_to_place_point_extracts_price_range_jpy():
    """priceRange が JPY で取れているとき (start, end) tuple を抽出する。"""
    from src.evidence.places import _to_place_point

    raw = {
        "id": "ChIJtest123",
        "displayName": {"text": "テスト食堂"},
        "formattedAddress": "東京都...",
        "location": {"latitude": 35.0, "longitude": 139.0},
        "types": ["restaurant"],
        "priceRange": {
            "startPrice": {"currencyCode": "JPY", "units": "1000", "nanos": 0},
            "endPrice": {"currencyCode": "JPY", "units": "2000", "nanos": 0},
        },
    }
    place = _to_place_point(raw)
    assert place.price_range_jpy == (1000, 2000)


def test_to_place_point_price_range_absent_returns_none():
    """priceRange field 自体が無いときは None。"""
    from src.evidence.places import _to_place_point

    raw = {
        "id": "ChIJtest456",
        "displayName": {"text": "テスト店"},
        "formattedAddress": "...",
        "location": {"latitude": 35.0, "longitude": 139.0},
        "types": ["restaurant"],
    }
    place = _to_place_point(raw)
    assert place.price_range_jpy is None


def test_to_place_point_price_range_non_jpy_returns_none():
    """JPY 以外の通貨は採用しない。"""
    from src.evidence.places import _to_place_point

    raw = {
        "id": "ChIJtest789",
        "displayName": {"text": "テスト店"},
        "formattedAddress": "...",
        "location": {"latitude": 35.0, "longitude": 139.0},
        "types": ["restaurant"],
        "priceRange": {
            "startPrice": {"currencyCode": "USD", "units": "10"},
            "endPrice": {"currencyCode": "USD", "units": "20"},
        },
    }
    place = _to_place_point(raw)
    assert place.price_range_jpy is None


def test_to_place_point_price_range_invalid_units_returns_none():
    """start > end など不正値は None。"""
    from src.evidence.places import _to_place_point

    raw = {
        "id": "ChIJtestbad",
        "displayName": {"text": "テスト店"},
        "formattedAddress": "...",
        "location": {"latitude": 35.0, "longitude": 139.0},
        "types": ["restaurant"],
        "priceRange": {
            "startPrice": {"currencyCode": "JPY", "units": "5000"},
            "endPrice": {"currencyCode": "JPY", "units": "1000"},
        },
    }
    place = _to_place_point(raw)
    assert place.price_range_jpy is None


# ==============================
# Integration（ライブ API）
# ==============================


def _has_real_maps_key() -> bool:
    val = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    return len(val) >= 20 and val.startswith("AIza")


@pytest.mark.integration
@pytest.mark.skipif(not _has_real_maps_key(), reason="GOOGLE_MAPS_API_KEY not set")
def test_integration_hakone_yumoto_returns_real_place():
    """箱根湯本駅で検索 → place_id と opening_hours を含む結果が返る。"""
    results = search_by_text("箱根湯本駅", max_results=3)
    assert len(results) > 0, "expected at least one hit for 箱根湯本駅"
    first = results[0]
    assert first.place_id  # 空でない
    assert first.name  # 空でない
    # 駅自体は 24h 営業で opening_hours が空のこともあるので、rating か user_ratings_total のどちらかは必ず返ってくるはず
    assert first.rating is not None or first.user_ratings_total is not None


@pytest.mark.integration
@pytest.mark.skipif(not _has_real_maps_key(), reason="GOOGLE_MAPS_API_KEY not set")
def test_integration_gibberish_returns_empty():
    """完全にランダムな文字列では 0 件、または関連性の低い結果でも落ちない。"""
    results = search_by_text("xxx架空の場所xxxabcxyz999", max_results=3)
    # 完全な 0 件が期待値だが Google が類似推論で何か返すこともある。落ちないことだけ保証
    assert isinstance(results, list)
