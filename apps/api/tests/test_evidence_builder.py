"""Evidence Pack Builder のユニットテスト（モック）と integration テスト。

Phase 1.2 では builder は transit_matrix を埋めない（フロントが Phase 1.3 で
Maps JS SDK から取得する）。places / budget / temporal / query_context の組み立て
のみ検証する。
"""

from __future__ import annotations

import os
from datetime import date
from unittest.mock import patch

import pytest

from src.evidence.builder import (
    _dedupe_and_cap,
    _generate_keywords,
    build_evidence_pack,
)
from src.evidence.pack import PlacePoint, QueryContext, QueryContextParticipant
from src.schemas import (
    BudgetBreakdown,
    GeneratePlanRequest,
    ParticipantInput,
)


def _sample_request(**overrides) -> GeneratePlanRequest:
    defaults: dict = dict(
        title="箱根温泉旅",
        region="箱根",
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 2),
        departure_point="新宿駅",
        budget_per_person_jpy=30000,
        budget_breakdown=BudgetBreakdown(lodging=40, meal=30, activity=20, transit=10),
        start_mode="auto",
        mode_payload=None,
        participants=[
            ParticipantInput(
                display_name="太郎",
                avatar_color="#D97757",
                wishes_text="ゆったり温泉に浸かりたい",
                tags=["温泉", "和食"],
                order_index=0,
            ),
            ParticipantInput(
                display_name="花子",
                avatar_color="#2C5F5D",
                wishes_text="美味しいもの食べたい",
                tags=["カフェ"],
                order_index=1,
            ),
        ],
    )
    defaults.update(overrides)
    return GeneratePlanRequest(**defaults)


def _place(place_id: str, name: str, lat: float, lng: float) -> PlacePoint:
    return PlacePoint(
        place_id=place_id,
        name=name,
        category=["tourist_attraction"],
        lat=lat,
        lng=lng,
        address="神奈川県箱根町",
        opening_hours=[],
        price_level=None,
        rating=None,
        user_ratings_total=None,
    )


# ==============================
# キーワード生成
# ==============================


def test_generate_keywords_includes_region_and_tags():
    ctx = QueryContext(
        region="箱根",
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 2),
        departure_point="新宿駅",
        start_mode="auto",
        mode_payload=None,
        participants=[
            QueryContextParticipant(name="太郎", wishes="w", tags=["温泉", "和食"]),
            QueryContextParticipant(name="花子", wishes="w", tags=["カフェ"]),
        ],
    )
    keywords = _generate_keywords(ctx)
    assert "箱根 観光" in keywords
    assert "箱根 飲食" in keywords
    assert "箱根 温泉" in keywords
    assert "箱根 和食" in keywords
    assert "箱根 カフェ" in keywords
    assert len(keywords) == 5


def test_generate_keywords_caps_tags_at_3():
    ctx = QueryContext(
        region="京都",
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 2),
        departure_point="東京駅",
        start_mode="auto",
        mode_payload=None,
        participants=[
            QueryContextParticipant(
                name="A",
                wishes="w",
                tags=["神社", "和菓子", "紅葉", "茶道", "着物"],
            )
        ],
    )
    keywords = _generate_keywords(ctx)
    assert len(keywords) == 5


# ==============================
# Dedupe + cap
# ==============================


def test_dedupe_preserves_first_occurrence():
    batch_a = [_place("p1", "A", 0, 0), _place("p2", "B", 0, 0)]
    batch_b = [_place("p2", "B-dup", 0, 0), _place("p3", "C", 0, 0)]
    unique = _dedupe_and_cap([batch_a, batch_b], cap=10)
    ids = [p.place_id for p in unique]
    assert ids == ["p1", "p2", "p3"]
    assert unique[1].name == "B"


def test_dedupe_caps_total_count():
    batches = [[_place(f"p{i}", str(i), 0, 0) for i in range(20)]]
    unique = _dedupe_and_cap(batches, cap=5)
    assert len(unique) == 5


# ==============================
# build_evidence_pack（places のみ、transit はフロント側で後埋め）
# ==============================


