"""Places API (New) クライアント。textSearch で候補スポットを取得する。

FieldMask で必要なフィールドに絞り、コスト（$0.017 × 基本セッション）と
LLM プロンプトの token 消費の両方を抑える。
"""

from __future__ import annotations

import os
from typing import Any

import requests

from .pack import PlacePoint

PLACES_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
REQUEST_TIMEOUT_SEC = 10.0

_FIELD_MASK = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.location",
        "places.regularOpeningHours.weekdayDescriptions",
        "places.priceLevel",
        "places.rating",
        "places.userRatingCount",
        "places.types",
    ]
)

_PRICE_LEVEL_MAP: dict[str, int | None] = {
    "PRICE_LEVEL_FREE": None,
    "PRICE_LEVEL_INEXPENSIVE": 1,
    "PRICE_LEVEL_MODERATE": 2,
    "PRICE_LEVEL_EXPENSIVE": 3,
    "PRICE_LEVEL_VERY_EXPENSIVE": 4,
}


class PlacesError(Exception):
    """Places API 呼び出しに失敗した時に投げる。"""


def search_by_text(
    query: str,
    *,
    language: str = "ja",
    region_code: str = "jp",
    max_results: int = 10,
    api_key: str | None = None,
) -> list[PlacePoint]:
    """テキスト検索を実行し、PlacePoint のリストを返す。

    見つからない場合は空リストを返す（例外ではない）。HTTP エラーや環境変数不在は
    PlacesError として上げる。
    """
    key = api_key or os.environ.get("GOOGLE_MAPS_API_KEY")
    if not key:
        raise PlacesError("GOOGLE_MAPS_API_KEY が未設定")

    payload = {
        "textQuery": query,
        "languageCode": language,
        "regionCode": region_code,
        "pageSize": max_results,
    }

    try:
        res = requests.post(
            PLACES_SEARCH_URL,
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": key,
                "X-Goog-FieldMask": _FIELD_MASK,
            },
            json=payload,
            timeout=REQUEST_TIMEOUT_SEC,
        )
    except requests.RequestException as e:
        raise PlacesError(f"Places API request failed: {type(e).__name__}: {e}") from e

    if not res.ok:
        raise PlacesError(f"Places API returned {res.status_code}: {res.text[:200]}")

    data = res.json()
    raw_places = data.get("places", [])
    return [_to_place_point(p) for p in raw_places]


def _to_place_point(raw: dict[str, Any]) -> PlacePoint:
    """Google の生レスポンスを PlacePoint に正規化する。"""
    location = raw.get("location") or {}
    display_name = raw.get("displayName") or {}
    opening = raw.get("regularOpeningHours") or {}
    price_level_str = raw.get("priceLevel")

    return PlacePoint(
        place_id=raw["id"],
        name=display_name.get("text", ""),
        category=list(raw.get("types", [])),
        lat=float(location.get("latitude", 0.0)),
        lng=float(location.get("longitude", 0.0)),
        address=raw.get("formattedAddress", ""),
        opening_hours=list(opening.get("weekdayDescriptions", [])),
        price_level=_PRICE_LEVEL_MAP.get(price_level_str) if price_level_str else None,
        rating=raw.get("rating"),
        user_ratings_total=raw.get("userRatingCount"),
        relevance_tags=[],
    )
