"""フロントが送る `ClientTransitEdge` を Evidence Pack と照合して検証する純関数。

Pydantic 層（`schemas.ClientTransitEdge`）で値域・文字長・HH:mm は既にガード済み。
`PlanGenerationPayload` の `max_length=200` で静的 hard cap もかかる。本モジュールは
以下の **文脈依存の検証** を担う:

1. from/to の place_id が Evidence Pack.places に含まれる
2. from == to（自己ループ）を拒否
3. 件数上限 min(HARD_CAP, N*(N-1)) を正規化後件数で判定（N = |pack.places|）
4. 距離上限（haversine）: MAX_EDGE_DISTANCE_KM 超は reject
5. (from, to, mode) 3-tuple 重複:
   - 完全一致（全フィールド値が等しい、`candidate_departures` は **順序を保持したリスト比較**）
     → silently drop
   - 矛盾（key 一致で他フィールド値が違う）→ reject（隠蔽リスク防止）
   - **注**: `candidate_departures` の要素集合が同じでも順序が違う場合は「矛盾」扱い。
     現状フロントは 1 要素固定なので顕在化しないが、将来複数化時に再検討する
     （順序に意味がない配列として扱うなら `frozenset` ベース比較に切り替える）。

距離は haversine 公式で計算する。フロント transit.ts の haversineKm と同一アルゴリズム
（半径 6371km）。挙動は単体テストで固定している。
"""

from __future__ import annotations

from math import asin, cos, radians, sin, sqrt

from ..schemas import ClientTransitEdge
from .pack import EvidencePack, PlacePoint, TransitEdge

HARD_CAP: int = 200
"""transit_matrix に許容する有向エッジ数の絶対上限（N*(N-1) と比較して小さい方を採用）。"""

MAX_EDGE_DISTANCE_KM: float = 15.0
"""1 エッジの許容距離上限。フロント側は 10km フィルタだが、浮動小数点誤差と将来の余裕を込めて 15km。"""


class TransitMatrixValidationError(ValueError):
    """文脈依存の transit_matrix バリデーション失敗。ルート側は 400 に翻訳。"""


def _haversine_km(a: PlacePoint, b: PlacePoint) -> float:
    """フロント transit.ts の haversineKm と同一アルゴリズム（半径 6371km）。"""
    R = 6371.0
    dlat = radians(b.lat - a.lat)
    dlng = radians(b.lng - a.lng)
    lat1 = radians(a.lat)
    lat2 = radians(b.lat)
    h = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlng / 2) ** 2
    return 2 * R * asin(sqrt(h))


def _conflict(existing: ClientTransitEdge, incoming: ClientTransitEdge) -> bool:
    """完全一致なら False、矛盾なら True。key ((from,to,mode)) は既に一致している前提。

    `candidate_departures` は順序を保持したリスト比較（docstring 冒頭の注を参照）。
    """
    return (
        existing.route_summary != incoming.route_summary
        or existing.duration_min != incoming.duration_min
        or existing.fare_jpy != incoming.fare_jpy
        or list(existing.candidate_departures) != list(incoming.candidate_departures)
    )


def validate_client_transit_matrix(
    edges: list[ClientTransitEdge],
    pack: EvidencePack,
) -> list[TransitEdge]:
    places_by_id: dict[str, PlacePoint] = {p.place_id: p for p in pack.places}
    n = len(places_by_id)

    normalized_order: list[ClientTransitEdge] = []
    seen_by_key: dict[tuple[str, str, str], ClientTransitEdge] = {}

    for e in edges:
        # 場所の所属
        if e.from_place_id not in places_by_id:
            raise TransitMatrixValidationError(
                f"unknown from_place_id: {e.from_place_id!r} is not in pack.places"
            )
        if e.to_place_id not in places_by_id:
            raise TransitMatrixValidationError(
                f"unknown to_place_id: {e.to_place_id!r} is not in pack.places"
            )
        # 自己ループ
        if e.from_place_id == e.to_place_id:
            raise TransitMatrixValidationError(
                f"self-loop edge is not allowed: {e.from_place_id}"
            )
        # 距離（place_id の所属が確認できてから座標参照）
        dist = _haversine_km(places_by_id[e.from_place_id], places_by_id[e.to_place_id])
        if dist > MAX_EDGE_DISTANCE_KM:
            raise TransitMatrixValidationError(
                f"edge distance {dist:.2f}km exceeds MAX_EDGE_DISTANCE_KM={MAX_EDGE_DISTANCE_KM} "
                f"({e.from_place_id} → {e.to_place_id})"
            )

        # 重複処理
        key = (e.from_place_id, e.to_place_id, e.mode)
        if key in seen_by_key:
            if _conflict(seen_by_key[key], e):
                raise TransitMatrixValidationError(
                    f"conflicting duplicate edge for {key}: "
                    f"existing and incoming disagree on attribute values"
                )
            # 完全一致 → silently drop
            continue
        seen_by_key[key] = e
        normalized_order.append(e)

    # 正規化後件数で cap 判定
    cap = min(HARD_CAP, n * (n - 1))
    if len(normalized_order) > cap:
        raise TransitMatrixValidationError(
            f"transit_matrix length {len(normalized_order)} after dedupe exceeds cap {cap} "
            f"(HARD_CAP={HARD_CAP}, |places|={n})"
        )

    return [
        TransitEdge(
            from_place_id=e.from_place_id,
            to_place_id=e.to_place_id,
            mode=e.mode,
            route_summary=e.route_summary,
            duration_min=e.duration_min,
            fare_jpy=e.fare_jpy,
            candidate_departures=list(e.candidate_departures),
        )
        for e in normalized_order
    ]
