"""`apps/api/src/llm/assembly.py` のユニットテスト（Phase 1.3e Structured Plan Assembly）。"""

from __future__ import annotations

from datetime import date

import pytest

from src.evidence.pack import (
    BudgetBreakdownJPY,
    BudgetConstraints,
    EvidencePack,
    OpeningHoursSlot,
    PlacePoint,
    QueryContext,
    TemporalConstraints,
    TransitEdge,
)
from src.llm.assembly import (
    NoFeasibleTransitError,
    UnknownPlaceInSlotError,
    UnknownSlotIdError,
    assemble_plan,
    generate_slot_catalog,
)
from src.llm.schema import LlmGeneratedPlanV2, LlmSlotAssignment
from src.schemas import BudgetBreakdown


def _make_pack(
    *,
    places: list[PlacePoint],
    edges: list[TransitEdge],
    total_days: int = 2,
) -> EvidencePack:
    return EvidencePack(
        query_context=QueryContext(
            region="箱根",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 1 + total_days - 1),
            departure_point="新宿駅",
            start_mode="auto",
            mode_payload=None,
            participants=[],
        ),
        places=places,
        transit_matrix=edges,
        budget_constraints=BudgetConstraints(
            total_jpy_per_person=30000,
            breakdown_percent=BudgetBreakdown(lodging=40, meal=30, activity=20, transit=10),
            breakdown_jpy=BudgetBreakdownJPY(lodging=12000, meal=9000, activity=6000, transit=3000),
        ),
        temporal_constraints=TemporalConstraints(
            start_datetime=f"2026-06-01T09:00:00+09:00",
            end_datetime=f"2026-06-0{total_days}T20:00:00+09:00",
            total_days=total_days,
        ),
    )


def _place(
    place_id: str,
    name: str = "spot",
    opening: list[tuple[int, str, str]] | None = None,
    price_level: int | None = 2,
    category: list[str] | None = None,
) -> PlacePoint:
    opening = opening or [(dow, "09:00", "22:00") for dow in range(7)]
    return PlacePoint(
        place_id=place_id,
        name=name,
        category=category or ["point_of_interest"],
        lat=35.2,
        lng=139.0,
        address="箱根",
        opening_hours=[
            OpeningHoursSlot(day_of_week=dow, open_hhmm=o, close_hhmm=c)
            for dow, o, c in opening
        ],
        opening_hours_unknown_days=[],
        price_level=price_level,
        rating=4.0,
        user_ratings_total=100,
        relevance_tags=[],
    )


def _edge(a: str, b: str, *, duration: int = 20, fare: int | None = 400) -> TransitEdge:
    return TransitEdge(
        from_place_id=a,
        to_place_id=b,
        mode="train",
        route_summary="箱根登山",
        duration_min=duration,
        fare_jpy=fare,
        candidate_departures=["09:00"],
    )


# ==============================
# slot catalog
# ==============================


def test_generate_slot_catalog_2_days_skips_lodging_on_last_day():
    catalog = generate_slot_catalog(total_days=2)
    ids = [c["slot_id"] for c in catalog]
    # 1 日目: 5 slot (morning/lunch/afternoon/dinner/lodging)、2 日目: 4 slot (lodging なし)
    assert ids == [
        "day1_morning",
        "day1_lunch",
        "day1_afternoon",
        "day1_dinner",
        "day1_lodging",
        "day2_morning",
        "day2_lunch",
        "day2_afternoon",
        "day2_dinner",
    ]


def test_generate_slot_catalog_1_day_has_no_lodging():
    catalog = generate_slot_catalog(total_days=1)
    ids = [c["slot_id"] for c in catalog]
    assert "day1_lodging" not in ids
    assert ids == ["day1_morning", "day1_lunch", "day1_afternoon", "day1_dinner"]


# ==============================
# assemble_plan happy path
# ==============================


