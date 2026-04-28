"""`apps/api/src/llm/assembly.py` のユニットテスト（Phase 1.3e Structured Plan Assembly）。"""

from __future__ import annotations

from datetime import date

import pytest

from src.evidence.pack import (
    BudgetBreakdownJPY,
    BudgetConstraints,
    EvidencePack,
    LodgingOption,
    OpeningHoursSlot,
    PlacePoint,
    QueryContext,
    TemporalConstraints,
    TransitEdge,
)
from src.llm.assembly import (
    AnchorMissingError,
    IneligiblePlaceForSlotError,
    NoFeasibleTransitError,
    UnknownPlaceInSlotError,
    UnknownSlotIdError,
    assemble_plan,
    compute_eligible_slot_ids_for_place,
    generate_slot_catalog,
    is_place_eligible_for_slot,
)
from src.llm.schema import LlmGeneratedPlanV2, LlmPlanItem, LlmSlotAssignment, LlmTransitRef
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


def _edge(
    a: str,
    b: str,
    *,
    duration: int = 20,
    fare: int | None = 400,
    candidate_departures: list[str] | None = None,
) -> TransitEdge:
    """test helper. デフォルトの candidate_departures は 2 日プランの全 transit（朝〜夕）を
    覆うよう 5 点配置（Codex Major fix で `_pick_departure_time` が過去時刻 fallback を
    廃止したため、morning〜lodging 全シフトを含む候補が必要）。
    """
    return TransitEdge(
        from_place_id=a,
        to_place_id=b,
        mode="train",
        route_summary="箱根登山",
        duration_min=duration,
        fare_jpy=fare,
        candidate_departures=candidate_departures
        or ["09:00", "12:00", "15:00", "18:00", "21:00"],
    )


# ==============================
# per-slot tailored places (Phase 1.3e 改修(iv))
# ==============================


def test_is_place_eligible_for_slot_overlap_returns_true():
    """月曜 10:00-20:00 営業 → 月曜 morning slot (09:00-11:30) と重なる → True"""
    place = _place("P", opening=[(0, "10:00", "20:00")])
    assert is_place_eligible_for_slot(
        place, slot_start_hhmm="09:00", slot_end_hhmm="11:30", date_=date(2026, 6, 1)
    ) is True


def test_is_place_eligible_for_slot_closed_day_returns_false():
    """月曜のみ営業 → 火曜の slot は False（定休日）"""
    place = _place("P", opening=[(0, "09:00", "20:00")])
    assert is_place_eligible_for_slot(
        place, slot_start_hhmm="09:00", slot_end_hhmm="11:30", date_=date(2026, 6, 2)
    ) is False


def test_is_place_eligible_for_slot_no_time_overlap_returns_false():
    """月曜ランチタイムのみ営業 (11:00-14:00) → morning slot (09:00-10:30) と重ならない → False"""
    place = _place("P", opening=[(0, "11:00", "14:00")])
    assert is_place_eligible_for_slot(
        place, slot_start_hhmm="09:00", slot_end_hhmm="10:30", date_=date(2026, 6, 1)
    ) is False


def test_is_place_eligible_for_slot_empty_opening_hours_returns_true():
    """opening_hours 空 → 検証スキップ → eligible 扱い"""
    place = PlacePoint(
        place_id="P",
        name="X",
        category=["restaurant"],
        lat=0,
        lng=0,
        address="",
        opening_hours=[],
        opening_hours_unknown_days=[],
        price_level=1,
        rating=4.0,
        user_ratings_total=10,
        relevance_tags=[],
    )
    assert is_place_eligible_for_slot(
        place, slot_start_hhmm="09:00", slot_end_hhmm="11:30", date_=date(2026, 6, 1)
    ) is True


def test_is_place_eligible_for_slot_unknown_day_returns_true():
    """opening_hours_unknown_days に当該曜日が含まれる → 検証スキップ → eligible 扱い"""
    place = PlacePoint(
        place_id="P",
        name="X",
        category=["restaurant"],
        lat=0,
        lng=0,
        address="",
        opening_hours=[OpeningHoursSlot(day_of_week=0, open_hhmm="09:00", close_hhmm="20:00")],
        opening_hours_unknown_days=[1],  # 火曜は不明
        price_level=1,
        rating=4.0,
        user_ratings_total=10,
        relevance_tags=[],
    )
    # 火曜の slot に対して unknown_day なので True
    assert is_place_eligible_for_slot(
        place, slot_start_hhmm="09:00", slot_end_hhmm="11:30", date_=date(2026, 6, 2)
    ) is True


def test_compute_eligible_slot_ids_for_place_filters_correctly():
    """Phase 1.3e (iv): slot_catalog に対して place が eligible な slot_id 配列を返す。

    LLM プロンプトの per-place `eligible_for_slots` フィールド構築用。
    """
    # 月曜 09:00-12:00 + 火曜 14:00-20:00 だけ営業
    place = _place(
        "P",
        opening=[
            (0, "09:00", "12:00"),  # Mon morning + lunch
            (1, "14:00", "20:00"),  # Tue afternoon + dinner
        ],
    )
    catalog = generate_slot_catalog(total_days=2)
    eligible = compute_eligible_slot_ids_for_place(
        place, slot_catalog=catalog, base_date=date(2026, 6, 1)  # 月始まり
    )
    # day1 (月) 09:00-12:00 営業 → morning (09:00-11:30) ✓ + lunch (12:00-13:30) は 12:00 ピッタリ ✗ (open < end かつ start < close 判定で 12:00 < 13:30 ∧ 09:00 < 12:00 → True)
    # 注: 半開区間判定 [open, close) と [slot_start, slot_end) で重なりチェック
    assert "day1_morning" in eligible
    # day1 lunch slot 12:00-13:30 に対し place 営業 09:00-12:00 → close=12:00, start=12:00 → 重ならない
    assert "day1_lunch" not in eligible
    # day1 afternoon (14:00-16:30): place は 12:00 まで → 含まれない
    assert "day1_afternoon" not in eligible
    # day2 (火) 14:00-20:00: morning (09:00-11:30) は重ならない
    assert "day2_morning" not in eligible
    # day2 lunch (12:00-13:30): 重ならない
    assert "day2_lunch" not in eligible
    # day2 afternoon (14:00-16:30): 重なる ✓
    assert "day2_afternoon" in eligible
    # day2 dinner (18:00-19:30): 重なる ✓
    assert "day2_dinner" in eligible


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


def test_assemble_plan_resolves_case_mismatched_place_id():
    """Phase 1.3e run 7 救済: LLM (特に gpt-4o-mini fallback) が pack の place_id を
    大文字小文字違いで生成するケースを救済する。

    Google Places ID は本来 case-sensitive だが、LLM が `ChIJFc0R0G-...` を
    `ChIJFC0R0G-...` のように生成するパターンが run 7 で観測された。
    pack に case-insensitive で一致するなら canonical id へ正規化して受け入れる
    （これは厳密一致を破る救済策、validator 的には UNKNOWN_PLACE_ID 回避目的）。
    """
    p_a = _place("ChIJFc0R0G-jGWARNMTt10zT2GY", name="HAKONE PICNIC")
    pack = _make_pack(places=[p_a], edges=[])
    plan_v2 = LlmGeneratedPlanV2(
        slots=[
            LlmSlotAssignment(
                slot_id="day1_morning",
                place_id="ChIJFC0R0G-jGWARNMTt10zT2GY",  # 大文字小文字違い
                rationale="case mismatch from gpt-4o-mini fallback",
            )
        ]
    )
    result = assemble_plan(plan_v2, pack)
    # 救済成功: エラーにならず、canonical id で結果に出る
    activity = next(i for i in result.items if i.item_type == "activity")
    assert activity.place_id == "ChIJFc0R0G-jGWARNMTt10zT2GY"


def test_assemble_plan_rejects_truly_unknown_place_id_even_after_case_check():
    """case-insensitive でも一致しない id は依然 UnknownPlaceInSlotError（hallucination 検出維持）。"""
    pack = _make_pack(places=[_place("ChIJABC")], edges=[])
    plan_v2 = LlmGeneratedPlanV2(
        slots=[
            LlmSlotAssignment(
                slot_id="day1_morning",
                place_id="ChIJXYZ",  # case を大文字小文字無視しても一致しない
                rationale="genuinely hallucinated id",
            )
        ]
    )
    with pytest.raises(UnknownPlaceInSlotError):
        assemble_plan(plan_v2, pack)


def test_assemble_plan_swaps_ineligible_place_to_same_category_eligible():
    """改修(iv) hard self-healing: LLM が opening_hours 不適合 place を選んでも
    assembler が同カテゴリの eligible 代替に自動差し替え（retry 不要、validator 通過）。
    """
    # day1_morning は月曜 09:00-11:30
    p_open = _place("P_open_mon", opening=[(0, "09:00", "20:00")], category=["restaurant"])
    p_closed = _place(
        "P_closed_mon", opening=[(1, "09:00", "20:00")], category=["restaurant"]
    )  # 火曜のみ → 月曜定休
    pack = _make_pack(places=[p_open, p_closed], edges=[])
    plan_v2 = LlmGeneratedPlanV2(
        slots=[
            LlmSlotAssignment(
                slot_id="day1_morning",
                place_id="P_closed_mon",
                rationale="LLM が誤って月曜定休 place を選んだケース",
            )
        ]
    )
    result = assemble_plan(plan_v2, pack)
    activity = result.items[0]
    assert activity.place_id == "P_open_mon"  # 自動差し替え


