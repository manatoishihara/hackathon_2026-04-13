"""外部 API のヘルスチェック。Phase 0.3 の疎通確認用。

各関数は最小限のリクエストを送り、成功/失敗を HealthResult で返す。
ネットワーク例外も HealthResult に畳み込んで raise しない（集約テスト向け）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import requests
from openai import OpenAI

REQUEST_TIMEOUT_SEC = 10.0


@dataclass
class HealthResult:
    service: str
    ok: bool
    status_code: int | None = None
    error: str | None = None


def check_google_places(api_key: str | None = None) -> HealthResult:
    """Places API (New) textSearch に最小リクエストを投げる。

    Reference: https://developers.google.com/maps/documentation/places/web-service/text-search
    """
    key = api_key or os.environ.get("GOOGLE_MAPS_API_KEY", "")
    if not key:
        return HealthResult("google_places", ok=False, error="GOOGLE_MAPS_API_KEY unset")

    try:
        res = requests.post(
            "https://places.googleapis.com/v1/places:searchText",
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": key,
                "X-Goog-FieldMask": "places.id,places.displayName",
            },
            json={"textQuery": "東京駅", "languageCode": "ja"},
            timeout=REQUEST_TIMEOUT_SEC,
        )
    except requests.RequestException as e:
        return HealthResult("google_places", ok=False, error=f"{type(e).__name__}: {e}")

    return HealthResult(
        "google_places",
        ok=res.ok,
        status_code=res.status_code,
        error=None if res.ok else res.text[:200],
    )


def check_google_routes(api_key: str | None = None) -> HealthResult:
    """Routes API computeRoutes に最小リクエストを投げる（東京駅→新宿駅、transit）。

    Reference: https://developers.google.com/maps/documentation/routes/compute_route_directions
    """
    key = api_key or os.environ.get("GOOGLE_MAPS_API_KEY", "")
    if not key:
        return HealthResult("google_routes", ok=False, error="GOOGLE_MAPS_API_KEY unset")

    try:
        res = requests.post(
            "https://routes.googleapis.com/directions/v2:computeRoutes",
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": key,
                "X-Goog-FieldMask": "routes.duration,routes.distanceMeters",
            },
            json={
                "origin": {"location": {"latLng": {"latitude": 35.681236, "longitude": 139.767125}}},
                "destination": {"location": {"latLng": {"latitude": 35.690921, "longitude": 139.700258}}},
                "travelMode": "TRANSIT",
                "languageCode": "ja",
            },
            timeout=REQUEST_TIMEOUT_SEC,
        )
    except requests.RequestException as e:
        return HealthResult("google_routes", ok=False, error=f"{type(e).__name__}: {e}")

    return HealthResult(
        "google_routes",
        ok=res.ok,
        status_code=res.status_code,
        error=None if res.ok else res.text[:200],
    )


def check_google_geocoding(api_key: str | None = None) -> HealthResult:
    """Geocoding API に最小リクエストを投げる。

    Reference: https://developers.google.com/maps/documentation/geocoding
    """
    key = api_key or os.environ.get("GOOGLE_MAPS_API_KEY", "")
    if not key:
        return HealthResult("google_geocoding", ok=False, error="GOOGLE_MAPS_API_KEY unset")

    try:
        res = requests.get(
            "https://maps.googleapis.com/maps/api/geocode/json",
            params={"address": "東京駅", "language": "ja", "key": key},
            timeout=REQUEST_TIMEOUT_SEC,
        )
    except requests.RequestException as e:
        return HealthResult("google_geocoding", ok=False, error=f"{type(e).__name__}: {e}")

    if not res.ok:
        return HealthResult("google_geocoding", ok=False, status_code=res.status_code, error=res.text[:200])

    # Geocoding API は 200 でも body の status が ERROR の場合があるので両方チェック
    body = res.json()
    api_status = body.get("status")
    return HealthResult(
        "google_geocoding",
        ok=(api_status == "OK"),
        status_code=res.status_code,
        error=None if api_status == "OK" else f"api_status={api_status}",
    )


def check_openai(api_key: str | None = None) -> HealthResult:
    """OpenAI API への疎通確認（models.list を叩く）。"""
    key = api_key or os.environ.get("OPENAI_API_KEY", "")
    if not key:
        return HealthResult("openai", ok=False, error="OPENAI_API_KEY unset")

    try:
        client = OpenAI(api_key=key, timeout=REQUEST_TIMEOUT_SEC)
        models = client.models.list()
        _ = list(models)[:1]  # 先頭だけ取って接続成立を確認
        return HealthResult("openai", ok=True, status_code=200)
    except Exception as e:
        return HealthResult("openai", ok=False, error=f"{type(e).__name__}: {str(e)[:200]}")


ALL_CHECKS = {
    "google_places": check_google_places,
    "google_routes": check_google_routes,
    "google_geocoding": check_google_geocoding,
    "openai": check_openai,
}


def run_all() -> dict[str, HealthResult]:
    """全チェックを実行し、service 名キーの dict で返す。"""
    return {name: fn() for name, fn in ALL_CHECKS.items()}