@patch("src.evidence.builder.search_by_text")
def test_build_evidence_pack_assembles_structure(mock_search):
    mock_search.return_value = [
        _place("p1", "箱根神社", 35.20, 139.02),
        _place("p2", "箱根湯本駅", 35.23, 139.10),
    ]

    req = _sample_request()
    pack = build_evidence_pack(req)

    # query_context
    assert pack.query_context.region == "箱根"
    assert len(pack.query_context.participants) == 2

    # places: 5 キーワード × 2 スポット = 10、dedupe で 2 つに
    assert len(pack.places) == 2
    assert {p.place_id for p in pack.places} == {"p1", "p2"}

    # transit_matrix: Phase 1.2 では常に空（フロントが埋める）
    assert pack.transit_matrix == []

    # budget: 30000 × 40/30/20/10 = 12000/9000/6000/3000
    assert pack.budget_constraints.total_jpy_per_person == 30000
    assert pack.budget_constraints.breakdown_jpy.lodging == 12000
    assert pack.budget_constraints.breakdown_jpy.meal == 9000
    assert pack.budget_constraints.breakdown_jpy.activity == 6000
    assert pack.budget_constraints.breakdown_jpy.transit == 3000

    # temporal: 2 日間
    assert pack.temporal_constraints.total_days == 2
    assert pack.temporal_constraints.start_datetime.hour == 9


@patch("src.evidence.builder.search_by_text")
def test_search_failure_does_not_abort_build(mock_search):
    """Places API の 1 クエリが失敗しても他のクエリは続行する（fail-soft）。"""
    from src.evidence.places import PlacesError

    call_count = {"n": 0}

    def search_side_effect(query: str):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise PlacesError("network error on keyword 2")
        return [_place(f"p{call_count['n']}", query, 35.0 + call_count["n"] * 0.001, 139.0)]

    mock_search.side_effect = search_side_effect

    req = _sample_request()
    pack = build_evidence_pack(req)

    assert len(pack.places) >= 1
    assert pack.transit_matrix == []


@patch("src.evidence.builder.search_by_text")
def test_all_searches_failing_still_returns_pack(mock_search):
    """全 Places クエリが失敗しても、空 places で pack は返る（LLM 側で空処理可）。"""
    from src.evidence.places import PlacesError

    mock_search.side_effect = PlacesError("everything broken")
    pack = build_evidence_pack(_sample_request())
    assert pack.places == []
    assert pack.transit_matrix == []
    # budget/temporal は Places の成否と無関係に計算される
    assert pack.budget_constraints.total_jpy_per_person == 30000


# ==============================
# Integration（ライブ Places API、transit はフロント task なのでここでは検証しない）
# ==============================


def _has_real_maps_key() -> bool:
    val = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    return len(val) >= 20 and val.startswith("AIza")


@pytest.mark.integration
@pytest.mark.skipif(not _has_real_maps_key(), reason="GOOGLE_MAPS_API_KEY not set")
def test_integration_build_hakone_pack():
    """箱根の小さな Evidence Pack を実 API で構築。places だけ検証。

    コストは Places 検索 5 回分（推定 $0.1 未満）。transit はフロント側で後埋めする
    ので、integration テストでも transit_matrix=[] が期待値。
    """
    req = GeneratePlanRequest(
        title="箱根日帰り",
        region="箱根",
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 1),
        departure_point="新宿駅",
        budget_per_person_jpy=20000,
        budget_breakdown=BudgetBreakdown(lodging=0, meal=40, activity=30, transit=30),
        start_mode="auto",
        mode_payload=None,
        participants=[
            ParticipantInput(
                display_name="太郎",
                avatar_color="#D97757",
                wishes_text="温泉と和食",
                tags=["温泉", "和食"],
                order_index=0,
            ),
        ],
    )
    pack = build_evidence_pack(req)

    assert len(pack.places) > 0, "箱根で places が 1 件も取れないのは Places API の問題"
    assert all(p.place_id for p in pack.places)
    assert pack.transit_matrix == []
    assert pack.budget_constraints.total_jpy_per_person == 20000
    assert pack.budget_constraints.breakdown_jpy.lodging == 0