def test_assemble_plan_with_two_slots_inserts_transit_between():
    p_a = _place("P_A", name="強羅公園")
    p_b = _place("P_B", name="そば処")
    pack = _make_pack(places=[p_a, p_b], edges=[_edge("P_A", "P_B")])

    plan_v2 = LlmGeneratedPlanV2(
        slots=[
            LlmSlotAssignment(slot_id="day1_morning", place_id="P_A", rationale="太郎の自然希望に合致する公園"),
            LlmSlotAssignment(slot_id="day1_lunch", place_id="P_B", rationale="そば好きの花子に配慮"),
        ]
    )
    result = assemble_plan(plan_v2, pack)

    assert len(result.items) == 3  # activity, transit, meal
    kinds = [i.item_type for i in result.items]
    assert kinds == ["activity", "transit", "meal"]

    transit = result.items[1]
    assert transit.transit_ref is not None
    assert transit.transit_ref.from_place_id == "P_A"
    assert transit.transit_ref.to_place_id == "P_B"
    assert transit.cost_jpy == 400

    meal = result.items[2]
    # price_level=2 meal → 2500 estimated
    assert meal.cost_jpy == 2500
    assert meal.cost_confidence == "estimated"


def test_assemble_plan_empty_slots_returns_empty_items():
    pack = _make_pack(places=[], edges=[])
    result = assemble_plan(LlmGeneratedPlanV2(slots=[]), pack)
    assert result.items == []


# ==============================
# エラー系
# ==============================


def test_assemble_plan_unknown_slot_id_raises():
    pack = _make_pack(places=[_place("P_A")], edges=[])
    plan_v2 = LlmGeneratedPlanV2(
        slots=[
            LlmSlotAssignment(
                slot_id="day99_morning",
                place_id="P_A",
                rationale="test case for unknown slot_id handling",
            )
        ]
    )
    with pytest.raises(UnknownSlotIdError):
        assemble_plan(plan_v2, pack)


def test_assemble_plan_unknown_place_id_raises():
    pack = _make_pack(places=[_place("P_A")], edges=[])
    plan_v2 = LlmGeneratedPlanV2(
        slots=[
            LlmSlotAssignment(
                slot_id="day1_morning",
                place_id="P_does_not_exist",
                rationale="test case for unknown place_id handling",
            )
        ]
    )
    with pytest.raises(UnknownPlaceInSlotError):
        assemble_plan(plan_v2, pack)


def test_assemble_plan_missing_transit_edge_raises_when_no_alternate():
    p_a = _place("P_A")
    p_b = _place("P_B")
    # edges 空 = 2 slot 連続使用で transit が取れず、代替候補も存在しない
    pack = _make_pack(places=[p_a, p_b], edges=[])
    plan_v2 = LlmGeneratedPlanV2(
        slots=[
            LlmSlotAssignment(slot_id="day1_morning", place_id="P_A", rationale="ok 12chars"),
            LlmSlotAssignment(slot_id="day1_lunch", place_id="P_B", rationale="needs transit 40 yen"),
        ]
    )
    with pytest.raises(NoFeasibleTransitError):
        assemble_plan(plan_v2, pack)


# ==============================
# 代替選定ロジック
# ==============================


def test_assemble_plan_substitutes_alternate_place_when_direct_transit_missing():
    """P_A→P_B edge がない場合、同カテゴリ P_C（P_A→P_C edge あり）に差し替える。"""
    p_a = _place("P_A", name="起点", category=["tourist_attraction"])
    p_b = _place("P_B", name="そば処B", category=["restaurant", "japanese"])
    # C は B と同じ category[0]=restaurant で、P_A→P_C edge が存在
    p_c = _place("P_C", name="定食屋C", category=["restaurant", "japanese"])
    pack = _make_pack(
        places=[p_a, p_b, p_c],
        edges=[_edge("P_A", "P_C", fare=380)],  # A→B は無い、A→C のみ
    )
    plan_v2 = LlmGeneratedPlanV2(
        slots=[
            LlmSlotAssignment(slot_id="day1_morning", place_id="P_A", rationale="起点テストのため 10 文字"),
            LlmSlotAssignment(
                slot_id="day1_lunch",
                place_id="P_B",
                rationale="代替選定が P_C に振り替える想定",
            ),
        ]
    )
    result = assemble_plan(plan_v2, pack)
    # activity → transit(A→C) → meal(P_C) の 3 items
    assert len(result.items) == 3
    assert result.items[1].item_type == "transit"
    assert result.items[1].transit_ref is not None
    assert result.items[1].transit_ref.to_place_id == "P_C"
    assert result.items[2].place_id == "P_C"
    assert result.items[2].cost_jpy == 2500  # price_level=2 meal カタログ


