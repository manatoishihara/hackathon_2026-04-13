"""Transit Validator のユニットテスト（Phase 1.3c）。

`apps/api/src/evidence/validator.py` の `validate_client_transit_matrix` を検証する。
- Pydantic 層で値域・文字長・HH:mm はガード済み（`schemas.ClientTransitEdge`）
- 本テストは文脈依存の検証を担保:
  - place_id 所属 / 自己ループ / 件数上限 / 距離 / 重複（完全一致 drop・矛盾 reject）
"""

from __future__ import annotations

from datetime import date

import pytest

from src.evidence.pack import (
    BudgetBreakdownJPY,
    BudgetConstraints,
    EvidencePack,
    PlacePoint,
    QueryContext,
    QueryContextParticipant,
    TemporalConstraints,
    TransitEdge,
)
from src.evidence.validator import (
    HARD_CAP,
    MAX_EDGE_DISTANCE_KM,
    TransitMatrixValidationError,
    validate_client_transit_matrix,
)
from src.schemas import BudgetBreakdown, ClientTransitEdge


def _place(place_id: str, lat: float = 35.0, lng: float = 139.0) -> PlacePoint:
    return PlacePoint(
        place_id=place_id,
        name=f"p-{place_id}",
        category=[],
        lat=lat,
        lng=lng,
        address="addr",
        opening_hours=[],
        price_level=None,
        rating=None,
        user_ratings_total=None,
    )


def _pack(placemap: dict[str, tuple[float, float]] | list[str]) -> EvidencePack:
    """placemap は {id: (lat, lng)} か ["id1", "id2"] のどちらも受ける。"""
    if isinstance(placemap, list):
        points = [_place(pid) for pid in placemap]
    else:
        points = [_place(pid, lat, lng) for pid, (lat, lng) in placemap.items()]
    return EvidencePack(
        query_context=QueryContext(
            region="箱根",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 2),
            departure_point="新宿",
            start_mode="auto",
            mode_payload=None,
            participants=[QueryContextParticipant(name="a", wishes="", tags=[])],
        ),
        places=points,
        transit_matrix=[],
        budget_constraints=BudgetConstraints(
            total_jpy_per_person=30000,
            breakdown_percent=BudgetBreakdown(lodging=40, meal=30, activity=20, transit=10),
            breakdown_jpy=BudgetBreakdownJPY(lodging=12000, meal=9000, activity=6000, transit=3000),
        ),
        temporal_constraints=TemporalConstraints(
            start_datetime="2026-06-01T09:00:00+09:00",
            end_datetime="2026-06-02T20:00:00+09:00",
            total_days=2,
        ),
    )


def _edge(
    a: str,
    b: str,
    mode: str = "train",
    duration_min: int = 30,
    route_summary: str = "JR",
) -> ClientTransitEdge:
    return ClientTransitEdge(
        from_place_id=a,
        to_place_id=b,
        mode=mode,
        route_summary=route_summary,
        duration_min=duration_min,
        fare_jpy=500,
        candidate_departures=["09:00"],
    )


# ==============================
# 基本
# ==============================


def test_happy_path_returns_transit_edges():
    pack = _pack(["A", "B", "C"])
    edges = [_edge("A", "B"), _edge("B", "A"), _edge("A", "C")]
    result = validate_client_transit_matrix(edges, pack)
    assert len(result) == 3
    assert all(isinstance(e, TransitEdge) for e in result)
    assert {(e.from_place_id, e.to_place_id) for e in result} == {
        ("A", "B"), ("B", "A"), ("A", "C")
    }


def test_empty_edges_is_allowed():
    pack = _pack(["A", "B"])
    assert validate_client_transit_matrix([], pack) == []


def test_single_place_allows_only_empty():
    pack = _pack(["A"])
    assert validate_client_transit_matrix([], pack) == []
    with pytest.raises(TransitMatrixValidationError):
        validate_client_transit_matrix([_edge("A", "A")], pack)


