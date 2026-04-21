"""Routes API クライアント（DRIVE モード）。

**JP transit 対応の経緯**:
Routes API / Legacy Directions API はどちらも **日本国内の公共交通情報を
サーバーサイドから返さない**。Google Maps の consumer 版（maps.google.com や
Maps JavaScript API の DirectionsService）だけが Jorudan / Navitime と提携した
日本の transit を返す。この制約は 2026-04 時点で存続中（tasks/lessons.md 参照）。

そのため本モジュールは **DRIVE モード**で所要時間・距離を返す設計に変更した:
- Phase 1.2 の Evidence Pack Builder は transit_matrix を空で返し、
  フロント（Phase 1.3 で実装）が Maps JS SDK で transit を埋める
- 本モジュールの `compute_drive_estimate` はサーバー側の補助用途として残す:
  - Phase 2 の「手動編集・部分再生成」で並び替え直後に所要時間を再計算するとき
  - フロントが DirectionsService を使えない環境（SSR プレビュー等）でのフォールバック
- 返す `TransitEdge.mode` は常に `"car"`、`fare_jpy` は常に `None`、
  `route_summary` は `"車で約○○分"`
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any

import requests

from .pack import TransitEdge

ROUTES_COMPUTE_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
REQUEST_TIMEOUT_SEC = 10.0

_FIELD_MASK = "routes.duration,routes.distanceMeters"


class RoutesError(Exception):
    """Routes API 呼び出しに失敗した時に投げる。"""


def compute_drive_estimate(
    origin_place_id: str,
    destination_place_id: str,
    *,
    departure_time: datetime,
    language: str = "ja",
    api_key: str | None = None,
) -> TransitEdge | None:
    """2 点間の運転所要時間を DRIVE モードで取得し、TransitEdge に包んで返す。

    - 経路が見つからない場合は None
    - HTTP エラーは RoutesError として raise
    - 日本国内の transit（電車・バス）詳細は取れない。必要ならフロント側の
      Maps JS SDK DirectionsService を使う（Phase 1.3）

    Args:
        origin_place_id: 起点の Google Places ID
        destination_place_id: 終点の Google Places ID
        departure_time: 出発時刻（tzinfo 未指定は UTC 扱い）
        language: レスポンス言語
        api_key: 明示指定する場合。省略時は GOOGLE_MAPS_API_KEY 環境変数
    """
    key = api_key or os.environ.get("GOOGLE_MAPS_API_KEY")
    if not key:
        raise RoutesError("GOOGLE_MAPS_API_KEY が未設定")

    if departure_time.tzinfo is None:
        departure_time = departure_time.replace(tzinfo=timezone.utc)
    departure_iso = departure_time.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    payload: dict[str, Any] = {
        "origin": {"placeId": origin_place_id},
        "destination": {"placeId": destination_place_id},
        "travelMode": "DRIVE",
        "departureTime": departure_iso,
        "languageCode": language,
    }

    try:
        res = requests.post(
            ROUTES_COMPUTE_URL,
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": key,
                "X-Goog-FieldMask": _FIELD_MASK,
            },
            json=payload,
            timeout=REQUEST_TIMEOUT_SEC,
        )
    except requests.RequestException as e:
        raise RoutesError(f"Routes API request failed: {type(e).__name__}: {e}") from e

    if not res.ok:
        raise RoutesError(f"Routes API returned {res.status_code}: {res.text[:200]}")

    try:
        data = res.json()
    except ValueError as e:
        raise RoutesError(f"Routes API returned invalid JSON: {e}") from e

    routes = data.get("routes") or []
    if not routes:
        return None

    duration_sec = _parse_duration_seconds(routes[0].get("duration"))
    if duration_sec is None:
        # duration が欠損 or 解析不能 → 黙って「車で約0分」を作らず、None で「経路なし扱い」
        return None
    duration_min = duration_sec // 60
    departure_hhmm = departure_time.strftime("%H:%M")

    return TransitEdge(
        from_place_id=origin_place_id,
        to_place_id=destination_place_id,
        mode="car",
        route_summary=f"車で約{duration_min}分",
        duration_min=duration_min,
        fare_jpy=None,
        candidate_departures=[departure_hhmm],
    )


def _parse_duration_seconds(dur: str | None) -> int | None:
    """Routes API の duration は "123s" 形式の文字列。秒数に変換する。

    Google Protobuf Duration の仕様で "1234.567s" のような小数点付きもあり得るので、
    正規表現で数値部分だけ取り出して int に丸める。

    欠損や解析不能時は **None** を返す（呼び出し側で「経路なし」扱いにするため）。
    0 を返してしまうと「車で約0分」という壊れた TransitEdge が静かに作られる。
    """
    if not dur:
        return None
    m = re.match(r"^(\d+(?:\.\d+)?)s$", dur)
    if not m:
        return None
    return int(float(m.group(1)))
