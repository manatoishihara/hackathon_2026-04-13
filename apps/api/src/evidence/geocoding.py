"""Google Geocoding API クライアント (region → lat/lng 変換)。

主な用途:
- 楽天トラベル SimpleHotelSearch API は緯度経度 + searchRadius (0.1〜3.0 km) での
  検索を要求するので、region 文字列 (例: "箱根") を lat/lng に変換する必要がある
- 将来的に Phase 3 polish の locationBias (Places API search の地理制約) にも流用可能

Reference: https://developers.google.com/maps/documentation/geocoding/start
"""

from __future__ import annotations

import logging
import os
from typing import Any

import requests

logger = logging.getLogger(__name__)

GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
REQUEST_TIMEOUT_SEC = 5.0


class GeocodingError(Exception):
    """Geocoding API 呼び出し失敗。"""


def geocode_region(
    region: str,
    *,
    language: str = "ja",
    region_code: str = "jp",
    api_key: str | None = None,
) -> tuple[float, float] | None:
    """region 文字列 (例: "箱根") を (lat, lng) に変換する。

    見つからない (ZERO_RESULTS) → None。HTTP エラーや環境変数不在は GeocodingError raise。
    成功時は世界測地系 (WGS84)、度単位の (latitude, longitude) を返す。

    Args:
        region: ジオコーディング対象の文字列。region 名 (「箱根」「京都」等) や
                住所文字列を想定。
        language: レスポンス言語。
        region_code: バイアスとして与える ISO 国コード (デフォルト "jp")。
        api_key: 明示指定する場合。省略時は GOOGLE_MAPS_API_KEY 環境変数。

    Returns:
        (lat, lng) のタプル (世界測地系・度単位)、または None (見つからない時)。

    Raises:
        GeocodingError: API 呼び出し失敗 (HTTP / network / 認証等)。
    """
    key = api_key or os.environ.get("GOOGLE_MAPS_API_KEY")
    if not key:
        raise GeocodingError("GOOGLE_MAPS_API_KEY が未設定")

    params: dict[str, Any] = {
        "address": region,
        "language": language,
        "region": region_code,
        "key": key,
    }

    try:
        res = requests.get(GEOCODE_URL, params=params, timeout=REQUEST_TIMEOUT_SEC)
    except requests.RequestException as e:
        raise GeocodingError(
            f"Geocoding API request failed: {type(e).__name__}: {e}"
        ) from e

    if not res.ok:
        raise GeocodingError(f"Geocoding API returned {res.status_code}: {res.text[:200]}")

    try:
        data = res.json()
    except ValueError as e:
        raise GeocodingError(f"Geocoding API returned invalid JSON: {e}") from e

    status = data.get("status")
    if status == "ZERO_RESULTS":
        logger.info("geocode_region: ZERO_RESULTS for region=%r", region)
        return None
    if status != "OK":
        raise GeocodingError(
            f"Geocoding API status={status!r}: {data.get('error_message', '')[:200]}"
        )

    results = data.get("results") or []
    if not results:
        return None

    location = results[0].get("geometry", {}).get("location") or {}
    lat = location.get("lat")
    lng = location.get("lng")
    if lat is None or lng is None:
        return None
    return (float(lat), float(lng))
