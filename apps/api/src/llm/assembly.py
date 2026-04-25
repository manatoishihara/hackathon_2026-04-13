"""Structured Plan Assembly（LCaMO 論文応用、Phase 1.3e）。

LLM の `LlmGeneratedPlanV2`（slot 割当）を受け取って、数値（start_time / end_time /
transit_ref / cost_jpy / cost_confidence）をサーバ側で決定論的に埋め、v1 互換の
`LlmGeneratedPlan` を返す。

設計詳細: tasks/plans/2026-04-25-structured-plan-assembly.md
方針根拠（LCaMO 論文、石原・中村 2026）: tasks/lessons.md「2026-04-25 深夜」エントリ
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Iterator
from zoneinfo import ZoneInfo

from ..evidence.pack import EvidencePack, OpeningHoursSlot, PlacePoint, TransitEdge
from .schema import LlmGeneratedPlan, LlmGeneratedPlanV2, LlmPlanItem, LlmTransitRef

JST = ZoneInfo("Asia/Tokyo")


# ==============================
# Slot カタログ（固定テンプレ、日数分繰り返して展開）
# ==============================


@dataclass(frozen=True)
class SlotTemplate:
    key_suffix: str  # "morning" / "lunch" など（slot_id は "day{N}_{suffix}" で構成）
    start_hhmm: str  # "HH:MM"（JST）
    end_hhmm: str    # "HH:MM"（JST、日跨ぎ lodging は特別処理）
    item_type: str   # "activity" | "meal" | "lodging"
    crosses_midnight: bool = False


# 1 日分のテンプレ（day_index は assembler が展開する）。
# lodging は翌日 08:30 までと想定するが、実装上は当日 23:00 までに揃え、翌日の朝食はスキップ。
DAILY_SLOT_TEMPLATES: tuple[SlotTemplate, ...] = (
    SlotTemplate("morning", "09:00", "11:30", "activity"),
    SlotTemplate("lunch", "12:00", "13:30", "meal"),
    SlotTemplate("afternoon", "14:00", "16:30", "activity"),
    SlotTemplate("dinner", "18:00", "19:30", "meal"),
    SlotTemplate("lodging", "20:00", "22:00", "lodging"),  # 実運用は宿泊そのもの、end は入室〆
)


def generate_slot_catalog(total_days: int) -> list[dict]:
    """日数に応じた slot_id カタログ。LLM プロンプト表示 + assembler の期待キー集合の正典。

    最終日は lodging を出さない（その日は自宅へ戻る想定）。
    """
    catalog: list[dict] = []
    for d in range(1, total_days + 1):
        for tmpl in DAILY_SLOT_TEMPLATES:
            if d == total_days and tmpl.key_suffix == "lodging":
                continue
            catalog.append(
                {
                    "slot_id": f"day{d}_{tmpl.key_suffix}",
                    "start_hhmm": tmpl.start_hhmm,
                    "end_hhmm": tmpl.end_hhmm,
                    "item_type": tmpl.item_type,
                }
            )
    return catalog


# ==============================
# price_level → jpy マップ（介入カタログ、設計書準拠）
# ==============================


_PRICE_MAP: dict[str, dict[int | None, tuple[int, str]]] = {
    # item_type: { price_level or None: (jpy, confidence) }
    "meal": {
        1: (1500, "estimated"),
        2: (2500, "estimated"),
        3: (4500, "estimated"),
        4: (8000, "estimated"),
        None: (2500, "unknown"),
    },
    "activity": {
        1: (1000, "estimated"),
        2: (2000, "estimated"),
        3: (3500, "estimated"),
        4: (6000, "estimated"),
        None: (1500, "unknown"),
    },
    "lodging": {
        1: (8000, "estimated"),
        2: (14000, "estimated"),
        3: (22000, "estimated"),
        4: (35000, "estimated"),
        None: (15000, "unknown"),
    },
}


def _resolve_cost(item_type: str, price_level: int | None) -> tuple[int, str]:
    mapping = _PRICE_MAP[item_type]
    return mapping.get(price_level, mapping[None])


# ==============================
# エラー型
# ==============================


class AssemblyError(Exception):
    """LLM 出力から決定論で組み立てる過程で、致命的な不整合が検出された。"""


class UnknownSlotIdError(AssemblyError):
    """LLM が返した slot_id が catalog に存在しない。"""


class UnknownPlaceInSlotError(AssemblyError):
    """LLM が slot に割当てた place_id が pack.places に存在しない（LCaMO の `HARD_BLOCK` 相当）。"""


class NoFeasibleTransitError(AssemblyError):
    """2 slot 間の transit を transit_matrix から取得できず、代替選定も尽きた。"""


# ==============================
# 本体: assemble
# ==============================


def assemble_plan(
    plan_v2: LlmGeneratedPlanV2, pack: EvidencePack
) -> LlmGeneratedPlan:
    """v2 出力から v1 互換 `LlmGeneratedPlan` を組み立てる。

    アルゴリズム:
      1. slot_catalog と突合して順序正規化、未知 slot_id は raise
      2. 各 slot の place_id を pack.places から lookup（未存在は raise）
      3. opening_hours で時刻調整（slot template の範囲内に収める）
      4. slot[i-1] → slot[i] の transit edge を transit_matrix から lookup、
         なければ代替 place に差し替え
      5. cost_jpy / cost_confidence を決定
      6. LlmPlanItem を構築し order_index を順に付ける
    """
    if not plan_v2.slots:
        return LlmGeneratedPlan(items=[])

    catalog = generate_slot_catalog(pack.temporal_constraints.total_days)
    catalog_by_id = {c["slot_id"]: c for c in catalog}

    # LLM 出力を slot カタログ順にソート（LLM が勝手な順で返してきても救う）
    ordered: list[tuple[dict, str, str]] = []
    for sa in plan_v2.slots:
        if sa.slot_id not in catalog_by_id:
            raise UnknownSlotIdError(
                f"LLM returned unknown slot_id: {sa.slot_id!r}. "
                f"Allowed: {sorted(catalog_by_id.keys())}"
            )
        ordered.append((catalog_by_id[sa.slot_id], sa.place_id, sa.rationale))
    ordered.sort(key=lambda t: _slot_order_key(t[0]["slot_id"]))

    places_by_id = {p.place_id: p for p in pack.places}

    items: list[LlmPlanItem] = []
    order_index = 0
    start_date = pack.temporal_constraints.start_datetime.astimezone(JST).date()

    prev_entry: dict | None = None
    for slot_meta, place_id, rationale in ordered:
        if place_id not in places_by_id:
            raise UnknownPlaceInSlotError(
                f"LLM assigned unknown place_id {place_id!r} to slot {slot_meta['slot_id']!r}"
            )

        day_index = _day_index_from_slot_id(slot_meta["slot_id"])
        slot_date = start_date + timedelta(days=day_index - 1)
        place = places_by_id[place_id]

        # opening_hours に収まる範囲に時刻を調整（不適合は slot 時間帯に収められなければ skip せず強行、
        # validator で拾う。将来は代替 place 選定に回す）
        start_dt, end_dt = _fit_to_opening_hours(
            date_=slot_date,
            slot_start=slot_meta["start_hhmm"],
            slot_end=slot_meta["end_hhmm"],
            place=place,
        )

        # transit を前置（必要なら）
        if prev_entry is not None:
            prev_place: PlacePoint = prev_entry["place"]
            prev_end_dt: datetime = prev_entry["end_dt"]
            edge = _lookup_transit_edge(prev_place.place_id, place_id, pack.transit_matrix)
            if edge is None:
                # 代替選定: 同カテゴリ近接 place に差し替え（設計書 §「代替選定ロジック」）
                alternate = _find_alternate_place(
                    pack=pack,
                    from_place_id=prev_place.place_id,
                    target_place=place,
                )
                if alternate is None:
                    raise NoFeasibleTransitError(
                        f"No transit edge from {prev_place.place_id!r} to "
                        f"{place_id!r} and no alternate place for category "
                        f"{place.category[0] if place.category else None!r} found"
                    )
                # 差し替え先の place / place_id / opening_hours 合わせの時刻を再計算
                place = alternate
                place_id = place.place_id
                start_dt, end_dt = _fit_to_opening_hours(
                    date_=slot_date,
                    slot_start=slot_meta["start_hhmm"],
                    slot_end=slot_meta["end_hhmm"],
                    place=place,
                )
                edge = _lookup_transit_edge(
                    prev_place.place_id, place_id, pack.transit_matrix
                )
                assert edge is not None, "alternate selection invariant broken"
            transit_start = prev_end_dt
            transit_end = transit_start + timedelta(minutes=edge.duration_min)
            # activity 開始を transit 到着に合わせて繰り下げ
            if transit_end > start_dt:
                shift = transit_end - start_dt
                start_dt = transit_end
                end_dt = end_dt + shift
            items.append(
                _build_transit_item(
                    order_index=order_index,
                    edge=edge,
                    start_dt=transit_start,
                    end_dt=transit_end,
                )
            )
            order_index += 1

        cost_jpy, cost_conf = _resolve_cost(slot_meta["item_type"], place.price_level)
        items.append(
            LlmPlanItem(
                order_index=order_index,
                item_type=slot_meta["item_type"],  # type: ignore[arg-type]
                title=_compose_title(slot_meta["item_type"], place),
                description=rationale,
                start_time=start_dt.isoformat(),
                end_time=end_dt.isoformat(),
                place_id=place_id,
                cost_jpy=cost_jpy,
                cost_confidence=cost_conf,  # type: ignore[arg-type]
                transit_ref=None,
            )
        )
        order_index += 1
        prev_entry = {"place": place, "end_dt": end_dt}

    return LlmGeneratedPlan(items=items)


# ==============================
# 内部ヘルパ
# ==============================


def _slot_order_key(slot_id: str) -> tuple[int, int]:
    """slot_id を (day_index, template_order) にパースして昇順キーにする。"""
    day_index = _day_index_from_slot_id(slot_id)
    suffix = slot_id.split("_", 1)[1] if "_" in slot_id else ""
    template_order = {t.key_suffix: i for i, t in enumerate(DAILY_SLOT_TEMPLATES)}
    return (day_index, template_order.get(suffix, 999))


def _day_index_from_slot_id(slot_id: str) -> int:
    """`day3_morning` → 3。パース不能なら 1 を返す（assembler が致命視する前提）。"""
    head = slot_id.split("_", 1)[0]
    if head.startswith("day"):
        try:
            return int(head[3:])
        except ValueError:
            return 1
    return 1


def _fit_to_opening_hours(
    *,
    date_: date,
    slot_start: str,
    slot_end: str,
    place: PlacePoint,
) -> tuple[datetime, datetime]:
    """slot の時間帯を place.opening_hours に照合し、収まる時刻を返す。

    不適合の場合は slot の start/end をそのまま返す（validator に任せる）。将来は
    代替 place 選定をトリガーする。opening_hours が空 or unknown_days は slot のまま返す。
    """
    slot_start_dt = _to_aware_dt(date_, slot_start)
    slot_end_dt = _to_aware_dt(date_, slot_end)

    dow = date_.weekday()  # Mon=0..Sun=6
    if dow in place.opening_hours_unknown_days or not place.opening_hours:
        return slot_start_dt, slot_end_dt

    day_slots = [s for s in place.opening_hours if s.day_of_week == dow]
    if not day_slots:
        # その曜日が定休 → slot のまま返し、validator で弾かせる
        return slot_start_dt, slot_end_dt

    # slot と重なる営業時間枠を探す。複数枠があれば重なり最長のものを採用
    best: tuple[datetime, datetime] | None = None
    best_overlap = timedelta(0)
    for s in day_slots:
        open_dt = _to_aware_dt(date_, s.open_hhmm)
        close_dt = _to_aware_dt(date_, s.close_hhmm)
        overlap_start = max(slot_start_dt, open_dt)
        overlap_end = min(slot_end_dt, close_dt)
        overlap = overlap_end - overlap_start
        if overlap > best_overlap:
            best_overlap = overlap
            best = (overlap_start, overlap_end)

    if best and best_overlap > timedelta(0):
        # 1 秒でも重なれば opening_hours 内に寄せる（validator の
        # OUTSIDE_OPENING_HOURS が厳密一致なので、重なり尺度でサボると reject される）
        return best
    # 全く重ならないケースのみ slot のまま返す（validator で弾かせ、retry 経路へ）
    return slot_start_dt, slot_end_dt


def _to_aware_dt(date_: date, hhmm: str) -> datetime:
    hour, minute = (int(x) for x in hhmm.split(":"))
    return datetime.combine(date_, time(hour=hour, minute=minute), tzinfo=JST)


def _lookup_transit_edge(
    from_id: str, to_id: str, matrix: list[TransitEdge]
) -> TransitEdge | None:
    for edge in matrix:
        if edge.from_place_id == from_id and edge.to_place_id == to_id:
            return edge
    return None


def _find_alternate_place(
    *,
    pack: EvidencePack,
    from_place_id: str,
    target_place: PlacePoint,
) -> PlacePoint | None:
    """transit 不成立時の代替 place 選定（設計書 §「代替選定ロジック」step 1-2）。

    方針（2026-04-25 夜、第 2 弾で category マッチを緩和）:
      1. 候補条件: (a) `from_place_id` から `transit_matrix` に edge が存在し、
         (b) `target_place.category` と **1 つでも共通する category を持つ**、
         (c) target_place 自体を除く、(d) `from_place_id` との自己ループは避ける
      2. (a)+(b)+(c)+(d) を満たすうち rating 最高のものを採用（tie は place_id 辞書順で安定化）
      3. 見つからなければ None（呼び出し元が `NoFeasibleTransitError` を raise して retry 委譲）

    Google Places の category は `[specific, ..., generic]` のリストなので、`category[0]`
    厳密一致だと `yakiniku_restaurant` のような細粒度ラベルで候補枯渇しやすい。共通集合
    判定に緩めることで `restaurant` / `food` 等の generic ラベルを介したマッチが成立する。

    **連鎖探索（前段 place も差し替える step 3）は最小実装では未採用**。LLM retry 経路で
    解消する方が副作用が少ないと判断（Phase 1.3e スコープメモ）。
    """
    target_categories = set(target_place.category)
    reachable_ids = {
        e.to_place_id for e in pack.transit_matrix if e.from_place_id == from_place_id
    }
    candidates: list[PlacePoint] = []
    for p in pack.places:
        if p.place_id == target_place.place_id:
            continue
        if p.place_id == from_place_id:
            # 自己ループ防止（slot[i-1] と同じ place へ戻る移動を作らない）
            continue
        if p.place_id not in reachable_ids:
            continue
        if target_categories and not target_categories.intersection(p.category):
            continue
        candidates.append(p)
    if not candidates:
        return None
    # rating 降順 → place_id 昇順（tie breaker、tests の安定性）
    candidates.sort(key=lambda p: (-(p.rating or 0.0), p.place_id))
    return candidates[0]


def _build_transit_item(
    *,
    order_index: int,
    edge: TransitEdge,
    start_dt: datetime,
    end_dt: datetime,
) -> LlmPlanItem:
    """transit item を組み立てる。

    **重要**: `transit_ref.departure_time` は `edge.candidate_departures` のいずれかに
    厳密一致する必要がある（validator `TRANSIT_DEPARTURE_MISMATCH` 検知）。
    prev_end_dt が合致しない時刻でも、candidate から採択する。
    """
    cost = edge.fare_jpy
    departure_hhmm = _pick_departure_time(edge, start_dt)
    return LlmPlanItem(
        order_index=order_index,
        item_type="transit",
        title=f"{edge.route_summary} で移動",
        description=f"{edge.duration_min} 分、{edge.mode}",
        start_time=start_dt.isoformat(),
        end_time=end_dt.isoformat(),
        place_id=None,
        cost_jpy=cost,
        cost_confidence="verified" if cost is not None else "unknown",
        transit_ref=LlmTransitRef(
            from_place_id=edge.from_place_id,
            to_place_id=edge.to_place_id,
            departure_time=departure_hhmm,
        ),
    )


def _pick_departure_time(edge: TransitEdge, start_dt: datetime) -> str:
    """`edge.candidate_departures` から最適な出発時刻を選ぶ。

    規則:
      1. start_dt の HH:mm（JST）**以降** で **最早** の候補を優先
      2. 全候補が start_dt より前なら **最遅** の候補を採択
         （「過去の出発時刻で乗る」は validator 的に OK だが、現実の運行には乗れない点は別問題）
      3. 空リストは ClientTransitEdge の min_length=1 で禁止なので到達しない
    """
    start_hhmm = start_dt.astimezone(JST).strftime("%H:%M")
    candidates = edge.candidate_departures
    eligible = [d for d in candidates if d >= start_hhmm]
    if eligible:
        return min(eligible)
    return max(candidates)


def _compose_title(item_type: str, place: PlacePoint) -> str:
    if item_type == "meal":
        return f"{place.name} で食事"
    if item_type == "lodging":
        return f"{place.name} に宿泊"
    return place.name