def test_assemble_plan_swaps_ineligible_to_any_eligible_when_no_same_category():
    """同カテゴリの eligible 代替が無ければ別カテゴリの eligible でもよい。"""
    p_other = _place("P_other_cat", opening=[(0, "09:00", "20:00")], category=["museum"])
    p_closed = _place(
        "P_closed_mon", opening=[(1, "09:00", "20:00")], category=["restaurant"]
    )
    pack = _make_pack(places=[p_other, p_closed], edges=[])
    plan_v2 = LlmGeneratedPlanV2(
        slots=[
            LlmSlotAssignment(
                slot_id="day1_morning",
                place_id="P_closed_mon",
                rationale="月曜定休、同カテゴリ代替なし",
            )
        ]
    )
    result = assemble_plan(plan_v2, pack)
    activity = result.items[0]
    assert activity.place_id == "P_other_cat"


def test_assemble_plan_accepts_when_no_eligible_alternate_at_all(caplog):
    """Phase 2 polish v5: pack 全 place が当該 slot に不適合 + 代替なしのとき、
    旧設計は raise IneligiblePlaceForSlotError。新設計は warn + accept で plan を組み上げ、
    validator が後段で OUTSIDE_OPENING_HOURS を catch して retry に流す。
    """
    import logging

    p_tue_only_a = _place("P1", opening=[(1, "09:00", "20:00")])  # 火曜のみ
    p_tue_only_b = _place("P2", opening=[(1, "09:00", "20:00")])
    pack = _make_pack(places=[p_tue_only_a, p_tue_only_b], edges=[])
    plan_v2 = LlmGeneratedPlanV2(
        slots=[
            LlmSlotAssignment(
                slot_id="day1_morning",
                place_id="P1",
                rationale="all closed Mon",
            )
        ]
    )
    with caplog.at_level(logging.WARNING, logger="src.llm.assembly"):
        result = assemble_plan(plan_v2, pack)
    # 元 P1 をそのまま採用、validator catch 委譲
    final_pids = [it.place_id for it in result.items if it.place_id is not None]
    assert "P1" in final_pids
    # warn log で「ineligible accepting (validator will catch and retry)」が出る
    assert any(
        "ineligible" in rec.getMessage() and "accepting" in rec.getMessage()
        for rec in caplog.records
    ), [rec.getMessage() for rec in caplog.records]


def test_assemble_plan_accepts_post_shift_start_outside_opening(caplog):
    """Phase 2 polish v5: transit shift で start_dt が place の opening close を超える
    ケース、旧設計は raise IneligiblePlaceForSlotError、新設計は warn + accept で plan
    を組み上げ、validator が後段で OUTSIDE_OPENING_HOURS を catch して retry に流す。
    """
    import logging

    # day1_morning は月曜 09:00-11:30
    p_prev = _place("P_prev", opening=[(0, "09:00", "22:00")], category=["restaurant"])
    # P_target: 月曜 11:00-12:30 のみ。post-shift で close 超え
    p_target = _place("P_target", opening=[(0, "11:00", "12:30")], category=["restaurant"])
    p_alt = _place("P_alt", opening=[(0, "11:00", "22:00")], category=["restaurant"])
    edges = [
        TransitEdge(
            from_place_id="P_prev",
            to_place_id="P_target",
            mode="train",
            route_summary="long",
            duration_min=90,
            fare_jpy=400,
            candidate_departures=["09:00"],
        ),
        TransitEdge(
            from_place_id="P_prev",
            to_place_id="P_alt",
            mode="train",
            route_summary="long",
            duration_min=90,
            fare_jpy=400,
            candidate_departures=["09:00"],
        ),
    ]
    pack = _make_pack(places=[p_prev, p_target, p_alt], edges=edges)
    plan_v2 = LlmGeneratedPlanV2(
        slots=[
            LlmSlotAssignment(slot_id="day1_morning", place_id="P_prev", rationale="post-shift test prev"),
            LlmSlotAssignment(slot_id="day1_lunch", place_id="P_target", rationale="post-shift breaks opening"),
        ]
    )
    with caplog.at_level(logging.WARNING, logger="src.llm.assembly"):
        result = assemble_plan(plan_v2, pack)
    # plan は組み上がる、warn log で post-shift accept を確認
    final_pids = [it.place_id for it in result.items if it.place_id is not None]
    assert "P_prev" in final_pids
    assert any(
        "post-shift" in rec.getMessage() and "accepting" in rec.getMessage()
        for rec in caplog.records
    ), [rec.getMessage() for rec in caplog.records]


def test_assemble_plan_rejects_ambiguous_case_insensitive_match():
    """Codex Major fix: pack 内に lower-case で衝突する id が複数ある場合、
    case-insensitive 救済は誤った canonical 化のリスクがある。曖昧一致は安全のため
    UnknownPlaceInSlotError で fail-fast させる（黙って先勝ちで上書きしない）。
    """
    p_a = _place("ChIJabc", name="A")
    p_b = _place("CHIJABC", name="B")  # lower すると ChIJabc と衝突
    pack = _make_pack(places=[p_a, p_b], edges=[])
    plan_v2 = LlmGeneratedPlanV2(
        slots=[
            LlmSlotAssignment(
                slot_id="day1_morning",
                place_id="chijabc",  # 大文字小文字無視で 2 件一致 → ambiguous
                rationale="ambiguous case match",
            )
        ]
    )
    with pytest.raises(UnknownPlaceInSlotError):
        assemble_plan(plan_v2, pack)


def test_assemble_plan_missing_transit_edge_skips_transit_item(caplog):
    """Phase 2 polish v5: transit edge 不在 + 代替候補なしのとき、旧設計は raise
    NoFeasibleTransitError。新設計は transit item を skip + place_id をそのまま採用。
    """
    import logging

    p_a = _place("P_A")
    p_b = _place("P_B")
    pack = _make_pack(places=[p_a, p_b], edges=[])
    plan_v2 = LlmGeneratedPlanV2(
        slots=[
            LlmSlotAssignment(slot_id="day1_morning", place_id="P_A", rationale="ok 12chars"),
            LlmSlotAssignment(slot_id="day1_lunch", place_id="P_B", rationale="needs transit 40 yen"),
        ]
    )
    with caplog.at_level(logging.WARNING, logger="src.llm.assembly"):
        result = assemble_plan(plan_v2, pack)
    final_pids = [it.place_id for it in result.items if it.place_id is not None]
    assert final_pids == ["P_A", "P_B"]
    # transit item は skip されているので含まれない
    transit_count = sum(1 for it in result.items if it.item_type == "transit")
    assert transit_count == 0
    assert any(
        "skipping transit item" in rec.getMessage()
        for rec in caplog.records
    ), [rec.getMessage() for rec in caplog.records]


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


def test_assemble_plan_alternate_selection_respects_category_match(caplog):
    """target と共通 category を 1 つも持たない候補は alternate に選ばれない。

    Phase 2 polish v5: 旧設計は raise NoFeasibleTransitError。
    新設計は alternate 不在のとき transit item skip + place_id をそのまま採用。
    """
    import logging

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
                rationale="category が合わない候補しかないので skip 想定",
            ),
        ]
    )
    with caplog.at_level(logging.WARNING, logger="src.llm.assembly"):
        result = assemble_plan(plan_v2, pack)
    # P_target そのまま採用、transit item は skip
    final_pids = [it.place_id for it in result.items if it.place_id is not None]
    assert final_pids == ["P_A", "P_target"]
    transit_count = sum(1 for it in result.items if it.item_type == "transit")
    assert transit_count == 0
    # category 不一致で alternate なし → transit skip log
    assert any(
        "skipping transit item" in rec.getMessage()
        for rec in caplog.records
    ), [rec.getMessage() for rec in caplog.records]


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