def test_returns_transit_edge_preserves_all_fields():
    pack = _pack(["A", "B"])
    edge = ClientTransitEdge(
        from_place_id="A",
        to_place_id="B",
        mode="bus",
        route_summary="高速バス",
        duration_min=90,
        fare_jpy=1800,
        candidate_departures=["09:00", "10:30"],
    )
    [out] = validate_client_transit_matrix([edge], pack)
    assert out.from_place_id == "A"
    assert out.to_place_id == "B"
    assert out.mode == "bus"
    assert out.route_summary == "高速バス"
    assert out.duration_min == 90
    assert out.fare_jpy == 1800
    assert out.candidate_departures == ["09:00", "10:30"]


# ==============================
# place_id 所属
# ==============================


def test_unknown_from_place_id_is_rejected():
    pack = _pack(["A", "B"])
    with pytest.raises(TransitMatrixValidationError) as exc:
        validate_client_transit_matrix([_edge("Z", "B")], pack)
    assert "from_place_id" in str(exc.value)


def test_unknown_to_place_id_is_rejected():
    pack = _pack(["A", "B"])
    with pytest.raises(TransitMatrixValidationError) as exc:
        validate_client_transit_matrix([_edge("A", "Z")], pack)
    assert "to_place_id" in str(exc.value)


# ==============================
# 自己ループ
# ==============================


def test_self_loop_is_rejected():
    pack = _pack(["A", "B"])
    with pytest.raises(TransitMatrixValidationError) as exc:
        validate_client_transit_matrix([_edge("A", "A")], pack)
    assert "self" in str(exc.value).lower()


# ==============================
# 件数上限（hard cap と N*(N-1)）
# ==============================


def test_small_n_directed_edge_cap():
    # N=2, cap=min(HARD_CAP, 2*(2-1))=2
    pack = _pack(["A", "B"])
    edges = [
        _edge("A", "B", mode="train"),
        _edge("B", "A", mode="train"),
        _edge("A", "B", mode="bus"),
    ]
    with pytest.raises(TransitMatrixValidationError) as exc:
        validate_client_transit_matrix(edges, pack)
    assert "limit" in str(exc.value).lower() or "cap" in str(exc.value).lower() or "exceeds" in str(exc.value).lower()


def test_hard_cap_is_enforced_even_when_nn1_is_larger():
    """N が大きくて N*(N-1) >> HARD_CAP の場合、hard cap が効く。

    v2 の `i % len(ids)` 循環だと同じキーが重複生成され、cap 超過ではなく
    「矛盾重複」で落ちる偽陽性があった（Codex re-review 指摘）。
    ここでは `all_pairs` で一意な有向ペアを列挙し、先頭 HARD_CAP+1 件を採用することで
    「cap 超過のみで落ちる」ことを保証する。
    """
    # N=15 → 有向ペア 15*14=210 > HARD_CAP=200。同一座標で距離制約を回避
    ids = [f"p{i}" for i in range(15)]
    pack = _pack({pid: (35.0, 139.0) for pid in ids})

    all_pairs = [(i, j) for i in range(len(ids)) for j in range(len(ids)) if i != j]
    assert len(all_pairs) > HARD_CAP  # 事前アサート

    edges = [
        _edge(ids[i], ids[j], mode="train", route_summary=f"r-{i}-{j}")
        for (i, j) in all_pairs[: HARD_CAP + 1]
    ]
    # 各 (from, to, mode) が一意（dedupe で落ちない）
    keys = {(e.from_place_id, e.to_place_id, e.mode) for e in edges}
    assert len(keys) == len(edges)

    with pytest.raises(TransitMatrixValidationError) as exc:
        validate_client_transit_matrix(edges, pack)
    msg = str(exc.value).lower()
    assert "cap" in msg or "limit" in msg or "exceeds" in msg
    # 偽陽性ガード: 「矛盾」経路で落ちていないこと
    assert "conflict" not in msg and "duplicate" not in msg


