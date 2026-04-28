"""Places API (New) クライアント。textSearch で候補スポットを取得する。

FieldMask で必要なフィールドに絞り、コスト（$0.017 × 基本セッション）と
LLM プロンプトの token 消費の両方を抑える。
"""

from __future__ import annotations

import os
from typing import Any

import requests

from .opening_hours import parse_weekday_descriptions
from .pack import PlacePoint

PLACES_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
PLACES_DETAILS_URL_TEMPLATE = "https://places.googleapis.com/v1/places/{place_id}"
REQUEST_TIMEOUT_SEC = 10.0

_FIELD_MASK = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.location",
        "places.regularOpeningHours.weekdayDescriptions",
        "places.priceLevel",
        "places.priceRange",
        "places.rating",
        "places.userRatingCount",
        "places.types",
    ]
)

# fetch_place_details (Phase 2.1 anchor mode 用) は単一 place 取得なので
# `places.` prefix なしの field 名を使う仕様。
_DETAILS_FIELD_MASK = ",".join(
    [
        "id",
        "displayName",
        "formattedAddress",
        "location",
        "regularOpeningHours.weekdayDescriptions",
        "priceLevel",
        "priceRange",
        "rating",
        "userRatingCount",
        "types",
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
    max_results: int = 20,
    api_key: str | None = None,
) -> list[PlacePoint]:
    """テキスト検索を実行し、PlacePoint のリストを返す。

    見つからない場合は空リストを返す（例外ではない）。HTTP エラーや環境変数不在は
    PlacesError として上げる。

    Phase 3 polish (2026-04-28、iconic spot coverage 改善):
    - `max_results` default を 10 → 20 (Places API New 上限) に拡張。母数倍増で
      ガイドブック系 iconic spot (大涌谷・芦ノ湖等) が pack に届く確率を上げる。
      箱根 3 日 plan で「彫刻の森・箱根神社 は入るが大涌谷・芦ノ湖は ranking 11+
      で取り逃す」事象を解消。詳細: tasks/lessons.md「Places API locationBias
      完全欠落」エントリ。
    - `rankPreference: "RELEVANCE"` 明示 (将来 Google API のデフォルト変更へ
      の防御、現状デフォルトと同じ)。
    """
    key = api_key or os.environ.get("GOOGLE_MAPS_API_KEY")
    if not key:
        raise PlacesError("GOOGLE_MAPS_API_KEY が未設定")

    payload = {
        "textQuery": query,
        "languageCode": language,
        "regionCode": region_code,
        "pageSize": max_results,
        "rankPreference": "RELEVANCE",
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


def fetch_place_details(
    place_id: str,
    *,
    language: str = "ja",
    api_key: str | None = None,
) -> PlacePoint | None:
    """Place ID 指定で 1 件だけ詳細取得する（Phase 2.1 anchor モード用）。

    見つからない (404) → None を返す。HTTP / 環境エラーは PlacesError を上げる。
    """
    key = api_key or os.environ.get("GOOGLE_MAPS_API_KEY")
    if not key:
        raise PlacesError("GOOGLE_MAPS_API_KEY が未設定")

    url = PLACES_DETAILS_URL_TEMPLATE.format(place_id=place_id)
    try:
        res = requests.get(
            url,
            headers={
                "X-Goog-Api-Key": key,
                "X-Goog-FieldMask": _DETAILS_FIELD_MASK,
                "Accept-Language": language,
            },
            params={"languageCode": language},
            timeout=REQUEST_TIMEOUT_SEC,
        )
    except requests.RequestException as e:
        raise PlacesError(f"Places Details request failed: {type(e).__name__}: {e}") from e

    if res.status_code == 404:
        return None
    if not res.ok:
        raise PlacesError(f"Places Details returned {res.status_code}: {res.text[:200]}")

    return _to_place_point(res.json())


def _parse_price_range_jpy(price_range: dict[str, Any] | None) -> tuple[int, int] | None:
    """Places API (New) priceRange を (start_jpy, end_jpy) に変換する。

    priceRange の構造:
        { "startPrice": { "currencyCode": "JPY", "units": "1000", "nanos": 0 },
          "endPrice":   { "currencyCode": "JPY", "units": "2000", "nanos": 0 } }

    JPY 以外の通貨や、start/end どちらか欠落、不正値 (start > end など) は None。
    nanos は JPY では常に 0 想定なので無視 (units だけ採用)。
    """
    if not isinstance(price_range, dict):
        return None
    start = price_range.get("startPrice") or {}
    end = price_range.get("endPrice") or {}
    if start.get("currencyCode") != "JPY" or end.get("currencyCode") != "JPY":
        return None
    try:
        start_units = int(start.get("units", 0))
        end_units = int(end.get("units", 0))
    except (TypeError, ValueError):
        return None
    if start_units < 0 or end_units < 0 or start_units > end_units:
        return None
    return (start_units, end_units)


def _to_place_point(raw: dict[str, Any]) -> PlacePoint:
    """Google の生レスポンスを PlacePoint に正規化する。"""
    location = raw.get("location") or {}
    display_name = raw.get("displayName") or {}
    opening = raw.get("regularOpeningHours") or {}
    price_level_str = raw.get("priceLevel")
    price_range_jpy = _parse_price_range_jpy(raw.get("priceRange"))

    weekday_descriptions = list(opening.get("weekdayDescriptions", []))
    parsed_hours = parse_weekday_descriptions(weekday_descriptions)

    return PlacePoint(
        place_id=raw["id"],
        name=display_name.get("text", ""),
        category=list(raw.get("types", [])),
        lat=float(location.get("latitude", 0.0)),
        lng=float(location.get("longitude", 0.0)),
        address=raw.get("formattedAddress", ""),
        opening_hours=parsed_hours.slots,
        opening_hours_unknown_days=parsed_hours.unknown_days,
        price_level=_PRICE_LEVEL_MAP.get(price_level_str) if price_level_str else None,
        rating=raw.get("rating"),
        user_ratings_total=raw.get("userRatingCount"),
        relevance_tags=[],
        price_range_jpy=price_range_jpy,
    )