def test_assemble_plan_transit_departure_skips_when_all_candidates_before_start(caplog):
    """Phase 2 polish v5: 全 candidate_departures が start_dt より前のとき、
    旧設計は raise NoFeasibleTransitError。新設計は transit item を skip + place を採用。
    過去時刻 transit を出さない原則は維持しつつ、retry に委ねず graceful に続行。
    """
    import logging

    p_a = _place("P_A", category=["point_of_interest"])
    p_b = _place("P_B", category=["point_of_interest"])
    edge_ab = TransitEdge(
        from_place_id="P_A",
        to_place_id="P_B",
        mode="train",
        route_summary="fallback skip テスト",
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
    with caplog.at_level(logging.WARNING, logger="src.llm.assembly"):
        result = assemble_plan(plan_v2, pack)
    final_pids = [it.place_id for it in result.items if it.place_id is not None]
    assert final_pids == ["P_A", "P_B"]
    transit_count = sum(1 for it in result.items if it.item_type == "transit")
    assert transit_count == 0
    assert any(
        "departure infeasible" in rec.getMessage()
        for rec in caplog.records
    ), [rec.getMessage() for rec in caplog.records]


def test_assemble_plan_alternate_selection_avoids_self_loop():
    """LLM が連続 slot に同じ place を割当てた場合、代替選定で from_place_id 自身は避ける。

    Phase 2 polish v6: day1_lunch (meal slot) だと v6 の item_type pre-check が
    point_of_interest を meal 不適合として swap 試みて失敗する。day1_afternoon (activity slot)
    に変更して item_type 制約なし状態で自己ループ回避の動作を確認する (本 test の本来の意図)。
    """
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
                slot_id="day1_afternoon",
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


# ==============================
# Phase 2.1: anchor mode の必須 place 検証
# ==============================


def _make_pack_anchor(
    places: list[PlacePoint],
    anchor_ids: list[str],
    edges: list[TransitEdge] | None = None,
    total_days: int = 2,
) -> EvidencePack:
    """anchor モード用の pack ヘルパ（query_context.start_mode='anchor'）。"""
    base = _make_pack(places=places, edges=edges or [], total_days=total_days)
    return base.model_copy(
        update={
            "query_context": base.query_context.model_copy(
                update={"start_mode": "anchor", "mode_payload": {"anchor_place_ids": anchor_ids}}
            )
        }
    )


def _full_edges_between(*place_ids: str) -> list[TransitEdge]:
    """与えられた place_ids 間で全方向 edge を生成（transit 不在で test が落ちるのを回避）。"""
    edges = []
    for a in place_ids:
        for b in place_ids:
            if a != b:
                edges.append(_edge(a, b))
    return edges


def test_assemble_plan_anchor_present_no_error():
    """anchor モードで指定 place_id が slot に含まれていれば成功。"""
    p_anchor = _place("ANCHOR1")
    p_other = _place("OTHER")
    pack = _make_pack_anchor(
        places=[p_anchor, p_other],
        anchor_ids=["ANCHOR1"],
        edges=_full_edges_between("ANCHOR1", "OTHER"),
    )
    plan_v2 = LlmGeneratedPlanV2(
        slots=[
            LlmSlotAssignment(slot_id="day1_morning", place_id="ANCHOR1", rationale="アンカーで指定されたスポット"),
            LlmSlotAssignment(slot_id="day1_lunch", place_id="OTHER", rationale="昼食タイムで定番店を選定"),
        ]
    )
    result = assemble_plan(plan_v2, pack)
    item_pids = [it.place_id for it in result.items if it.place_id is not None]
    assert "ANCHOR1" in item_pids


def test_assemble_plan_anchor_missing_raises():
    """anchor モードで指定 place_id が slot に含まれない → AnchorMissingError。

    1 slot 構成で transit / swap 経路を排除し、純粋に「anchor が plan に居ない」
    case を作る。
    """
    p_anchor = _place("ANCHOR1")
    p_other = _place("OTHER")
    pack = _make_pack_anchor(
        places=[p_anchor, p_other],
        anchor_ids=["ANCHOR1"],
        edges=[],  # transit 不要（1 slot のみ）
    )
    plan_v2 = LlmGeneratedPlanV2(
        slots=[
            LlmSlotAssignment(slot_id="day1_morning", place_id="OTHER", rationale="アンカー以外の通常スポット"),
        ]
    )
    with pytest.raises(AnchorMissingError) as exc:
        assemble_plan(plan_v2, pack)
    assert "ANCHOR1" in str(exc.value)


def test_assemble_plan_multiple_anchors_partial_missing_raises():
    """anchor 2 件中 1 件のみ含まれる → 不足分を AnchorMissingError で報告。"""
    p_a1 = _place("A1")
    p_a2 = _place("A2")
    pack = _make_pack_anchor(
        places=[p_a1, p_a2],
        anchor_ids=["A1", "A2"],
        edges=[],  # 1 slot のみで transit 不要
    )
    plan_v2 = LlmGeneratedPlanV2(
        slots=[
            LlmSlotAssignment(slot_id="day1_morning", place_id="A1", rationale="アンカー1番目のスポット"),
        ]
    )
    with pytest.raises(AnchorMissingError) as exc:
        assemble_plan(plan_v2, pack)
    assert "A2" in str(exc.value)
    assert "A1" not in str(exc.value)  # A1 は含まれてるので報告対象外


def test_assemble_plan_auto_mode_no_anchor_check():
    """auto モードでは anchor チェックなし（既存 happy path と同じ挙動）。"""
    p = _place("P_A")
    pack = _make_pack(places=[p], edges=[])
    plan_v2 = LlmGeneratedPlanV2(
        slots=[LlmSlotAssignment(slot_id="day1_morning", place_id="P_A", rationale="通常選定の rationale")]
    )
    result = assemble_plan(plan_v2, pack)
    assert len(result.items) == 1


def test_assemble_plan_anchor_swapped_by_self_healing_raises():
    """LLM が anchor を pick しても assembler の self-healing で swap され消えたら
    post-check で AnchorMissingError raise（Codex 再レビュー Major 2 対応で実 swap 経路）。

    シナリオ（fixture: 2026-06-01 = 月曜 day_of_week=0 を day1 とする 1 day pack）:
    - ANCHOR1: 水曜のみ営業 (day_of_week=2) → day1 (月曜) slot で ineligible
    - SUB1: 全曜日営業、ANCHOR1 と同 category（"museum"）→ self-healing の swap 候補
    - LLM が day1_morning (=月曜) に ANCHOR1 を割当
    - assembler の `_find_eligible_alternate_for_slot` で SUB1 に swap される
    - 最終 items に ANCHOR1 が居ない → anchor post-check で raise
    """
    p_anchor1 = _place(
        "ANCHOR1",
        opening=[(2, "09:00", "21:00")],  # 水曜のみ
        category=["museum"],
    )
    p_sub1 = _place(
        "SUB1",
        opening=[(d, "09:00", "21:00") for d in range(7)],  # 全曜日
        category=["museum"],  # ANCHOR1 と同 category（swap 候補に上がる）
    )
    pack = _make_pack_anchor(
        places=[p_anchor1, p_sub1],
        anchor_ids=["ANCHOR1"],
        edges=[],
        total_days=1,  # day1 のみ（=月曜のみ）
    )
    plan_v2 = LlmGeneratedPlanV2(
        slots=[
            LlmSlotAssignment(slot_id="day1_morning", place_id="ANCHOR1", rationale="アンカー指定で午前に訪問する"),
        ]
    )
    with pytest.raises(AnchorMissingError) as exc:
        assemble_plan(plan_v2, pack)
    assert "ANCHOR1" in str(exc.value)
    # AnchorMissingError が raise されたということは、ineligible 検出 → swap で
    # ANCHOR1 が SUB1 に置き換わって items から消えたことの間接的証拠。
    # （swap が起きなかったら IneligiblePlaceForSlotError が先に raise される。
    #  どちらでもなく成功で抜けた場合は ANCHOR1 が items に残るので AnchorMissingError も出ない。）


def test_assemble_plan_anchor_with_invalid_payload_no_check():
    """anchor モードだが mode_payload が壊れてる場合は anchor チェックを skip（fail-open）。"""
    p = _place("P_A")
    pack = _make_pack(places=[p], edges=[])
    pack = pack.model_copy(
        update={
            "query_context": pack.query_context.model_copy(
                update={"start_mode": "anchor", "mode_payload": {"unrelated": True}}
            )
        }
    )
    plan_v2 = LlmGeneratedPlanV2(
        slots=[LlmSlotAssignment(slot_id="day1_morning", place_id="P_A", rationale="通常選定の rationale")]
    )
    # raise しない（payload 不整合は assembler の責任外）
    result = assemble_plan(plan_v2, pack)
    assert len(result.items) == 1


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


def test_assemble_plan_rakuten_lodging_uses_verified_actual_price():
    """Phase 3 polish 案 D 第 6 段 (2026-04-28): 楽天 lodging (place_id が `rakuten_`
    prefix) は pack.lodging_options から実価格を引いて cost_confidence="verified"
    にする。`_PRICE_MAP` の estimated 値で上書きしない。
    """
    rakuten_place = PlacePoint(
        place_id="rakuten_55555",
        name="楽天実価格テスト旅館",
        category=["lodging", "hotel", "ryokan"],
        lat=35.2,
        lng=139.0,
        address="箱根",
        opening_hours=[],
        opening_hours_unknown_days=[0, 1, 2, 3, 4, 5, 6],
        price_level=2,  # _PRICE_MAP では (14000, "estimated") に対応
        rating=4.3,
        user_ratings_total=None,
        relevance_tags=[],
    )
    pack = _make_pack(places=[rakuten_place], edges=[])
    # pack.lodging_options に楽天実価格をセット
    pack = pack.model_copy(
        update={
            "lodging_options": [
                LodgingOption(
                    place_id="rakuten_55555",
                    name="楽天実価格テスト旅館",
                    price_jpy_per_night=18500,  # 実価格 (price_level=2 の 14000 と異なる値)
                    lat=35.2,
                    lng=139.0,
                    rating=4.3,
                ),
            ],
        }
    )
    plan_v2 = LlmGeneratedPlanV2(
        slots=[
            LlmSlotAssignment(
                slot_id="day1_lodging",
                place_id="rakuten_55555",
                rationale="楽天 verified 価格",
            ),
        ]
    )
    result = assemble_plan(plan_v2, pack)
    assert len(result.items) == 1
    lodging = result.items[0]
    # _PRICE_MAP の (14000, "estimated") ではなく LodgingOption の実価格 + verified
    assert lodging.cost_jpy == 18500
    assert lodging.cost_confidence == "verified"


def test_assemble_plan_google_lodging_keeps_price_map_estimated():
    """Google Places (`ChIJ` prefix) の lodging は従来通り `_PRICE_MAP` 経由の estimated。

    第 6 段 fix が `rakuten_` prefix のみを対象にしている回帰確認。
    """
    google_lodging = _place("ChIJABC123", price_level=2, category=["lodging", "hotel"])
    pack = _make_pack(places=[google_lodging], edges=[])
    plan_v2 = LlmGeneratedPlanV2(
        slots=[
            LlmSlotAssignment(
                slot_id="day1_lodging",
                place_id="ChIJABC123",
                rationale="Google lodging",
            ),
        ]
    )
    result = assemble_plan(plan_v2, pack)
    assert len(result.items) == 1
    lodging = result.items[0]
    # 従来通り _PRICE_MAP の price_level=2 lodging = (14000, "estimated")
    assert lodging.cost_jpy == 14000
    assert lodging.cost_confidence == "estimated"


def test_assemble_plan_rakuten_lodging_falls_back_when_lodging_options_empty():
    """楽天 place が pack.places にあるが pack.lodging_options が None / 空 (race
    condition、deserialize 抜け落ち等の防御)。`_PRICE_MAP` 経由 fallback で動作継続。
    """
    rakuten_place = PlacePoint(
        place_id="rakuten_99999",
        name="orphan rakuten",
        category=["lodging", "hotel"],
        lat=35.2,
        lng=139.0,
        address="箱根",
        opening_hours=[],
        opening_hours_unknown_days=[0, 1, 2, 3, 4, 5, 6],
        price_level=3,  # _PRICE_MAP[lodging][3] = (22000, "estimated")
        rating=None,
        user_ratings_total=None,
        relevance_tags=[],
    )
    pack = _make_pack(places=[rakuten_place], edges=[])
    # pack.lodging_options を None のまま (default)
    plan_v2 = LlmGeneratedPlanV2(
        slots=[
            LlmSlotAssignment(
                slot_id="day1_lodging",
                place_id="rakuten_99999",
                rationale="楽天 orphan fallback",
            ),
        ]
    )
    result = assemble_plan(plan_v2, pack)
    assert len(result.items) == 1
    lodging = result.items[0]
    # fallback で _PRICE_MAP[lodging][3] = (22000, "estimated")
    assert lodging.cost_jpy == 22000
    assert lodging.cost_confidence == "estimated"


# ==============================
# 重複防止 (Phase 2 polish 2026-04-27、A 課題)
# ==============================


def test_assemble_plan_swaps_duplicate_place_in_non_adjacent_slot():
    """非隣接 slot で重複 pick → duplicate detection で swap される。

    DAY1 / DAY2 lunch 重複のような実際のシナリオをシミュレート。
    transit lookup は edge 存在で成功するパスなので、duplicate detection が
    無いと既存コードはそのまま重複 place を plan に入れてしまう。
    """
    p1 = _place("P1", category=["museum"])
    p_mid = _place("P_mid", category=["museum"])  # slot 2 で使われ used になる
    p_alt = _place("P_alt", category=["museum"])  # swap target
    edges = [
        _edge("P1", "P_mid"),     # slot1 → slot2
        _edge("P_mid", "P1"),     # slot2 → slot3 (P1 重複だが edge ある)
        _edge("P_mid", "P_alt"),  # swap target reachable from prev
    ]
    pack = _make_pack(places=[p1, p_mid, p_alt], edges=edges, total_days=1)
    plan_v2 = LlmGeneratedPlanV2(
        slots=[
            LlmSlotAssignment(slot_id="day1_morning", place_id="P1", rationale="重複 1 つ目の rationale"),
            LlmSlotAssignment(slot_id="day1_lunch", place_id="P_mid", rationale="間に挟まる別 place"),
            LlmSlotAssignment(slot_id="day1_afternoon", place_id="P1", rationale="重複 2 つ目 → swap"),
        ]
    )
    result = assemble_plan(plan_v2, pack)
    place_id_items = [it for it in result.items if it.place_id is not None]
    assert len(place_id_items) == 3
    assert place_id_items[0].place_id == "P1"
    assert place_id_items[1].place_id == "P_mid"
    assert place_id_items[2].place_id == "P_alt"  # P1 重複検出 → swap


def test_assemble_plan_transit_alternate_excludes_already_used_places():
    """3 slot シナリオで `_find_alternate_place` が exclude_place_ids を honor する。

    transit edge 不在で代替を探す時、別 slot で既に使われた place は再選しない
    （rating が最高でも除外）。
    """
    p_used = _place("P_used", category=["museum"])
    p_used = p_used.model_copy(update={"rating": 4.9})  # 一番 rating 高い、used により除外
    p_prev = _place("P_prev", category=["museum"])
    p_target = _place("P_target", category=["museum"])
    p_alt = _place("P_alt", category=["museum"])
    p_alt = p_alt.model_copy(update={"rating": 4.0})  # 普通 rating、exclude 後に選ばれる

    edges = [
        # slot1 → slot2: P_used → P_prev (transit OK)
        _edge("P_used", "P_prev"),
        # slot2 から到達可能候補:
        _edge("P_prev", "P_used"),  # rating 高いが used で除外されるべき
        _edge("P_prev", "P_alt"),   # rating 普通、exclude 後に選ばれる
        # P_prev → P_target に edge 無し → _find_alternate_place 起動
    ]
    pack = _make_pack(places=[p_used, p_prev, p_target, p_alt], edges=edges, total_days=1)

    plan_v2 = LlmGeneratedPlanV2(
        slots=[
            LlmSlotAssignment(slot_id="day1_morning", place_id="P_used", rationale="slot1 起点 used 化"),
            LlmSlotAssignment(slot_id="day1_lunch", place_id="P_prev", rationale="slot2 中継 prev 化"),
            LlmSlotAssignment(slot_id="day1_afternoon", place_id="P_target", rationale="slot3 edge 不在で swap"),
        ]
    )
    result = assemble_plan(plan_v2, pack)

    place_ids = [it.place_id for it in result.items if it.place_id is not None]
    # P_used は rating 最高だが used により除外、P_alt が選ばれる
    assert place_ids == ["P_used", "P_prev", "P_alt"]


def test_drop_duplicate_place_items_drops_dangling_transit():
    """Codex review 2 Major 1: 最終 invariant で non-transit を drop したとき、
    その place を指す transit_ref も dangling として drop されることを確認。

    proactive swap path がカバーする想定だが、defense-in-depth path のテスト。
    """
    from src.llm.assembly import _drop_duplicate_place_items

    # 手作りの items (assembler が生成しない malformed なケースをシミュレート)
    items = [
        LlmPlanItem(
            order_index=0,
            item_type="activity",
            title="A",
            description="r",
            start_time="2026-06-01T09:00:00+09:00",
            end_time="2026-06-01T11:30:00+09:00",
            place_id="A",
            cost_jpy=1000,
            cost_confidence="estimated",
            transit_ref=None,
        ),
        LlmPlanItem(
            order_index=1,
            item_type="transit",
            title="A→B",
            description="t",
            start_time="2026-06-01T11:30:00+09:00",
            end_time="2026-06-01T11:50:00+09:00",
            place_id=None,
            cost_jpy=400,
            cost_confidence="verified",
            transit_ref=LlmTransitRef(from_place_id="A", to_place_id="B", departure_time="11:30"),
        ),
        # 重複: A が再登場（malformed input、proactive swap が漏らした想定）
        LlmPlanItem(
            order_index=2,
            item_type="activity",
            title="A_dup",
            description="r",
            start_time="2026-06-01T12:00:00+09:00",
            end_time="2026-06-01T13:30:00+09:00",
            place_id="A",
            cost_jpy=1000,
            cost_confidence="estimated",
            transit_ref=None,
        ),
        LlmPlanItem(
            order_index=3,
            item_type="transit",
            title="A→C",
            description="t",
            start_time="2026-06-01T13:30:00+09:00",
            end_time="2026-06-01T13:50:00+09:00",
            place_id=None,
            cost_jpy=400,
            cost_confidence="verified",
            transit_ref=LlmTransitRef(from_place_id="A", to_place_id="C", departure_time="13:30"),
        ),
        LlmPlanItem(
            order_index=4,
            item_type="activity",
            title="C",
            description="r",
            start_time="2026-06-01T14:00:00+09:00",
            end_time="2026-06-01T16:30:00+09:00",
            place_id="C",
            cost_jpy=1000,
            cost_confidence="estimated",
            transit_ref=None,
        ),
    ]
    deduped = _drop_duplicate_place_items(items)
    non_transit_pids = [it.place_id for it in deduped if it.place_id is not None]
    assert non_transit_pids == ["A", "C"]  # A_dup drop、A→B transit dangling drop、A→C 残存
    # 残った transit は from/to ともに surviving_pids 内にある
    for it in deduped:
        if it.transit_ref is not None:
            assert it.transit_ref.from_place_id in {"A", "C"}
            assert it.transit_ref.to_place_id in {"A", "C"}
    # T(A→B) は to=B が surviving に居ないので dropped、T(A→C) は両端生存で残る
    transit_pairs = [
        (it.transit_ref.from_place_id, it.transit_ref.to_place_id)
        for it in deduped
        if it.transit_ref is not None
    ]
    assert ("A", "B") not in transit_pairs
    assert ("A", "C") in transit_pairs


def test_drop_duplicate_place_items_drops_transit_with_dangling_from():
    """Codex review 3 Minor 2: transit_ref.from が drop された place を指すケースも drop。

    test_drop_duplicate_place_items_drops_dangling_transit は to 欠落中心のため、
    対称な from 欠落カバレッジを明示する。
    """
    from src.llm.assembly import _drop_duplicate_place_items

    # B が duplicate で drop され、T(B→C) は from=B が surviving に居ない → drop
    items = [
        LlmPlanItem(
            order_index=0, item_type="activity", title="B", description="r",
            start_time="2026-06-01T09:00:00+09:00", end_time="2026-06-01T11:30:00+09:00",
            place_id="B", cost_jpy=1000, cost_confidence="estimated", transit_ref=None,
        ),
        LlmPlanItem(
            order_index=1, item_type="transit", title="B→C", description="t",
            start_time="2026-06-01T11:30:00+09:00", end_time="2026-06-01T11:50:00+09:00",
            place_id=None, cost_jpy=400, cost_confidence="verified",
            transit_ref=LlmTransitRef(from_place_id="B", to_place_id="C", departure_time="11:30"),
        ),
        LlmPlanItem(
            order_index=2, item_type="activity", title="C", description="r",
            start_time="2026-06-01T12:00:00+09:00", end_time="2026-06-01T13:30:00+09:00",
            place_id="C", cost_jpy=1000, cost_confidence="estimated", transit_ref=None,
        ),
        # B duplicate (malformed input、proactive swap が漏らした想定)
        LlmPlanItem(
            order_index=3, item_type="activity", title="B_dup", description="r",
            start_time="2026-06-01T14:00:00+09:00", end_time="2026-06-01T15:00:00+09:00",
            place_id="B", cost_jpy=1000, cost_confidence="estimated", transit_ref=None,
        ),
    ]
    deduped = _drop_duplicate_place_items(items)
    non_transit_pids = [it.place_id for it in deduped if it.place_id is not None]
    # 仕様上 1 番目の B が surviving、4 番目の B_dup は drop
    assert non_transit_pids == ["B", "C"]
    # T(B→C) は from=B が surviving に存在するので残るはず
    transit_pairs = [
        (it.transit_ref.from_place_id, it.transit_ref.to_place_id)
        for it in deduped
        if it.transit_ref is not None
    ]
    assert ("B", "C") in transit_pairs

    # 対照として: B が最初に出現 + drop が後発 → 同じ test だが、B が逆順だったら？
    # _drop_duplicate_place_items は最初の出現を残すので、to=B 欠落 + from=B 欠落
    # の両方を 1 つの items 配列で同時実証するために以下のケースを追加検証:
    items2 = [
        # X が surviving、Y も surviving、T(Y→X) は両端 OK で残る
        LlmPlanItem(
            order_index=0, item_type="activity", title="X", description="r",
            start_time="2026-06-01T09:00:00+09:00", end_time="2026-06-01T11:30:00+09:00",
            place_id="X", cost_jpy=1000, cost_confidence="estimated", transit_ref=None,
        ),
        # T(X→Y) は X 残 + Y 残 で OK
        LlmPlanItem(
            order_index=1, item_type="transit", title="X→Y", description="t",
            start_time="2026-06-01T11:30:00+09:00", end_time="2026-06-01T11:50:00+09:00",
            place_id=None, cost_jpy=400, cost_confidence="verified",
            transit_ref=LlmTransitRef(from_place_id="X", to_place_id="Y", departure_time="11:30"),
        ),
        # Y_dup として X を再登場させて drop（X が duplicate）
        LlmPlanItem(
            order_index=2, item_type="activity", title="X_dup", description="r",
            start_time="2026-06-01T12:00:00+09:00", end_time="2026-06-01T13:30:00+09:00",
            place_id="X", cost_jpy=1000, cost_confidence="estimated", transit_ref=None,
        ),
        # T(X→Z) は X 残 + Z 残 (続く) で OK のはずだが、ここで Z を non_transit として続ける
        LlmPlanItem(
            order_index=3, item_type="transit", title="X→Z", description="t",
            start_time="2026-06-01T13:30:00+09:00", end_time="2026-06-01T13:50:00+09:00",
            place_id=None, cost_jpy=400, cost_confidence="verified",
            transit_ref=LlmTransitRef(from_place_id="X", to_place_id="Z", departure_time="13:30"),
        ),
        LlmPlanItem(
            order_index=4, item_type="activity", title="Z", description="r",
            start_time="2026-06-01T14:00:00+09:00", end_time="2026-06-01T15:30:00+09:00",
            place_id="Z", cost_jpy=1000, cost_confidence="estimated", transit_ref=None,
        ),
    ]
    # ここでは Y は items2 に含まれず、T(X→Y) は to=Y が surviving に居ないので drop
    deduped2 = _drop_duplicate_place_items(items2)
    transit_pairs2 = [
        (it.transit_ref.from_place_id, it.transit_ref.to_place_id)
        for it in deduped2
        if it.transit_ref is not None
    ]
    assert ("X", "Y") not in transit_pairs2  # Y 不在で drop
    assert ("X", "Z") in transit_pairs2  # 両端生存で残存


def test_assemble_plan_triple_duplicate_resolved_to_unique_invariant():
    """3 slot で同じ place を 3 回 pick → 全て unique な place に展開される（最終 invariant）。

    Phase 2 polish v6: category=["museum"] だと day1_lunch (meal slot) で v6 の
    item_type pre-check が swap 試みて失敗する。3 slot 全部 activity slot に変更して
    pre-check が無関係な状態で重複検出 swap の動作を確認する (本 test の本来の意図)。
    """
    p1 = _place("P1", category=["museum"])
    p2 = _place("P2", category=["museum"])
    p3 = _place("P3", category=["museum"])
    edges = [
        _edge("P1", "P2"), _edge("P1", "P3"),
        _edge("P2", "P1"), _edge("P2", "P3"),
        _edge("P3", "P1"), _edge("P3", "P2"),
    ]
    # total_days=2 にすれば day1_morning, day1_afternoon, day2_morning が全て activity slot
    pack = _make_pack(places=[p1, p2, p3], edges=edges, total_days=2)
    plan_v2 = LlmGeneratedPlanV2(
        slots=[
            LlmSlotAssignment(slot_id="day1_morning", place_id="P1", rationale="重複 1 つ目 rationale"),
            LlmSlotAssignment(slot_id="day1_afternoon", place_id="P1", rationale="重複 2 つ目 → swap"),
            LlmSlotAssignment(slot_id="day2_morning", place_id="P1", rationale="重複 3 つ目 → swap"),
        ]
    )
    result = assemble_plan(plan_v2, pack)

    final_place_ids = [it.place_id for it in result.items if it.place_id is not None]
    assert len(final_place_ids) == 3
    assert len(set(final_place_ids)) == 3  # 全 unique（最終 invariant）
    assert final_place_ids[0] == "P1"  # 1 つ目は LLM pick がそのまま通る


# ==============================
# Phase 2 polish v3 T7: tier3 item_type filter
# ==============================


def test_is_item_type_compatible_meal_accepts_validator_helpers():
    """validator の `_categories_indicate_meal` と挙動一致を確認 (Codex review 2 Major)。"""
    from src.llm.assembly import _is_item_type_compatible

    # validator allowlist + `*_restaurant` 接尾辞
    assert _is_item_type_compatible("meal", ["restaurant"]) is True
    assert _is_item_type_compatible("meal", ["bakery"]) is True
    assert _is_item_type_compatible("meal", ["bar"]) is True
    assert _is_item_type_compatible("meal", ["meal_takeaway"]) is True
    assert _is_item_type_compatible("meal", ["yakiniku_restaurant"]) is True
    # museum / zoo は meal slot に不適合 (validator で reject される類)
    assert _is_item_type_compatible("meal", ["museum"]) is False
    assert _is_item_type_compatible("meal", ["zoo"]) is False


def test_is_item_type_compatible_lodging_accepts_validator_helpers():
    from src.llm.assembly import _is_item_type_compatible

    assert _is_item_type_compatible("lodging", ["lodging"]) is True
    assert _is_item_type_compatible("lodging", ["hotel"]) is True
    assert _is_item_type_compatible("lodging", ["ryokan"]) is True
    assert _is_item_type_compatible("lodging", ["hostel"]) is True
    assert _is_item_type_compatible("lodging", ["guest_house"]) is True
    assert _is_item_type_compatible("lodging", ["restaurant"]) is False
    assert _is_item_type_compatible("lodging", ["museum"]) is False


def test_is_item_type_compatible_activity_unconstrained():
    """activity slot は category 制約なし (validator も activity はチェックしない)。"""
    from src.llm.assembly import _is_item_type_compatible

    assert _is_item_type_compatible("activity", ["museum"]) is True
    assert _is_item_type_compatible("activity", ["zoo"]) is True
    assert _is_item_type_compatible("activity", ["restaurant"]) is True


def test_is_item_type_compatible_empty_category_returns_true():
    """Codex review 4 Major: validator 本体は空 category を skip するので一致。"""
    from src.llm.assembly import _is_item_type_compatible

    assert _is_item_type_compatible("meal", []) is True
    assert _is_item_type_compatible("lodging", []) is True
    assert _is_item_type_compatible("activity", []) is True


def test_find_eligible_alternate_tier3_skips_item_type_mismatch():
    """meal slot で tier1/tier2 不在時に tier3 が museum を弾く (T7)。"""
    from src.llm.assembly import _find_eligible_alternate_for_slot

    # target: meal slot 想定 (target_place の category は meal)
    target = _place("TARGET", category=["restaurant"])
    # candidates: tier1/tier2 不在を仕掛けるため category 重複なし
    bakery = _place("BAKERY", category=["bakery"])  # validator では meal allowed
    museum = _place("MUSEUM", category=["museum"])  # tier3 で弾かれる
    # transit edge は全 candidates に置いて reachable にする (prev_place_id=None でも OK)
    pack = _make_pack(places=[target, bakery, museum], edges=[], total_days=1)

    slot_meta = {
        "slot_id": "day1_lunch",
        "start_hhmm": "12:00",
        "end_hhmm": "14:00",
        "item_type": "meal",
    }
    result = _find_eligible_alternate_for_slot(
        pack=pack,
        target_place=target,
        slot_meta=slot_meta,
        slot_date=date(2026, 6, 1),
        prev_place_id=None,
        exclude_place_ids=set(),
    )
    # bakery が選ばれる (museum は item_type filter で弾かれる)
    assert result is not None
    assert result.place_id == "BAKERY"


def test_find_eligible_alternate_tier3_lodging_blocks_restaurant():
    """lodging slot で tier3 が restaurant を弾き、ryokan を選ぶ。"""
    from src.llm.assembly import _find_eligible_alternate_for_slot

    target = _place("TARGET", category=["lodging"])  # 異 category にして tier1/2 を不発に
    ryokan = _place("RYOKAN", category=["ryokan"])
    restaurant = _place("RESTAURANT", category=["restaurant"])
    pack = _make_pack(places=[target, ryokan, restaurant], edges=[], total_days=1)

    slot_meta = {
        "slot_id": "day1_lodging",
        "start_hhmm": "20:00",
        "end_hhmm": "23:00",
        "item_type": "lodging",
    }
    result = _find_eligible_alternate_for_slot(
        pack=pack,
        target_place=target,
        slot_meta=slot_meta,
        slot_date=date(2026, 6, 1),
        prev_place_id=None,
        exclude_place_ids=set(),
    )
    # ryokan のみ通る (restaurant は item_type filter で弾かれる)
    # ただし target も "lodging" category なので tier1/tier2 で ryokan が hit する経路もある
    # → どちらにせよ restaurant は選ばれない
    assert result is not None
    assert result.place_id == "RYOKAN"


def test_find_eligible_alternate_tier3_emits_warning_when_filtered_out(caplog):
    """Codex review 5 Minor 1: meal slot に museum しか無い場合は tier3 filter で None +
    tier3 専用 warning log を出す (`_find_eligible_alternate_for_slot tier3 filtered out`)。
    """
    import logging

    from src.llm.assembly import _find_eligible_alternate_for_slot

    target = _place("TARGET", category=["restaurant"])
    only_museum = _place("MUSEUM", category=["museum"])
    pack = _make_pack(places=[target, only_museum], edges=[], total_days=1)

    slot_meta = {
        "slot_id": "day1_lunch",
        "start_hhmm": "12:00",
        "end_hhmm": "14:00",
        "item_type": "meal",
    }
    with caplog.at_level(logging.WARNING, logger="src.llm.assembly"):
        result = _find_eligible_alternate_for_slot(
            pack=pack,
            target_place=target,
            slot_meta=slot_meta,
            slot_date=date(2026, 6, 1),
            prev_place_id=None,
            exclude_place_ids=set(),
        )
    assert result is None
    # tier3 で museum が弾かれた結果 None を返す経路 = 「tier3 filtered out」log
    assert any(
        "tier3 filtered out" in rec.getMessage() for rec in caplog.records
    ), [rec.getMessage() for rec in caplog.records]


# ==============================
# Phase 2 polish v4: _resolve_fuzzy_place_id (本番 Run 13d 短縮ハルシ救済)
# ==============================


def test_resolve_fuzzy_place_id_catches_prefix_duplication():
    """Run 13d で観測された「先頭 J 1 文字余分」ハルシを救済できる。

    LLM 出力: ChIJJE69IgAHnHWARDJVsAgxtjCQ (28 chars)
    Pack 正解: ChIJE69IgAHnHWARDJVsAgxtjCQ (27 chars)
    """
    from src.llm.assembly import _resolve_fuzzy_place_id

    pack_id = "ChIJE69IgAHnHWARDJVsAgxtjCQ"
    places_by_id = {
        pack_id: object(),  # value は使われない
        "ChIJUnrelatedDifferentPlaceXYZ123": object(),
    }
    llm_id = "ChIJJE69IgAHnHWARDJVsAgxtjCQ"  # 頭の J 余分
    assert _resolve_fuzzy_place_id(llm_id, places_by_id) == pack_id


def test_resolve_fuzzy_place_id_returns_none_when_unique_match_absent():
    """全く似ていない ID では None を返す (false positive 防止)。"""
    from src.llm.assembly import _resolve_fuzzy_place_id

    places_by_id = {"ChIJabc123def456ghi789jkl012": object()}
    assert _resolve_fuzzy_place_id("CompletelyDifferent_XYZ", places_by_id) is None


def test_resolve_fuzzy_place_id_returns_none_when_ambiguous():
    """複数の pack ID に同程度マッチするときは救済せず None (誤 canonical 化防止)。"""
    from src.llm.assembly import _resolve_fuzzy_place_id

    places_by_id = {
        "ChIJN1t_tDeuEmsRUsoyG83frY4": object(),
        "ChIJN2t_tDeuEmsRUsoyG83frY4": object(),  # 1 文字違い
    }
    # LLM 出力が両方に等距離 → ambiguous → None
    llm_id = "ChIJN3t_tDeuEmsRUsoyG83frY4"
    assert _resolve_fuzzy_place_id(llm_id, places_by_id) is None


def test_resolve_fuzzy_place_id_rejects_large_length_diff():
    """長さ差が FUZZY_MAX_LEN_DIFF=2 を超えるなら ratio 高くても救済しない。"""
    from src.llm.assembly import _resolve_fuzzy_place_id

    pack_id = "ChIJabc"  # 7 chars
    places_by_id = {pack_id: object()}
    llm_id = "ChIJabcdefghij"  # 14 chars (差 7)
    assert _resolve_fuzzy_place_id(llm_id, places_by_id) is None


def test_resolve_fuzzy_place_id_catches_j_to_h_typo():
    """Phase 2 polish v5 (Codex review 1 Minor 1 reverse): 旧 `ChIJ` prefix guard
    を削除したことで、本番 Run 13e で観測された `ChIJ` → `ChIH` typo を救済できる。
    """
    from src.llm.assembly import _resolve_fuzzy_place_id

    pack_id = "ChIJhY2RO4XnHWAReFs51v9XU3A"  # 27 chars
    places_by_id = {pack_id: object()}
    # LLM が J を H に typo
    llm_id = "ChIHhY2RO4XnHWAReFs51v9XU3A"
    assert _resolve_fuzzy_place_id(llm_id, places_by_id) == pack_id


def test_resolve_fuzzy_place_id_catches_j_to_lowercase_typo():
    """Run 13e attempt 3 で観測された `ChIJ` → `ChIh` (J を h に lowercase) も救済。"""
    from src.llm.assembly import _resolve_fuzzy_place_id

    pack_id = "ChIJhY2RO4XnHWAReFs51v9XU3A"  # 27 chars
    places_by_id = {pack_id: object()}
    # LLM が J を h に lowercase + 残りはそのまま (28 → 27 文字)
    llm_id = "ChIhY2RO4XnHWAReFs51v9XU3A"
    assert _resolve_fuzzy_place_id(llm_id, places_by_id) == pack_id


def test_assemble_plan_resolves_fuzzy_match_in_assembly(caplog):
    """assembly が unknown place_id 出力を fuzzy match で救済して plan 生成成功する。"""
    import logging

    p1 = _place("ChIJOriginalAttraction001", category=["tourist_attraction"])
    p2 = _place("ChIJOriginalRestaurant002", category=["restaurant"])
    edges = [_edge("ChIJOriginalAttraction001", "ChIJOriginalRestaurant002"),
             _edge("ChIJOriginalRestaurant002", "ChIJOriginalAttraction001")]
    pack = _make_pack(places=[p1, p2], edges=edges, total_days=1)
    # LLM が頭に余分な J を付けたケース (Run 13d パターン)
    plan_v2 = LlmGeneratedPlanV2(
        slots=[
            LlmSlotAssignment(
                slot_id="day1_morning",
                place_id="ChIJJOriginalAttraction001",  # 頭に J 余分
                rationale="朝の観光地でゆっくり過ごす",
            ),
            LlmSlotAssignment(
                slot_id="day1_lunch",
                place_id="ChIJOriginalRestaurant002",  # 正解
                rationale="人気のレストランでランチ",
            ),
        ]
    )
    with caplog.at_level(logging.WARNING, logger="src.llm.assembly"):
        result = assemble_plan(plan_v2, pack)
    # 救済されてエラーなく組み上がる
    final_pids = [it.place_id for it in result.items if it.place_id is not None]
    assert "ChIJOriginalAttraction001" in final_pids
    # warning log で fuzzy match 動作確認
    assert any(
        "fuzzy-matched place_id" in rec.getMessage() for rec in caplog.records
    ), [rec.getMessage() for rec in caplog.records]


# ==============================
# Phase 2 polish v5: lodging 連泊許容 / meal/activity soft duplicate / 連続同 place skip
# ==============================


def test_assemble_plan_allows_lodging_repeat_for_consecutive_nights(caplog):
    """Phase 2 polish v5 (Codex review 1 Major 1 反映): lodging slot は同 place_id の
    連泊を許容する。total_days=3 で day1_lodging + day2_lodging に同じ宿を割当てて、
    swap log が出ない + 両方が plan に採用されることを確認する。
    """
    import logging

    p_attr1 = _place("P_attr1", category=["tourist_attraction"])
    p_attr2 = _place("P_attr2", category=["tourist_attraction"])
    p_attr3 = _place("P_attr3", category=["tourist_attraction"])
    p_meal1 = _place("P_meal1", category=["restaurant"])
    p_meal2 = _place("P_meal2", category=["restaurant"])
    p_meal3 = _place("P_meal3", category=["restaurant"])
    p_meal4 = _place("P_meal4", category=["restaurant"])
    p_meal5 = _place("P_meal5", category=["restaurant"])
    p_meal6 = _place("P_meal6", category=["restaurant"])
    p_lodging = _place(
        "P_lodging",
        category=["lodging"],
        opening=[(dow, "00:00", "23:59") for dow in range(7)],
    )
    pids = [p.place_id for p in [p_attr1, p_attr2, p_attr3, p_meal1, p_meal2, p_meal3, p_meal4, p_meal5, p_meal6, p_lodging]]
    edges = [_edge(i, j) for i in pids for j in pids if i != j]
    pack = _make_pack(
        places=[p_attr1, p_attr2, p_attr3, p_meal1, p_meal2, p_meal3, p_meal4, p_meal5, p_meal6, p_lodging],
        edges=edges,
        total_days=3,
    )
    # day1_lodging と day2_lodging に同じ P_lodging を割当 (連泊)。day3 は最終日で lodging skip。
    plan_v2 = LlmGeneratedPlanV2(
        slots=[
            LlmSlotAssignment(slot_id="day1_morning", place_id="P_attr1", rationale="day1 朝の観光地巡り"),
            LlmSlotAssignment(slot_id="day1_lunch", place_id="P_meal1", rationale="day1 ランチ食事処"),
            LlmSlotAssignment(slot_id="day1_afternoon", place_id="P_attr2", rationale="day1 午後観光地散策"),
            LlmSlotAssignment(slot_id="day1_dinner", place_id="P_meal2", rationale="day1 ディナー和食"),
            LlmSlotAssignment(slot_id="day1_lodging", place_id="P_lodging", rationale="day1 旅館連泊予定"),
            LlmSlotAssignment(slot_id="day2_morning", place_id="P_attr3", rationale="day2 朝の観光地巡り"),
            LlmSlotAssignment(slot_id="day2_lunch", place_id="P_meal3", rationale="day2 ランチ別店"),
            LlmSlotAssignment(slot_id="day2_afternoon", place_id="P_attr1", rationale="day2 午後観光地散策"),  # 重複 OK 想定
            LlmSlotAssignment(slot_id="day2_dinner", place_id="P_meal4", rationale="day2 ディナー和食"),
            LlmSlotAssignment(slot_id="day2_lodging", place_id="P_lodging", rationale="day2 同宿連泊継続"),
            LlmSlotAssignment(slot_id="day3_morning", place_id="P_attr2", rationale="day3 朝の観光地巡り"),
            LlmSlotAssignment(slot_id="day3_lunch", place_id="P_meal5", rationale="day3 帰路ランチ"),
            LlmSlotAssignment(slot_id="day3_afternoon", place_id="P_attr3", rationale="day3 午後観光地散策"),
            LlmSlotAssignment(slot_id="day3_dinner", place_id="P_meal6", rationale="day3 ディナー和食"),
        ]
    )
    with caplog.at_level(logging.WARNING, logger="src.llm.assembly"):
        result = assemble_plan(plan_v2, pack)
    place_items = [it for it in result.items if it.place_id is not None]
    # day1_lodging / day2_lodging の両方に P_lodging が連泊で採用される
    lodging_slot_items = [it for it in place_items if it.item_type == "lodging"]
    assert len(lodging_slot_items) == 2, (
        f"3 日 plan の lodging slot は day1+day2 で 2 件 (got {len(lodging_slot_items)})"
    )
    assert all(it.place_id == "P_lodging" for it in lodging_slot_items), (
        f"両 lodging slot に P_lodging が連泊採用されるべき (got {[it.place_id for it in lodging_slot_items]})"
    )
    # P_lodging が「重複検出の subject」として log に登場しない (used_place_ids exclusion 動作確認)
    # ※ "swapped to 'P_lodging'" のような subject 以外の出現は除外する
    lodging_subject_dup_logs = [
        rec.getMessage() for rec in caplog.records
        if "Duplicate place_id 'P_lodging'" in rec.getMessage()
    ]
    assert lodging_subject_dup_logs == [], (
        f"lodging slot で重複検出が起きてはいけない (used_place_ids exclusion): {lodging_subject_dup_logs}"
    )


def test_assemble_plan_meal_duplicate_falls_back_to_accept_when_no_alternate(caplog):
    """Phase 2 polish v5: meal slot で重複検出 + alternate なしのとき、warn + accept で
    plan を組み上げる (旧設計は item drop で continue)。
    """
    import logging

    p_attr = _place("P_attr", category=["tourist_attraction"])
    # meal restaurant 候補が 1 件しかない、もう 1 件 meal slot に重複させる
    p_meal = _place("P_meal", category=["restaurant"])
    edges = [_edge("P_attr", "P_meal"), _edge("P_meal", "P_attr"), _edge("P_meal", "P_meal")]
    pack = _make_pack(places=[p_attr, p_meal], edges=edges, total_days=1)
    plan_v2 = LlmGeneratedPlanV2(
        slots=[
            LlmSlotAssignment(slot_id="day1_morning", place_id="P_attr", rationale="day1 起点観光地巡り"),
            LlmSlotAssignment(slot_id="day1_lunch", place_id="P_meal", rationale="day1 lunch 1 つ目"),
            LlmSlotAssignment(slot_id="day1_dinner", place_id="P_meal", rationale="day1 dinner 重複"),
        ]
    )
    with caplog.at_level(logging.WARNING, logger="src.llm.assembly"):
        result = assemble_plan(plan_v2, pack)
    place_items = [it for it in result.items if it.place_id is not None]
    # P_meal は重複したまま 2 度採用される (旧 v1 の drop なし、v5 の accept fallback)
    p_meal_count = sum(1 for it in place_items if it.place_id == "P_meal")
    assert p_meal_count == 2
    assert any(
        "accepting duplicate" in rec.getMessage()
        for rec in caplog.records
    ), [rec.getMessage() for rec in caplog.records]


def test_assemble_plan_skips_transit_for_consecutive_same_place(caplog):
    """Phase 2 polish v5 (Codex review 2 Major 3): 連続 slot で同 place_id のとき
    self-loop transit edge は禁止のため transit item を生成 skip。lodging 連泊 + 翌朝
    同宿で朝食的な使い方を想定。
    """
    import logging

    p_lodge = _place(
        "P_lodge",
        category=["lodging"],
        opening=[(dow, "00:00", "23:59") for dow in range(7)],
    )
    pack = _make_pack(places=[p_lodge], edges=[], total_days=2)
    # day1_lodging → day2_morning で同じ宿 (連泊して朝食)
    plan_v2 = LlmGeneratedPlanV2(
        slots=[
            LlmSlotAssignment(slot_id="day1_lodging", place_id="P_lodge", rationale="day1 lodging 連泊予定"),
            LlmSlotAssignment(slot_id="day2_morning", place_id="P_lodge", rationale="day2 朝食同宿で連泊"),
        ]
    )
    with caplog.at_level(logging.INFO, logger="src.llm.assembly"):
        result = assemble_plan(plan_v2, pack)
    transit_count = sum(1 for it in result.items if it.item_type == "transit")
    assert transit_count == 0  # 連続同 place で transit skip
    assert any(
        "Same place as previous slot" in rec.getMessage()
        for rec in caplog.records
    ), [rec.getMessage() for rec in caplog.records]


def test_assemble_plan_lodging_repeat_does_not_trigger_swap(caplog):
    """Phase 2 polish v5 (Codex review 1 Minor 1 反映): lodging slot は重複検出から
    除外されるので、3 日 plan で連泊させたとき lodging に対する swap log が一切出ない。
    `used_place_ids` に lodging を加えない設計の検証。
    """
    import logging

    p_attr = _place("P_attr", category=["tourist_attraction"])
    p_attr2 = _place("P_attr2", category=["tourist_attraction"])
    p_meal1 = _place("P_meal1", category=["restaurant"])
    p_meal2 = _place("P_meal2", category=["restaurant"])
    p_meal3 = _place("P_meal3", category=["restaurant"])
    p_lodge = _place(
        "P_lodge",
        category=["lodging"],
        opening=[(dow, "00:00", "23:59") for dow in range(7)],
    )
    pids = ["P_attr", "P_attr2", "P_meal1", "P_meal2", "P_meal3", "P_lodge"]
    edges = [_edge(i, j) for i in pids for j in pids if i != j]
    pack = _make_pack(
        places=[p_attr, p_attr2, p_meal1, p_meal2, p_meal3, p_lodge],
        edges=edges,
        total_days=3,
    )
    plan_v2 = LlmGeneratedPlanV2(
        slots=[
            LlmSlotAssignment(slot_id="day1_morning", place_id="P_attr", rationale="day1 朝の観光地巡り"),
            LlmSlotAssignment(slot_id="day1_lunch", place_id="P_meal1", rationale="day1 ランチ食事処"),
            LlmSlotAssignment(slot_id="day1_lodging", place_id="P_lodge", rationale="day1 lodging 連泊予定"),
            LlmSlotAssignment(slot_id="day2_morning", place_id="P_attr2", rationale="day2 朝の観光別所"),
            LlmSlotAssignment(slot_id="day2_lunch", place_id="P_meal2", rationale="day2 ランチ別店訪"),
            LlmSlotAssignment(slot_id="day2_lodging", place_id="P_lodge", rationale="day2 同宿連泊継続"),
            LlmSlotAssignment(slot_id="day3_morning", place_id="P_attr", rationale="day3 朝の観光再訪"),
            LlmSlotAssignment(slot_id="day3_lunch", place_id="P_meal3", rationale="day3 帰路ランチ"),
        ]
    )
    with caplog.at_level(logging.WARNING, logger="src.llm.assembly"):
        result = assemble_plan(plan_v2, pack)
    place_items = [it for it in result.items if it.place_id is not None]
    # P_lodge は day1 + day2 lodging で重複採用 (連泊)
    lodge_count = sum(1 for it in place_items if it.place_id == "P_lodge")
    assert lodge_count == 2
    # P_lodge を subject とする「Duplicate place_id 'P_lodge' in slot ...」が出ない
    # (lodging exclusion で重複検出 path に入らない)
    lodge_subject_dup_logs = [
        rec.getMessage() for rec in caplog.records
        if "Duplicate place_id 'P_lodge'" in rec.getMessage()
    ]
    assert lodge_subject_dup_logs == [], (
        f"lodging slot で重複検出が起きてはいけない: {lodge_subject_dup_logs}"
    )


def test_assemble_plan_transit_skip_path_preserves_monotonic_start_time():
    """Phase 2 polish v5 (Codex review 1 Minor 2): transit skip path (edge なし → skip)
    で時刻補正 `max(start_dt, prev_end_dt)` が効いて、後 slot の start_time が前 slot の
    end_time より遅いことを assert する。`OVERLAPPING_ITEMS` 防止の invariant。
    """
    p_a = _place(
        "P_A",
        category=["point_of_interest"],
        opening=[(dow, "00:00", "23:59") for dow in range(7)],
    )
    p_b = _place(
        "P_B",
        category=["point_of_interest"],
        opening=[(dow, "00:00", "23:59") for dow in range(7)],
    )
    # edge 不在 → transit item skip path に入る
    pack = _make_pack(places=[p_a, p_b], edges=[], total_days=1)
    plan_v2 = LlmGeneratedPlanV2(
        slots=[
            LlmSlotAssignment(slot_id="day1_morning", place_id="P_A", rationale="day1 朝の観光地巡り"),
            LlmSlotAssignment(slot_id="day1_lunch", place_id="P_B", rationale="day1 ランチ食事処"),
        ]
    )
    result = assemble_plan(plan_v2, pack)
    place_items = [it for it in result.items if it.place_id is not None]
    assert len(place_items) == 2
    # 後 slot の start_time が前 slot の end_time 以降
    from datetime import datetime as _dt
    prev_end = _dt.fromisoformat(place_items[0].end_time)
    next_start = _dt.fromisoformat(place_items[1].start_time)
    assert next_start >= prev_end, (
        f"transit skip path で後 slot start_time={next_start} は前 slot end_time={prev_end} 以降であるべき"
    )


def test_assemble_plan_consecutive_same_place_preserves_monotonic_start_time():
    """Phase 2 polish v5 (Codex review 2 Minor 1): 連続同 place skip path で時刻補正
    `max(start_dt, prev_end_dt)` が効いて、後 slot の start_time が前 slot の end_time
    より遅いことを assert する。lodging 連泊 + 翌朝同宿シナリオの invariant。
    """
    p_lodge = _place(
        "P_lodge",
        category=["lodging"],
        opening=[(dow, "00:00", "23:59") for dow in range(7)],
    )
    pack = _make_pack(places=[p_lodge], edges=[], total_days=2)
    # day1_lodging → day2_morning で同 place (連続同 place path)
    plan_v2 = LlmGeneratedPlanV2(
        slots=[
            LlmSlotAssignment(slot_id="day1_lodging", place_id="P_lodge", rationale="day1 lodging 連泊予定"),
            LlmSlotAssignment(slot_id="day2_morning", place_id="P_lodge", rationale="day2 朝食同宿で連泊"),
        ]
    )
    result = assemble_plan(plan_v2, pack)
    place_items = [it for it in result.items if it.place_id is not None]
    assert len(place_items) == 2
    from datetime import datetime as _dt
    prev_end = _dt.fromisoformat(place_items[0].end_time)
    next_start = _dt.fromisoformat(place_items[1].start_time)
    assert next_start >= prev_end, (
        f"連続同 place skip path で後 slot start_time={next_start} は前 slot end_time={prev_end} 以降であるべき"
    )


# ==============================
# Phase 2 polish v6: assembler item_type pre-check + duration_min=0 → 1 min 補正
# ==============================


def test_assemble_plan_item_type_pre_check_swaps_park_in_meal_slot(caplog):
    """v6: LLM が meal slot に park (公園) を割当てた場合、assembler が事前検出して
    `_find_eligible_alternate_for_slot` で restaurant 系に swap する。
    本番 Run 13e で観測された `item_type_category_mismatch` 多発の対策。
    """
    import logging

    p_attr = _place("P_attr", category=["tourist_attraction"])
    p_park = _place("P_park", category=["park"])  # LLM が誤って meal slot に割当
    p_restaurant = _place("P_restaurant", category=["restaurant"])  # 正しい meal slot 候補
    edges = [
        _edge("P_attr", "P_park"), _edge("P_attr", "P_restaurant"),
        _edge("P_park", "P_attr"), _edge("P_restaurant", "P_attr"),
        _edge("P_park", "P_restaurant"), _edge("P_restaurant", "P_park"),
    ]
    pack = _make_pack(places=[p_attr, p_park, p_restaurant], edges=edges, total_days=1)
    plan_v2 = LlmGeneratedPlanV2(
        slots=[
            LlmSlotAssignment(slot_id="day1_morning", place_id="P_attr", rationale="day1 朝の観光地巡り"),
            LlmSlotAssignment(slot_id="day1_lunch", place_id="P_park", rationale="LLM が park を meal に誤割当"),
        ]
    )
    with caplog.at_level(logging.WARNING, logger="src.llm.assembly"):
        result = assemble_plan(plan_v2, pack)
    place_items = [it for it in result.items if it.place_id is not None]
    # day1_lunch が P_park ではなく P_restaurant に swap される
    lunch_item = next(it for it in place_items if it.item_type == "meal")
    assert lunch_item.place_id == "P_restaurant", (
        f"meal slot は restaurant に swap されるべき (got {lunch_item.place_id})"
    )
    # swap log 確認
    assert any(
        "item_type-mismatched" in rec.getMessage() and "swapped to" in rec.getMessage()
        for rec in caplog.records
    )


def test_assemble_plan_transit_duration_zero_uses_minimum_one_minute():
    """v6: edge.duration_min=0 (徒歩 0 分の至近距離) のとき、transit item の
    start_time == end_time にならないよう最小 1 分の duration を保証する
    (validator の `INVALID_TIME_RANGE` を構造的に防ぐ)。
    """
    p_a = _place("P_A", category=["tourist_attraction"])
    p_b = _place("P_B", category=["restaurant"])
    edge_zero = TransitEdge(
        from_place_id="P_A",
        to_place_id="P_B",
        mode="walk",
        route_summary="徒歩 (至近距離)",
        duration_min=0,  # 至近距離
        fare_jpy=None,
        candidate_departures=["09:00", "12:00", "15:00"],
    )
    pack = _make_pack(places=[p_a, p_b], edges=[edge_zero])
    plan_v2 = LlmGeneratedPlanV2(
        slots=[
            LlmSlotAssignment(slot_id="day1_morning", place_id="P_A", rationale="day1 朝の観光地巡り"),
            LlmSlotAssignment(slot_id="day1_lunch", place_id="P_B", rationale="day1 ランチ食事処"),
        ]
    )
    result = assemble_plan(plan_v2, pack)
    # transit item が含まれている、start_time != end_time であることを確認
    transit_items = [it for it in result.items if it.item_type == "transit"]
    assert len(transit_items) == 1
    transit_item = transit_items[0]
    from datetime import datetime as _dt
    transit_start = _dt.fromisoformat(transit_item.start_time)
    transit_end = _dt.fromisoformat(transit_item.end_time)
    assert transit_end > transit_start, (
        f"duration_min=0 でも transit_end ({transit_end}) > transit_start ({transit_start}) "
        f"であるべき (最小 1 分補正)"
    )


# ==============================
# Phase 2 polish v6.2: item_type pre-check fallback で used 集合から reuse
# ==============================


def test_assemble_plan_item_type_reuses_used_meal_when_candidates_exhausted(caplog):
    """v6.2: meal slot で alternate 候補が枯渇したとき、used 集合内 meal place を再使用する。

    本番 Run 13f で `item_type_category_mismatch` 多発の対策。pack の meal candidate が
    薄いと 4-6 meal slot を埋めるには candidate 不足 → tier3 filtered out → accept で
    item_type 不適合 place を採用 → validator が item_type_category_mismatch 連発。

    fix: alternate なし時に used 集合の中で meal-compatible を reuse、validator は重複自体を
    issue にしないので 422 を防げる。
    """
    import logging

    p_attr = _place("P_attr", category=["tourist_attraction"])
    p_park = _place("P_park", category=["park"])  # LLM が誤 meal 割当
    p_restaurant = _place("P_restaurant", category=["restaurant"])  # 唯一の meal
    edges = [
        _edge("P_attr", "P_restaurant"), _edge("P_restaurant", "P_attr"),
        _edge("P_attr", "P_park"), _edge("P_park", "P_attr"),
        _edge("P_restaurant", "P_park"), _edge("P_park", "P_restaurant"),
    ]
    pack = _make_pack(places=[p_attr, p_park, p_restaurant], edges=edges, total_days=1)
    plan_v2 = LlmGeneratedPlanV2(
        slots=[
            LlmSlotAssignment(slot_id="day1_morning", place_id="P_attr", rationale="day1 朝の観光地巡り"),
            LlmSlotAssignment(slot_id="day1_lunch", place_id="P_restaurant", rationale="day1 ランチ食事処"),
            LlmSlotAssignment(slot_id="day1_dinner", place_id="P_park", rationale="LLM 誤割当 dinner park"),
        ]
    )
    with caplog.at_level(logging.WARNING, logger="src.llm.assembly"):
        result = assemble_plan(plan_v2, pack)
    place_items = [it for it in result.items if it.place_id is not None]
    # day1_dinner は item_type pre-check で park → P_restaurant に reuse される
    dinner_items = [it for it in place_items if it.item_type == "meal"]
    # lunch + dinner で 2 件、両方 P_restaurant (重複 OK で item_type 守る)
    assert len(dinner_items) == 2
    assert all(it.place_id == "P_restaurant" for it in dinner_items)
    assert any(
        "reusing already-used" in rec.getMessage() and "item_type integrity" in rec.getMessage()
        for rec in caplog.records
    )


def test_find_item_type_compatible_used_place_skips_when_no_compatible_in_used():
    """used 集合に item_type compatible がない場合は None を返す (caller は accept fallback)。"""
    from src.llm.assembly import _find_item_type_compatible_used_place

    p_attr = _place("P_attr", category=["tourist_attraction"])
    p_park = _place("P_park", category=["park"])
    pack = _make_pack(places=[p_attr, p_park], edges=[], total_days=1)
    used = {"P_attr", "P_park"}
    slot_meta = {
        "slot_id": "day1_lunch",
        "start_hhmm": "12:00",
        "end_hhmm": "14:00",
        "item_type": "meal",
    }
    result = _find_item_type_compatible_used_place(
        pack=pack,
        used_place_ids=used,
        item_type="meal",
        slot_meta=slot_meta,
        slot_date=date(2026, 6, 1),
        prev_place_id=None,
    )
    assert result is None  # used に meal-compatible なし