def test_cap_is_evaluated_after_normalization():
    """完全一致重複の drop は cap 判定前に適用され、正規化後の件数で cap 比較する。"""
    # N=2, cap=2。完全一致 3 件送るが dedupe 後 1 件なので pass
    pack = _pack(["A", "B"])
    e = _edge("A", "B", mode="train")
    result = validate_client_transit_matrix([e, e, e], pack)
    assert len(result) == 1


# ==============================
# 距離上限
# ==============================


def test_distance_over_cap_is_rejected():
    # 東京(35.68, 139.69) と 大阪(34.70, 135.50) は ~400km
    pack = _pack({"T": (35.68, 139.69), "O": (34.70, 135.50)})
    with pytest.raises(TransitMatrixValidationError) as exc:
        validate_client_transit_matrix([_edge("T", "O")], pack)
    assert "distance" in str(exc.value).lower() or "km" in str(exc.value).lower()


def test_distance_exactly_within_cap_is_allowed():
    # 2 点を ~14.9km 離して置く（lat 差 ~0.134 度）
    pack = _pack({"A": (35.0, 139.0), "B": (35.134, 139.0)})
    result = validate_client_transit_matrix([_edge("A", "B")], pack)
    assert len(result) == 1


def test_same_coordinate_distance_zero_is_allowed():
    pack = _pack({"A": (35.0, 139.0), "B": (35.0, 139.0)})
    assert len(validate_client_transit_matrix([_edge("A", "B")], pack)) == 1


# ==============================
# 重複: 完全一致 drop / 矛盾 reject
# ==============================


def test_exact_duplicate_is_silently_dropped():
    pack = _pack(["A", "B", "C"])
    e1 = _edge("A", "B", mode="train", route_summary="JR", duration_min=30)
    e2 = _edge("A", "B", mode="train", route_summary="JR", duration_min=30)
    e3 = _edge("B", "A", mode="train")
    result = validate_client_transit_matrix([e1, e2, e3], pack)
    assert len(result) == 2
    ab = [r for r in result if (r.from_place_id, r.to_place_id) == ("A", "B")]
    assert len(ab) == 1


def test_conflicting_duplicate_is_rejected():
    """同じ (from,to,mode) で route_summary や duration_min が違うのは隠蔽リスク → reject。"""
    pack = _pack(["A", "B"])
    e1 = _edge("A", "B", mode="train", route_summary="JR", duration_min=30)
    e2 = _edge("A", "B", mode="train", route_summary="私鉄", duration_min=45)
    with pytest.raises(TransitMatrixValidationError) as exc:
        validate_client_transit_matrix([e1, e2], pack)
    assert "conflict" in str(exc.value).lower() or "duplicate" in str(exc.value).lower()


def test_different_mode_same_pair_is_allowed():
    """(A,B,train) と (A,B,bus) は key が違うので両方保持。"""
    pack = _pack(["A", "B"])
    e1 = _edge("A", "B", mode="train")
    e2 = _edge("A", "B", mode="bus")
    result = validate_client_transit_matrix([e1, e2], pack)
    assert len(result) == 2
    assert {r.mode for r in result} == {"train", "bus"}


# ==============================
# 順序の安定性（デバッグ容易性）
# ==============================


def test_output_preserves_input_order():
    pack = _pack(["A", "B", "C"])
    edges = [_edge("B", "A"), _edge("A", "C"), _edge("A", "B")]
    result = validate_client_transit_matrix(edges, pack)
    pairs = [(r.from_place_id, r.to_place_id) for r in result]
    assert pairs == [("B", "A"), ("A", "C"), ("A", "B")]


def test_max_edge_distance_constant_exposed():
    """validator の定数が import されている（回帰防止）。"""
    assert HARD_CAP == 200
    assert MAX_EDGE_DISTANCE_KM == 15.0
