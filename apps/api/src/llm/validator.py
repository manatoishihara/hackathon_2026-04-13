"""LLM 出力のハルシネーション検出 / 整合性検証（Phase 1.3d）。

計画書 v3「ハルシネーション検出 / Validator」節の 13 項目を実装する（schema 検証は
Pydantic 側で担保されるので 2 項目目以降）。失敗時は `ValidationIssue` を list で集約して
返す（throw せず、retry プロンプトで LLM 自己訂正させるため）。

OpenAI Structured Output により schema 違反は先に弾かれるので、本 validator は
「schema 通過後の意味論的違反」のみを扱う:
- item_type ごとの必須フィールド
- place_id が Evidence Pack に実在
- 時刻順序（start < end）
- 営業時間内（unknown_days は skip）
- transit edge 存在
- transit departure_time / duration / fare の整合
- 予算超過（category 別合計 vs budget_constraints.breakdown_jpy）
- 時系列重複 / 逆転
- temporal 範囲
- start_time の timezone 必須
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Iterable

from ..evidence.pack import EvidencePack, OpeningHoursSlot, TransitEdge
from .schema import LlmGeneratedPlan, LlmPlanItem


class IssueKind(str, Enum):
    MISSING_REQUIRED_FIELD = "missing_required_field"
    UNKNOWN_PLACE_ID = "unknown_place_id"
    INVALID_TIME_RANGE = "invalid_time_range"
    OUTSIDE_OPENING_HOURS = "outside_opening_hours"
    UNKNOWN_TRANSIT_EDGE = "unknown_transit_edge"
    TRANSIT_DEPARTURE_MISMATCH = "transit_departure_mismatch"
    TRANSIT_DURATION_MISMATCH = "transit_duration_mismatch"
    TRANSIT_FARE_MISMATCH = "transit_fare_mismatch"
    BUDGET_EXCEEDED = "budget_exceeded"
    OVERLAPPING_ITEMS = "overlapping_items"
    OUT_OF_TEMPORAL_RANGE = "out_of_temporal_range"
    MISSING_TIMEZONE = "missing_timezone"
    ITEM_TYPE_CATEGORY_MISMATCH = "item_type_category_mismatch"


@dataclass(frozen=True)
class ValidationIssue:
    kind: IssueKind
    message: str
    item_index: int | None = None  # None は計画全体に対する issue

    def to_prompt_line(self) -> str:
        """retry プロンプトに注入する 1 行表現。"""
        prefix = f"items[{self.item_index}]" if self.item_index is not None else "plan"
        return f"- [{self.kind.value}] {prefix}: {self.message}"


DURATION_TOLERANCE_MIN = 5
BUDGET_TOLERANCE_RATIO = 0.05

# meal slot の place が「飲食」を表す category を持つか判定するための allowlist。
# Google Places API の細粒度 category（`japanese_restaurant` 等の `_restaurant` 接尾辞）も
# 後段の suffix check で許容する。
_MEAL_CATEGORIES: frozenset[str] = frozenset(
    {
        "restaurant",
        "food",
        "cafe",
        "bakery",
        "bar",
        "meal_takeaway",
        "meal_delivery",
    }
)

# lodging slot の place が「宿泊」を表す category を持つか判定するための allowlist。
_LODGING_CATEGORIES: frozenset[str] = frozenset(
    {
        "lodging",
        "hotel",
        "resort_hotel",
        "ryokan",
        "bed_and_breakfast",
        "extended_stay_hotel",
        "hostel",
        "motel",
        "guest_house",
        "inn",
    }
)


def _categories_indicate_meal(categories: list[str]) -> bool:
    """category list に飲食を示すラベルが含まれるか。`*_restaurant` 接尾辞も許容。"""
    for c in categories:
        if c in _MEAL_CATEGORIES or c.endswith("_restaurant"):
            return True
    return False


def _categories_indicate_lodging(categories: list[str]) -> bool:
    return any(c in _LODGING_CATEGORIES for c in categories)


def validate_llm_output(
    plan: LlmGeneratedPlan, pack: EvidencePack
) -> list[ValidationIssue]:
    """LLM 出力 `plan` を Evidence Pack `pack` と照合して issue 一覧を返す。

    issue が空リストなら全検証パス、非空ならリトライ（呼び出し側の generator 責任）。
    """
    issues: list[ValidationIssue] = []
    places_by_id = {p.place_id: p for p in pack.places}
    edges_by_key = _index_edges(pack.transit_matrix)

    for idx, item in enumerate(plan.items):
        _check_required_fields(issues, idx, item)
        _check_place_id(issues, idx, item, places_by_id)
        start_dt = _parse_datetime(item.start_time)
        end_dt = _parse_datetime(item.end_time)
        _check_timezone(issues, idx, item, start_dt, end_dt)
        _check_time_range(issues, idx, item, start_dt, end_dt)
        _check_temporal_range(issues, idx, item, start_dt, end_dt, pack)
        _check_opening_hours(issues, idx, item, start_dt, places_by_id)
        _check_transit_details(issues, idx, item, edges_by_key, start_dt, end_dt)
        _check_item_type_category_consistency(issues, idx, item, places_by_id)

    _check_overlapping_items(issues, plan.items)
    _check_budget(issues, plan.items, pack)

    return issues


# ==============================
# 個別チェック
# ==============================


def _check_required_fields(
    issues: list[ValidationIssue], idx: int, item: LlmPlanItem
) -> None:
    if item.item_type in ("activity", "meal", "lodging"):
        if not item.place_id:
            issues.append(
                ValidationIssue(
                    IssueKind.MISSING_REQUIRED_FIELD,
                    f"{item.item_type} item は place_id 必須",
                    idx,
                )
            )
        if item.transit_ref is not None:
            issues.append(
                ValidationIssue(
                    IssueKind.MISSING_REQUIRED_FIELD,
                    f"{item.item_type} item は transit_ref を持たない",
                    idx,
                )
            )
    elif item.item_type == "transit":
        if item.transit_ref is None:
            issues.append(
                ValidationIssue(
                    IssueKind.MISSING_REQUIRED_FIELD,
                    "transit item は transit_ref 必須",
                    idx,
                )
            )


def _check_place_id(
    issues: list[ValidationIssue],
    idx: int,
    item: LlmPlanItem,
    places_by_id: dict[str, object],
) -> None:
    if item.place_id is not None and item.place_id not in places_by_id:
        issues.append(
            ValidationIssue(
                IssueKind.UNKNOWN_PLACE_ID,
                f"place_id={item.place_id!r} は evidence_pack.places に存在しない",
                idx,
            )
        )


def _check_timezone(
    issues: list[ValidationIssue],
    idx: int,
    item: LlmPlanItem,
    start_dt: datetime | None,
    end_dt: datetime | None,
) -> None:
    if start_dt is not None and start_dt.tzinfo is None:
        issues.append(
            ValidationIssue(
                IssueKind.MISSING_TIMEZONE,
                "start_time は timezone（JST +09:00）を明示すること",
                idx,
            )
        )
    if end_dt is not None and end_dt.tzinfo is None:
        issues.append(
            ValidationIssue(
                IssueKind.MISSING_TIMEZONE,
                "end_time は timezone（JST +09:00）を明示すること",
                idx,
            )
        )


def _check_time_range(
    issues: list[ValidationIssue],
    idx: int,
    item: LlmPlanItem,
    start_dt: datetime | None,
    end_dt: datetime | None,
) -> None:
    if start_dt is None or end_dt is None:
        # parse 失敗は MISSING_TIMEZONE でも拾うが、fromisoformat 完全失敗の場合だけここで別途エラー
        if start_dt is None:
            issues.append(
                ValidationIssue(
                    IssueKind.INVALID_TIME_RANGE,
                    f"start_time を ISO 8601 としてパースできない: {item.start_time!r}",
                    idx,
                )
            )
        if end_dt is None:
            issues.append(
                ValidationIssue(
                    IssueKind.INVALID_TIME_RANGE,
                    f"end_time を ISO 8601 としてパースできない: {item.end_time!r}",
                    idx,
                )
            )
        return
    if start_dt >= end_dt:
        issues.append(
            ValidationIssue(
                IssueKind.INVALID_TIME_RANGE,
                f"start_time ({item.start_time}) >= end_time ({item.end_time})",
                idx,
            )
        )


def _check_temporal_range(
    issues: list[ValidationIssue],
    idx: int,
    item: LlmPlanItem,
    start_dt: datetime | None,
    end_dt: datetime | None,
    pack: EvidencePack,
) -> None:
    if start_dt is None or end_dt is None:
        return
    t_start = pack.temporal_constraints.start_datetime
    t_end = pack.temporal_constraints.end_datetime
    # tzinfo 揃えて比較
    if start_dt.tzinfo is None or end_dt.tzinfo is None:
        return  # MISSING_TIMEZONE で別途拾うのでここではスキップ
    if start_dt < t_start or end_dt > t_end:
        issues.append(
            ValidationIssue(
                IssueKind.OUT_OF_TEMPORAL_RANGE,
                f"temporal 範囲外: item=[{start_dt}, {end_dt}], pack=[{t_start}, {t_end}]",
                idx,
            )
        )


def _check_opening_hours(
    issues: list[ValidationIssue],
    idx: int,
    item: LlmPlanItem,
    start_dt: datetime | None,
    places_by_id: dict[str, object],
) -> None:
    if item.item_type == "transit":
        return
    if not item.place_id or item.place_id not in places_by_id:
        return  # place_id unknown は別の issue で扱う
    if start_dt is None or start_dt.tzinfo is None:
        return  # timezone 未設定は別の issue で扱う

    from ..evidence.pack import PlacePoint

    place = places_by_id[item.place_id]
    assert isinstance(place, PlacePoint)
    day_of_week = start_dt.weekday()  # 月=0〜日=6

    # opening_hours が空 → 情報なし扱い、スキップ
    if not place.opening_hours:
        return
    # unknown_days に含まれる曜日もスキップ
    if day_of_week in place.opening_hours_unknown_days:
        return

    # この曜日の slot が 1 つもない = 定休日扱い → issue
    day_slots = [s for s in place.opening_hours if s.day_of_week == day_of_week]
    if not day_slots:
        issues.append(
            ValidationIssue(
                IssueKind.OUTSIDE_OPENING_HOURS,
                f"place_id={item.place_id} は曜日 {day_of_week}（0=月）は定休日",
                idx,
            )
        )
        return

    start_hhmm = start_dt.strftime("%H:%M")
    if not any(_hhmm_in_slot(start_hhmm, s) for s in day_slots):
        issues.append(
            ValidationIssue(
                IssueKind.OUTSIDE_OPENING_HOURS,
                f"place_id={item.place_id} の営業時間外: start={start_hhmm}, slots={[(s.open_hhmm, s.close_hhmm) for s in day_slots]}",
                idx,
            )
        )


def _hhmm_in_slot(hhmm: str, slot: OpeningHoursSlot) -> bool:
    return slot.open_hhmm <= hhmm <= slot.close_hhmm


def _check_item_type_category_consistency(
    issues: list[ValidationIssue],
    idx: int,
    item: LlmPlanItem,
    places_by_id: dict[str, object],
) -> None:
    """item_type と place.category の整合性を確認する（Codex Minor、Phase 1.10）。

    - meal slot に飲食 category を持たない place が割当てられたら mismatch issue
    - lodging slot に宿泊 category を持たない place が割当てられたら mismatch issue
    - activity / transit / 不明 place は permissive（check しない）
    - category 空（pack 構築側の情報欠損）は penalize しない
    """
    from ..evidence.pack import PlacePoint

    if item.item_type not in ("meal", "lodging"):
        return
    if not item.place_id or item.place_id not in places_by_id:
        return  # place_id 不明は別 issue で扱う
    place = places_by_id[item.place_id]
    assert isinstance(place, PlacePoint)
    if not place.category:
        return  # 情報なし、judgement 保留

    if item.item_type == "meal" and not _categories_indicate_meal(place.category):
        issues.append(
            ValidationIssue(
                IssueKind.ITEM_TYPE_CATEGORY_MISMATCH,
                f"meal item に飲食系 category を持たない place_id={item.place_id} "
                f"を割当て（category={place.category}）",
                idx,
            )
        )
    elif item.item_type == "lodging" and not _categories_indicate_lodging(place.category):
        issues.append(
            ValidationIssue(
                IssueKind.ITEM_TYPE_CATEGORY_MISMATCH,
                f"lodging item に宿泊系 category を持たない place_id={item.place_id} "
                f"を割当て（category={place.category}）",
                idx,
            )
        )


def _check_transit_details(
    issues: list[ValidationIssue],
    idx: int,
    item: LlmPlanItem,
    edges_by_key: dict[tuple[str, str], TransitEdge],
    start_dt: datetime | None,
    end_dt: datetime | None,
) -> None:
    if item.item_type != "transit" or item.transit_ref is None:
        return
    key = (item.transit_ref.from_place_id, item.transit_ref.to_place_id)
    edge = edges_by_key.get(key)
    if edge is None:
        issues.append(
            ValidationIssue(
                IssueKind.UNKNOWN_TRANSIT_EDGE,
                f"transit_ref={key} に対応する edge が transit_matrix に存在しない",
                idx,
            )
        )
        return

    # departure_time が candidate_departures に含まれる
    if item.transit_ref.departure_time not in edge.candidate_departures:
        issues.append(
            ValidationIssue(
                IssueKind.TRANSIT_DEPARTURE_MISMATCH,
                f"departure_time={item.transit_ref.departure_time} が candidate_departures={edge.candidate_departures} に含まれない",
                idx,
            )
        )

    # duration ±5 分
    if start_dt is not None and end_dt is not None and start_dt.tzinfo and end_dt.tzinfo:
        actual_min = int((end_dt - start_dt).total_seconds() // 60)
        if abs(actual_min - edge.duration_min) > DURATION_TOLERANCE_MIN:
            issues.append(
                ValidationIssue(
                    IssueKind.TRANSIT_DURATION_MISMATCH,
                    f"item の所要時間 {actual_min} 分が edge.duration_min={edge.duration_min} から ±{DURATION_TOLERANCE_MIN} 分を超える",
                    idx,
                )
            )

    # fare 整合
    if edge.fare_jpy is None:
        # edge.fare_jpy が null → item.cost_confidence は unknown 必須
        if item.cost_confidence != "unknown":
            issues.append(
                ValidationIssue(
                    IssueKind.TRANSIT_FARE_MISMATCH,
                    f"edge.fare_jpy が null のとき cost_confidence は 'unknown' にすること（got {item.cost_confidence}）",
                    idx,
                )
            )
    else:
        if item.cost_jpy != edge.fare_jpy:
            issues.append(
                ValidationIssue(
                    IssueKind.TRANSIT_FARE_MISMATCH,
                    f"item.cost_jpy={item.cost_jpy} が edge.fare_jpy={edge.fare_jpy} と一致しない",
                    idx,
                )
            )


def _check_overlapping_items(
    issues: list[ValidationIssue], items: list[LlmPlanItem]
) -> None:
    sorted_items = sorted(items, key=lambda i: i.order_index)
    for prev, curr in zip(sorted_items, sorted_items[1:]):
        prev_end = _parse_datetime(prev.end_time)
        curr_start = _parse_datetime(curr.start_time)
        if prev_end is None or curr_start is None:
            continue
        if prev_end > curr_start:
            issues.append(
                ValidationIssue(
                    IssueKind.OVERLAPPING_ITEMS,
                    f"items[{prev.order_index}].end_time > items[{curr.order_index}].start_time",
                    None,
                )
            )


def _check_budget(
    issues: list[ValidationIssue],
    items: list[LlmPlanItem],
    pack: EvidencePack,
) -> None:
    totals = {"activity": 0, "meal": 0, "transit": 0, "lodging": 0}
    for item in items:
        if item.cost_jpy is None:
            continue
        if item.item_type in totals:
            totals[item.item_type] += item.cost_jpy

    breakdown = pack.budget_constraints.breakdown_jpy
    limits = {
        "activity": breakdown.activity,
        "meal": breakdown.meal,
        "transit": breakdown.transit,
        "lodging": breakdown.lodging,
    }
    for category, total in totals.items():
        limit = limits[category]
        ceiling = int(limit * (1 + BUDGET_TOLERANCE_RATIO))
        if total > ceiling:
            issues.append(
                ValidationIssue(
                    IssueKind.BUDGET_EXCEEDED,
                    f"category={category} 合計 {total} 円 が 上限 {limit} 円（+{int(BUDGET_TOLERANCE_RATIO*100)}% 許容で {ceiling} 円）を超過",
                    None,
                )
            )


# ==============================
# Helpers
# ==============================


def _index_edges(
    transit_matrix: Iterable[TransitEdge],
) -> dict[tuple[str, str], TransitEdge]:
    """(from_place_id, to_place_id) → TransitEdge。mode が複数あっても最初のものを採用。"""
    idx: dict[tuple[str, str], TransitEdge] = {}
    for edge in transit_matrix:
        key = (edge.from_place_id, edge.to_place_id)
        if key not in idx:
            idx[key] = edge
    return idx


def _parse_datetime(value: str) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
