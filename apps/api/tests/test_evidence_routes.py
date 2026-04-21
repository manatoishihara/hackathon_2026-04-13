"""Routes API クライアント（DRIVE モード）のユニットテストと integration テスト。

Phase 1.2 では Google Directions/Routes の日本 transit 対応不在を回避するため、
サーバー側は DRIVE モードで所要時間のみ取得する。transit 詳細（電車便名・運賃）は
フロント側 Maps JS SDK DirectionsService で補完する（Phase 1.3）。
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from src.evidence.routes import (
    RoutesError,
    _parse_duration_seconds,
    compute_drive_estimate,
)

JST = ZoneInfo("Asia/Tokyo")


# ==============================
# Helpers
# ==============================


def test_parse_duration_seconds():
    assert _parse_duration_seconds("123s") == 123
    assert _parse_duration_seconds("5400s") == 5400
    assert _parse_duration_seconds("12.5s") == 12  # int truncation
    # 欠損・解析不能は None（0 を返すと壊れた TransitEdge が作られる）
    assert _parse_duration_seconds(None) is None
    assert _parse_duration_seconds("") is None
    assert _parse_duration_seconds("abc") is None
    assert _parse_duration_seconds("123") is None  # 末尾 s が無い
    assert _parse_duration_seconds("s") is None


# ==============================
# compute_drive_estimate (mocked)
# ==============================


def test_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    with pytest.raises(RoutesError, match="未設定"):
        compute_drive_estimate("a", "b", departure_time=datetime(2026, 6, 1, 9, 0, tzinfo=JST))


@patch("src.evidence.routes.requests.post")
def test_builds_request_with_place_ids_and_drive_mode(mock_post):
    mock_post.return_value = MagicMock(ok=True, status_code=200, **{"json.return_value": {"routes": []}})
    compute_drive_estimate(
        "origin_id",
        "dest_id",
        departure_time=datetime(2026, 6, 1, 9, 0, tzinfo=JST),
        api_key="fake-key",
    )

    args, kwargs = mock_post.call_args
    assert args[0] == "https://routes.googleapis.com/directions/v2:computeRoutes"
    body = kwargs["json"]
    assert body["origin"] == {"placeId": "origin_id"}
    assert body["destination"] == {"placeId": "dest_id"}
    assert body["travelMode"] == "DRIVE"  # TRANSIT ではなく DRIVE
    # JST 09:00 -> UTC 00:00
    assert body["departureTime"].endswith("T00:00:00Z")


@patch("src.evidence.routes.requests.post")
def test_no_routes_returns_none(mock_post):
    mock_post.return_value = MagicMock(ok=True, status_code=200, **{"json.return_value": {"routes": []}})
    result = compute_drive_estimate(
        "a", "b", departure_time=datetime(2026, 6, 1, 9, 0, tzinfo=JST), api_key="fake-key"
    )
    assert result is None


@patch("src.evidence.routes.requests.post")
def test_drive_response_parsed_to_car_transit_edge(mock_post):
    """DRIVE レスポンスが TransitEdge(mode='car', fare_jpy=None) に正規化される。"""
    mock_post.return_value = MagicMock(
        ok=True,
        status_code=200,
        **{
            "json.return_value": {
                "routes": [
                    {
                        "duration": "5400s",  # 90 min
                        "distanceMeters": 98000,
                    }
                ]
            }
        },
    )
    edge = compute_drive_estimate(
        "shinjuku",
        "hakone",
        departure_time=datetime(2026, 6, 1, 9, 15, tzinfo=JST),
        api_key="fake-key",
    )
    assert edge is not None
    assert edge.from_place_id == "shinjuku"
    assert edge.to_place_id == "hakone"
    assert edge.duration_min == 90
    assert edge.mode == "car"
    assert edge.fare_jpy is None  # DRIVE モードは運賃を持たない
    assert "車で約90分" == edge.route_summary
    assert edge.candidate_departures == ["09:15"]


@patch("src.evidence.routes.requests.post")
def test_http_error_raises_routes_error(mock_post):
    mock_post.return_value = MagicMock(ok=False, status_code=400, text="bad request")
    with pytest.raises(RoutesError, match="400"):
        compute_drive_estimate(
            "a", "b", departure_time=datetime(2026, 6, 1, 9, 0, tzinfo=JST), api_key="fake-key"
        )


@patch("src.evidence.routes.requests.post")
def test_invalid_json_body_raises_routes_error(mock_post):
    mock_response = MagicMock(ok=True, status_code=200, text="<html>nope</html>")
    mock_response.json.side_effect = ValueError("not json")
    mock_post.return_value = mock_response
    with pytest.raises(RoutesError, match="invalid JSON"):
        compute_drive_estimate(
            "a", "b", departure_time=datetime(2026, 6, 1, 9, 0, tzinfo=JST), api_key="fake-key"
        )


@patch("src.evidence.routes.requests.post")
def test_missing_duration_returns_none(mock_post):
    """routes 配列に duration が無い異常レスポンスでは静かに 0 分を作らず None で返す。"""
    mock_post.return_value = MagicMock(
        ok=True,
        status_code=200,
        **{"json.return_value": {"routes": [{"distanceMeters": 5000}]}},
    )
    result = compute_drive_estimate(
        "a", "b", departure_time=datetime(2026, 6, 1, 9, 0, tzinfo=JST), api_key="fake-key"
    )
    assert result is None


@patch("src.evidence.routes.requests.post")
def test_naive_datetime_treated_as_utc(mock_post):
    mock_post.return_value = MagicMock(ok=True, status_code=200, **{"json.return_value": {"routes": []}})
    compute_drive_estimate(
        "a", "b", departure_time=datetime(2026, 6, 1, 9, 0), api_key="fake-key"
    )
    body = mock_post.call_args.kwargs["json"]
    assert body["departureTime"] == "2026-06-01T09:00:00Z"


@patch("src.evidence.routes.requests.post")
def test_network_exception_wrapped(mock_post):
    import requests as _req

    mock_post.side_effect = _req.ConnectionError("boom")
    with pytest.raises(RoutesError, match="ConnectionError"):
        compute_drive_estimate(
            "a", "b", departure_time=datetime(2026, 6, 1, 9, 0, tzinfo=JST), api_key="fake-key"
        )


# ==============================
# Integration（ライブ API）
# ==============================


def _has_real_maps_key() -> bool:
    val = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    return len(val) >= 20 and val.startswith("AIza")


@pytest.mark.integration
@pytest.mark.skipif(not _has_real_maps_key(), reason="GOOGLE_MAPS_API_KEY not set")
def test_integration_shinjuku_to_hakone_yumoto_drive():
    """新宿駅 → 箱根湯本駅 で DRIVE 経路が返る。

    DRIVE モードは日本でも正常動作する（Routes API の TRANSIT は JP 未対応なため
    DRIVE で代用、transit 詳細はフロント JS SDK から取る、tasks/lessons.md 参照）。
    departure_time は 3 日後を使う（Routes API のダイヤ確定 window に合わせる）。
    """
    from src.evidence.places import search_by_text

    shinjuku = search_by_text("新宿駅", max_results=1)
    hakone = search_by_text("箱根湯本駅", max_results=1)
    assert shinjuku and hakone

    near_future = datetime.combine(
        date.today() + timedelta(days=3), datetime.min.time().replace(hour=9), tzinfo=JST
    )
    edge = compute_drive_estimate(
        shinjuku[0].place_id,
        hakone[0].place_id,
        departure_time=near_future,
    )
    assert edge is not None, "DRIVE mode should always return a route for JP metro areas"
    assert edge.mode == "car"
    assert edge.fare_jpy is None
    assert edge.duration_min > 30  # 新宿→箱根湯本は 90〜180 分（交通状況次第）
    assert "車で約" in edge.route_summary
