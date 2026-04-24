"""`apps/api/src/llm/validator.py` のテスト（Phase 1.3d Branch A）。

計画書 v3 の 13 項目すべてに対応する。失敗時は `ValidationIssue` を list で集約して返し、
retry プロンプトで LLM に self-correction させる用途。validator は reject でなく「issues 列挙」。
"""

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
    QueryContextParticipant,
    TemporalConstraints,
    TransitEdge,
)
from src.llm.schema import LlmGeneratedPlan, LlmPlanItem, LlmTransitRef
from src.llm.validator import (
    IssueKind,
    ValidationIssue,
    validate_llm_output,
)
from src.schemas import BudgetBreakdown


def _place(
    place_id: str,
    *,
    name: str = "",
    opening_hours: list[OpeningHoursSlot] | None = None,
    unknown_days: list[int] | None = None,
) -> PlacePoint:
    return PlacePoint(
        place_id=place_id,
        name=name or f"p-{place_id}",
        category=[],
        lat=35.0,
        lng=139.0,
        address="addr",
        opening_hours=opening_hours or [],
        opening_hours_unknown_days=unknown_days or [],
        price_level=None,
        rating=None,
        user_ratings_total=None,
    )


def _edge(
    a: str,
    b: str,
    *,
    mode: str = "train",
    duration_min: int = 30,
    fare_jpy: int | None = 500,
    candidate_departures: list[str] | None = None,
    route_summary: str = "JR",
) -> TransitEdge:
    return TransitEdge(
        from_place_id=a,
        to_place_id=b,
        mode=mode,
        route_summary=route_summary,
        duration_min=duration_min,
        fare_jpy=fare_jpy,
        candidate_departures=candidate_departures or ["09:00"],
    )


def _pack(
    *,
    places: list[PlacePoint] | None = None,
    transit_matrix: list[TransitEdge] | None = None,
    breakdown_jpy: tuple[int, int, int, int] = (12000, 9000, 6000, 3000),
) -> EvidencePack:
    if places is None:
        places = [_place("A"), _place("B")]
    lodging, meal, activity, transit = breakdown_jpy
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
        places=places,
        transit_matrix=transit_matrix or [],
        budget_constraints=BudgetConstraints(
            total_jpy_per_person=30000,
            breakdown_percent=BudgetBreakdown(lodging=40, meal=30, activity=20, transit=10),
            breakdown_jpy=BudgetBreakdownJPY(
                lodging=lodging, meal=meal, activity=activity, transit=transit
            ),
        ),
        temporal_constraints=TemporalConstraints(
            start_datetime="2026-06-01T09:00:00+09:00",
            end_datetime="2026-06-02T20:00:00+09:00",
            total_days=2,
        ),
    )


def _activity(
    *,
    order_index: int = 0,
    place_id: str = "A",
    start_time: str = "2026-06-01T10:00:00+09:00",
    end_time: str = "2026-06-01T12:00:00+09:00",
    cost_jpy: int | None = 1000,
    cost_confidence: str = "verified",
    title: str = "t",
) -> LlmPlanItem:
    return LlmPlanItem(
        order_index=order_index,
        item_type="activity",
        title=title,
        description=None,
        start_time=start_time,
        end_time=end_time,
        place_id=place_id,
        cost_jpy=cost_jpy,
        cost_confidence=cost_confidence,
        transit_ref=None,
    )


def _transit_item(
    *,
    order_index: int = 0,
    start_time: str = "2026-06-01T09:00:00+09:00",
    end_time: str = "2026-06-01T09:30:00+09:00",
    cost_jpy: int | None = 500,
    cost_confidence: str = "verified",
    from_place_id: str = "A",
    to_place_id: str = "B",
    departure_time: str = "09:00",
) -> LlmPlanItem:
    return LlmPlanItem(
        order_index=order_index,
        item_type="transit",
        title="A→B",
        description=None,
        start_time=start_time,
        end_time=end_time,
        place_id=None,
        cost_jpy=cost_jpy,
        cost_confidence=cost_confidence,
        transit_ref=LlmTransitRef(
            from_place_id=from_place_id,
            to_place_id=to_place_id,
            departure_time=departure_time,
        ),
    )


def _plan(*items: LlmPlanItem) -> LlmGeneratedPlan:
    return LlmGeneratedPlan(items=list(items))


# ==============================
# 基本: 全項目 OK
# ==============================


def test_happy_path_no_issues():
    pack = _pack(places=[_place("A"), _place("B")], transit_matrix=[_edge("A", "B")])
    plan = _plan(_activity(place_id="A"))
    issues = validate_llm_output(plan, pack)
    assert issues == []


# ==============================
# #2 item_type ごとの必須フィールド
# ==============================


def test_activity_missing_place_id_is_issue():
    pack = _pack()
    plan = _plan(_activity(place_id=None))
    # Pydantic は place_id=None を許すが、validator が item_type=activity では必須と判断
    plan.items[0].place_id = None  # 念のため明示
    issues = validate_llm_output(plan, pack)
    assert any(i.kind == IssueKind.MISSING_REQUIRED_FIELD for i in issues)