def test_assemble_plan_alternate_selection_prefers_higher_rating():
    """複数候補のうち rating 最高を採用する。"""
    p_a = _place("P_A", category=["tourist_attraction"])
    p_target = _place("P_target", category=["restaurant"])
    p_low = _place("P_low", category=["restaurant"])
    p_high = _place("P_high", category=["restaurant"])
    # rating を上書き
    p_low = p_low.model_copy(update={"rating": 3.0})
    p_high = p_high.model_copy(update={"rating": 4.8})
    pack = _make_pack(
        places=[p_a, p_target, p_low, p_high],
        edges=[
            _edge("P_A", "P_low"),
            _edge("P_A", "P_high"),
            # P_A → P_target edge は無い
        ],
    )
    plan_v2 = LlmGeneratedPlanV2(
        slots=[
            LlmSlotAssignment(slot_id="day1_morning", place_id="P_A", rationale="起点テストの 10 文字超"),
            LlmSlotAssignment(
                slot_id="day1_lunch",
                place_id="P_target",
                rationale="rating 高い P_high が選ばれるはず",
            ),
        ]
    )
    result = assemble_plan(plan_v2, pack)
    meal = result.items[2]
    assert meal.place_id == "P_high"


def test_assemble_plan_alternate_selection_respects_category_match():
    """target と共通 category を 1 つも持たない候補は選ばれない。"""
    p_a = _place("P_A", category=["tourist_attraction"])
    p_target = _place("P_target", category=["restaurant"])
    p_wrong_category = _place("P_cafe", category=["cafe"])  # restaurant との共通なし
    pack = _make_pack(
        places=[p_a, p_target, p_wrong_category],
        edges=[_edge("P_A", "P_cafe")],  # cafe のみ到達可能だが category 共通なし
    )
    plan_v2 = LlmGeneratedPlanV2(
        slots=[
            LlmSlotAssignment(slot_id="day1_morning", place_id="P_A", rationale="起点テストの 10 文字超"),
            LlmSlotAssignment(
                slot_id="day1_lunch",
                place_id="P_target",
                rationale="category が合わない候補しかないので raise 想定",
            ),
        ]
    )
    with pytest.raises(NoFeasibleTransitError):
        assemble_plan(plan_v2, pack)


def test_assemble_plan_alternate_selection_loose_category_intersection():
    """category リストの 1 要素でも共通していればマッチ（Google Places の階層対応）。

    target=`[yakiniku_restaurant, restaurant, food]`、候補=`[sushi_restaurant, restaurant]`
    なら `restaurant` の共通でマッチする（`category[0]` 厳密一致では落ちていたケース）。
    """
    p_a = _place("P_A", category=["tourist_attraction"])
    p_target = _place(
        "P_target", category=["yakiniku_restaurant", "restaurant", "food"]
    )
    p_alt = _place("P_alt", category=["sushi_restaurant", "restaurant"])
    pack = _make_pack(
        places=[p_a, p_target, p_alt],
        edges=[_edge("P_A", "P_alt")],
    )
    plan_v2 = LlmGeneratedPlanV2(
        slots=[
            LlmSlotAssignment(
                slot_id="day1_morning", place_id="P_A", rationale="起点テスト 10 文字以上"
            ),
            LlmSlotAssignment(
                slot_id="day1_lunch",
                place_id="P_target",
                rationale="restaurant 共通で alt が採択されるべき",
            ),
        ]
    )
    result = assemble_plan(plan_v2, pack)
    assert result.items[-1].place_id == "P_alt"


def test_assemble_plan_transit_departure_time_picks_from_candidate_departures():
    """transit_ref.departure_time は edge.candidate_departures のいずれかに一致する
    必要がある（validator TRANSIT_DEPARTURE_MISMATCH 対策）。slot 遷移 11:30 基準で
    候補 ["09:00", "12:00"] のうち最早で start_dt 以降の "12:00" が選ばれる。
    """
    p_a = _place("P_A", category=["point_of_interest"])
    p_b = _place("P_B", category=["point_of_interest"])
    # candidate_departures を 2 つ、両者ともテストケース用
    edge_ab = TransitEdge(
        from_place_id="P_A",
        to_place_id="P_B",
        mode="train",
        route_summary="candidate 選定テスト用",
        duration_min=20,
        fare_jpy=500,
        candidate_departures=["09:00", "12:00"],
    )
    pack = _make_pack(places=[p_a, p_b], edges=[edge_ab])
    plan_v2 = LlmGeneratedPlanV2(
        slots=[
            LlmSlotAssignment(slot_id="day1_morning", place_id="P_A", rationale="起点 slot 10 文字"),
            LlmSlotAssignment(slot_id="day1_lunch", place_id="P_B", rationale="transit 遷移検証用"),
        ]
    )
    result = assemble_plan(plan_v2, pack)
    # items = [activity(P_A), transit(A→B), meal(P_B)]
    transit = result.items[1]
    assert transit.transit_ref is not None
    # morning slot 終了 11:30 → 以降の最早 candidate "12:00" が採択される
    assert transit.transit_ref.departure_time == "12:00"