def test_transit_missing_transit_ref_is_issue():
    pack = _pack()
    plan = _plan(
        LlmPlanItem(
            order_index=0,
            item_type="transit",
            title="x",
            description=None,
            start_time="2026-06-01T09:00:00+09:00",
            end_time="2026-06-01T09:30:00+09:00",
            place_id=None,
            cost_jpy=500,
            cost_confidence="verified",
            transit_ref=None,
        )
    )
    issues = validate_llm_output(plan, pack)
    assert any(i.kind == IssueKind.MISSING_REQUIRED_FIELD for i in issues)


# ==============================
# #3 place_id 実在
# ==============================


def test_unknown_place_id_is_issue():
    pack = _pack(places=[_place("A")])
    plan = _plan(_activity(place_id="Z"))
    issues = validate_llm_output(plan, pack)
    assert any(i.kind == IssueKind.UNKNOWN_PLACE_ID for i in issues)


# ==============================
# #4 時刻順序
# ==============================


def test_invalid_time_range_is_issue():
    pack = _pack()
    plan = _plan(
        _activity(
            start_time="2026-06-01T12:00:00+09:00",
            end_time="2026-06-01T10:00:00+09:00",
        )
    )
    issues = validate_llm_output(plan, pack)
    assert any(i.kind == IssueKind.INVALID_TIME_RANGE for i in issues)


# ==============================
# #5 営業時間内
# ==============================


def test_outside_opening_hours_is_issue():
    # 月曜のみ 09:00-17:00、LLM が 18:00 開始で activity を置く
    pack = _pack(
        places=[_place(
            "A",
            opening_hours=[
                OpeningHoursSlot(day_of_week=0, open_hhmm="09:00", close_hhmm="17:00")
            ],
        )]
    )
    plan = _plan(
        _activity(
            start_time="2026-06-01T18:00:00+09:00",  # 月曜 18:00（閉店後）
            end_time="2026-06-01T19:00:00+09:00",
        )
    )
    issues = validate_llm_output(plan, pack)
    assert any(i.kind == IssueKind.OUTSIDE_OPENING_HOURS for i in issues)


def test_within_opening_hours_no_issue():
    pack = _pack(
        places=[_place(
            "A",
            opening_hours=[
                OpeningHoursSlot(day_of_week=0, open_hhmm="09:00", close_hhmm="17:00")
            ],
        )]
    )
    plan = _plan(_activity(
        start_time="2026-06-01T10:00:00+09:00",
        end_time="2026-06-01T12:00:00+09:00",
    ))
    issues = validate_llm_output(plan, pack)
    assert not any(i.kind == IssueKind.OUTSIDE_OPENING_HOURS for i in issues)


def test_opening_hours_empty_skips_validation():
    """opening_hours=[] は情報なし扱いで block しない。"""
    pack = _pack(places=[_place("A", opening_hours=[])])
    plan = _plan(_activity(
        start_time="2026-06-01T23:30:00+09:00",
        end_time="2026-06-01T23:59:00+09:00",
    ))
    issues = validate_llm_output(plan, pack)
    assert not any(i.kind == IssueKind.OUTSIDE_OPENING_HOURS for i in issues)


def test_opening_hours_unknown_day_skips_validation():
    """unknown_days に含まれる曜日は検証スキップ（計画書 v3 仕様）。"""
    pack = _pack(places=[_place("A", opening_hours=[], unknown_days=[0])])
    plan = _plan(_activity(
        start_time="2026-06-01T03:00:00+09:00",  # 月曜 深夜
        end_time="2026-06-01T05:00:00+09:00",
    ))
    issues = validate_llm_output(plan, pack)
    assert not any(i.kind == IssueKind.OUTSIDE_OPENING_HOURS for i in issues)


# ==============================
# #6 transit edge 存在
# ==============================


def test_transit_unknown_edge_is_issue():
    pack = _pack(
        places=[_place("A"), _place("B")],
        transit_matrix=[_edge("A", "B")],
    )
    plan = _plan(_transit_item(from_place_id="A", to_place_id="X"))
    issues = validate_llm_output(plan, pack)
    assert any(i.kind == IssueKind.UNKNOWN_TRANSIT_EDGE for i in issues)


# ==============================
# #7 transit departure_time 整合
# ==============================


def test_transit_departure_not_in_candidates_is_issue():
    pack = _pack(
        transit_matrix=[_edge("A", "B", candidate_departures=["09:00", "09:30"])]
    )
    plan = _plan(_transit_item(departure_time="10:00"))  # 候補外
    issues = validate_llm_output(plan, pack)
    assert any(i.kind == IssueKind.TRANSIT_DEPARTURE_MISMATCH for i in issues)


# ==============================
# #8 transit duration 整合
# ==============================


def test_transit_duration_mismatch_is_issue():
    # edge は 30 分、item は 60 分 → ±5 分許容超過
    pack = _pack(transit_matrix=[_edge("A", "B", duration_min=30)])
    plan = _plan(_transit_item(
        start_time="2026-06-01T09:00:00+09:00",
        end_time="2026-06-01T10:00:00+09:00",  # 60 分
    ))
    issues = validate_llm_output(plan, pack)
    assert any(i.kind == IssueKind.TRANSIT_DURATION_MISMATCH for i in issues)


def test_transit_duration_within_tolerance_no_issue():
    pack = _pack(transit_matrix=[_edge("A", "B", duration_min=30)])
    plan = _plan(_transit_item(
        start_time="2026-06-01T09:00:00+09:00",
        end_time="2026-06-01T09:33:00+09:00",  # 33 分 = edge 30 + 3 分、許容内
    ))
    issues = validate_llm_output(plan, pack)
    assert not any(i.kind == IssueKind.TRANSIT_DURATION_MISMATCH for i in issues)


# ==============================
# #9 transit fare 整合
# ==============================


def test_transit_fare_mismatch_is_issue():
    pack = _pack(transit_matrix=[_edge("A", "B", fare_jpy=500)])
    plan = _plan(_transit_item(cost_jpy=700))
    issues = validate_llm_output(plan, pack)
    assert any(i.kind == IssueKind.TRANSIT_FARE_MISMATCH for i in issues)


def test_transit_fare_null_edge_requires_unknown_confidence():
    """edge.fare_jpy が null の場合、item.cost_confidence は 'unknown' 必須。"""
    pack = _pack(transit_matrix=[_edge("A", "B", fare_jpy=None)])
    plan = _plan(_transit_item(cost_jpy=500, cost_confidence="verified"))
    issues = validate_llm_output(plan, pack)
    assert any(i.kind == IssueKind.TRANSIT_FARE_MISMATCH for i in issues)


def test_transit_fare_null_edge_with_unknown_confidence_ok():
    pack = _pack(transit_matrix=[_edge("A", "B", fare_jpy=None)])
    plan = _plan(_transit_item(cost_jpy=None, cost_confidence="unknown"))
    issues = validate_llm_output(plan, pack)
    assert not any(i.kind == IssueKind.TRANSIT_FARE_MISMATCH for i in issues)


# ==============================
# #10 予算超過
# ==============================


def test_budget_exceeded_is_issue():
    # activity 枠 6000 円、LLM が 10000 円の activity を入れる
    pack = _pack(breakdown_jpy=(12000, 9000, 6000, 3000))
    plan = _plan(_activity(cost_jpy=10000))
    issues = validate_llm_output(plan, pack)
    assert any(i.kind == IssueKind.BUDGET_EXCEEDED for i in issues)


def test_budget_within_tolerance_ok():
    # activity 枠 6000 円、5% 誤差まで OK → 6300 まで許容
    pack = _pack(breakdown_jpy=(12000, 9000, 6000, 3000))
    plan = _plan(_activity(cost_jpy=6200))
    issues = validate_llm_output(plan, pack)
    assert not any(i.kind == IssueKind.BUDGET_EXCEEDED for i in issues)


# ==============================
# #11 時系列重複 / 逆転
# ==============================


def test_overlapping_items_is_issue():
    pack = _pack(places=[_place("A"), _place("B")])
    plan = _plan(
        _activity(order_index=0, place_id="A",
                  start_time="2026-06-01T10:00:00+09:00",
                  end_time="2026-06-01T12:00:00+09:00"),
        _activity(order_index=1, place_id="B",
                  start_time="2026-06-01T11:00:00+09:00",  # overlap
                  end_time="2026-06-01T13:00:00+09:00"),
    )
    issues = validate_llm_output(plan, pack)
    assert any(i.kind == IssueKind.OVERLAPPING_ITEMS for i in issues)


# ==============================
# #12 temporal 範囲
# ==============================


def test_out_of_temporal_range_is_issue():
    pack = _pack()  # start=2026-06-01 09:00, end=2026-06-02 20:00 JST
    plan = _plan(_activity(
        start_time="2026-06-03T10:00:00+09:00",  # 範囲外
        end_time="2026-06-03T12:00:00+09:00",
    ))
    issues = validate_llm_output(plan, pack)
    assert any(i.kind == IssueKind.OUT_OF_TEMPORAL_RANGE for i in issues)


# ==============================
# #13 start_time の timezone 必須
# ==============================


def test_missing_timezone_is_issue():
    pack = _pack()
    plan = _plan(_activity(
        start_time="2026-06-01T10:00:00",  # tz なし
        end_time="2026-06-01T12:00:00",
    ))
    issues = validate_llm_output(plan, pack)
    assert any(i.kind == IssueKind.MISSING_TIMEZONE for i in issues)


# ==============================
# ValidationIssue shape
# ==============================


def test_validation_issue_has_kind_and_message_and_item_index():
    pack = _pack()
    plan = _plan(_activity(place_id="X"))  # unknown
    issues = validate_llm_output(plan, pack)
    assert len(issues) >= 1
    issue = next(i for i in issues if i.kind == IssueKind.UNKNOWN_PLACE_ID)
    assert issue.message  # 非空文字列
    assert issue.item_index == 0