def test_assemble_plan_transit_departure_time_fallbacks_to_max_when_all_earlier():
    """全 candidate_departures が start_dt より前なら、validator に弾かせる想定で最遅を返す。"""
    p_a = _place("P_A", category=["point_of_interest"])
    p_b = _place("P_B", category=["point_of_interest"])
    edge_ab = TransitEdge(
        from_place_id="P_A",
        to_place_id="P_B",
        mode="train",
        route_summary="fallback テスト",
        duration_min=20,
        fare_jpy=500,
        candidate_departures=["06:00", "07:00"],  # 全て morning 終了前
    )
    pack = _make_pack(places=[p_a, p_b], edges=[edge_ab])
    plan_v2 = LlmGeneratedPlanV2(
        slots=[
            LlmSlotAssignment(slot_id="day1_morning", place_id="P_A", rationale="起点 slot 10 文字"),
            LlmSlotAssignment(slot_id="day1_lunch", place_id="P_B", rationale="departure fallback"),
        ]
    )
    result = assemble_plan(plan_v2, pack)
    transit = result.items[1]
    assert transit.transit_ref is not None
    # 全候補が prev_end_dt より前なので、最遅 "07:00" を採用（validator で時系列エラーになる想定）
    assert transit.transit_ref.departure_time == "07:00"


def test_assemble_plan_alternate_selection_avoids_self_loop():
    """LLM が連続 slot に同じ place を割当てた場合、代替選定で from_place_id 自身は避ける。"""
    p_a = _place("P_A", category=["point_of_interest"])
    p_b = _place("P_B", category=["point_of_interest"])
    pack = _make_pack(
        places=[p_a, p_b],
        edges=[_edge("P_A", "P_B")],
    )
    plan_v2 = LlmGeneratedPlanV2(
        slots=[
            LlmSlotAssignment(
                slot_id="day1_morning", place_id="P_A", rationale="起点 slot のテスト内容"
            ),
            LlmSlotAssignment(
                slot_id="day1_lunch",
                place_id="P_A",  # 同じ id で自己ループリクエスト
                rationale="自己ループ禁止テストの rationale",
            ),
        ]
    )
    result = assemble_plan(plan_v2, pack)
    # 代替選定で P_B に差し替えられる（P_A 自身は candidate から除外）
    assert result.items[-1].place_id == "P_B"


# ==============================
# opening_hours 照合
# ==============================


def test_assemble_plan_fits_time_into_opening_hours():
    """slot day1_morning=09:00-11:30 に対し、place が 10:00-12:00 しか空いていなければ
    start_time は 10:00 に繰り下がる（重なり優先）。"""
    # 2026-06-01 = 月曜 = dow 0
    p = _place("P_A", opening=[(0, "10:00", "12:00")])
    pack = _make_pack(places=[p], edges=[])
    plan_v2 = LlmGeneratedPlanV2(
        slots=[
            LlmSlotAssignment(slot_id="day1_morning", place_id="P_A", rationale="opening_hours 調整の検証"),
        ]
    )
    result = assemble_plan(plan_v2, pack)
    assert len(result.items) == 1
    item = result.items[0]
    # start_time は 10:00 に寄せられる（重なり 10:00-11:30 で最大重複）
    assert "T10:00:00" in item.start_time
    assert "T11:30:00" in item.end_time


def test_assemble_plan_cost_for_unknown_price_level():
    """price_level=None の meal は jpy マップの None 行から取り、cost_confidence=unknown。"""
    p = _place("P_A", price_level=None)
    pack = _make_pack(places=[p], edges=[])
    plan_v2 = LlmGeneratedPlanV2(
        slots=[
            LlmSlotAssignment(slot_id="day1_lunch", place_id="P_A", rationale="price_level null case"),
        ]
    )
    result = assemble_plan(plan_v2, pack)
    assert len(result.items) == 1
    meal = result.items[0]
    assert meal.cost_jpy == 2500
    assert meal.cost_confidence == "unknown"
