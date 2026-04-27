"""Structured Plan Assembly（LCaMO 論文応用、Phase 1.3e）。

LLM の `LlmGeneratedPlanV2`（slot 割当）を受け取って、数値（start_time / end_time /
transit_ref / cost_jpy / cost_confidence）をサーバ側で決定論的に埋め、v1 互換の
`LlmGeneratedPlan` を返す。

設計詳細: tasks/plans/2026-04-25-structured-plan-assembly.md
方針根拠（LCaMO 論文、石原・中村 2026）: tasks/lessons.md「2026-04-25 深夜」エントリ
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Iterator
from zoneinfo import ZoneInfo

from ..evidence.pack import EvidencePack, OpeningHoursSlot, PlacePoint, TransitEdge
from .schema import LlmGeneratedPlan, LlmGeneratedPlanV2, LlmPlanItem, LlmTransitRef

JST = ZoneInfo("Asia/Tokyo")

logger = logging.getLogger(__name__)


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


class IneligiblePlaceForSlotError(AssemblyError):
    """LLM が slot に割当てた place が opening_hours 不適合で、pack に eligible な代替も無い。
    Phase 1.3e (iv) hard self-healing 用。validator の OUTSIDE_OPENING_HOURS にマップされる。"""


class AnchorMissingError(AssemblyError):
    """anchor モードで指定 place_id が plan のどの item にも含まれない（Phase 2.1）。

    LLM が anchor 指示を無視 or assembler の self-healing で anchor が swap された
    case で発生。retry プロンプトに inject して LLM に anchor を入れ直してもらう。"""


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
    # case-insensitive fallback 用（Phase 1.3e run 7 救済、gpt-4o-mini が
    # 大文字小文字違いで place_id を出すケース対応）。
    # 曖昧一致（lower で複数 place_id が衝突）は誤 canonical 化リスクなので
    # ambiguous マークして救済から除外する（衝突 lower → None で記録）。
    places_by_id_lower: dict[str, PlacePoint | None] = {}
    for p in pack.places:
        key = p.place_id.lower()
        if key in places_by_id_lower:
            places_by_id_lower[key] = None  # ambiguous → 救済禁止
        else:
            places_by_id_lower[key] = p

    items: list[LlmPlanItem] = []
    order_index = 0
    start_date = pack.temporal_constraints.start_datetime.astimezone(JST).date()

    # Phase 2 polish (2026-04-27): slot 跨ぎ place_id 重複防止。
    # plan items に既に採用された place_id を追跡し、同 place を 2 度採用しない。
    # _find_eligible_alternate_for_slot / _find_alternate_place の exclude_place_ids
    # にこの set を渡すことで、代替選定でも used を再選しない。
    used_place_ids: set[str] = set()

    prev_entry: dict | None = None
    for slot_meta, place_id, rationale in ordered:
        if place_id not in places_by_id:
            # case-insensitive で **一意** に一致するなら canonical id に正規化（救済）。
            # ambiguous（lower で複数衝突）は誤 canonical 化リスクなので raise
            canonical = places_by_id_lower.get(place_id.lower())
            if canonical is not None:
                logger.warning(
                    "LLM produced case-mismatched place_id %r; resolved to canonical %r (slot=%s)",
                    place_id,
                    canonical.place_id,
                    slot_meta["slot_id"],
                )
                place_id = canonical.place_id
            else:
                # canonical is None: 厳密一致なし、かつ case-insensitive で 0 件 or ambiguous
                raise UnknownPlaceInSlotError(
                    f"LLM assigned unknown place_id {place_id!r} to slot {slot_meta['slot_id']!r}"
                )

        day_index = _day_index_from_slot_id(slot_meta["slot_id"])
        slot_date = start_date + timedelta(days=day_index - 1)
        place = places_by_id[place_id]
        prev_place_id_for_swap: str | None = (
            prev_entry["place"].place_id if prev_entry else None
        )

        # Phase 2 polish (A): slot 跨ぎ重複検出 + swap。
        # 既存の transit-failure swap path は from==target かつ self-edge 不在の場合のみ
        # 救うため、非隣接 slot（DAY1 と DAY2 の lunch 重複等）を取りこぼす。proactive に
        # 重複を検出し _find_eligible_alternate_for_slot で別 place に差し替える。
        if place_id in used_place_ids:
            alternate = _find_eligible_alternate_for_slot(
                pack=pack,
                target_place=place,
                slot_meta=slot_meta,
                slot_date=slot_date,
                prev_place_id=prev_place_id_for_swap,
                exclude_place_ids=used_place_ids,
            )
            if alternate is None:
                # fail-soft: 代替が見つからない場合は item を drop して継続（Risk 1）。
                # validator で「slot 欠損」は許容されるため retry を誘発しない。
                logger.error(
                    "Duplicate place_id %r in slot %r; no eligible alternate (used=%s); dropping item",
                    place_id, slot_meta["slot_id"], sorted(used_place_ids),
                )
                continue
            logger.warning(
                "Duplicate place_id %r in slot %r; swapped to %r",
                place_id, slot_meta["slot_id"], alternate.place_id,
            )
            place = alternate
            place_id = place.place_id

        # Phase 1.3e (iv) hard self-healing: LLM が opening_hours 不適合 place を
        # 選んだ場合、assembler が pack 内の eligible 代替に自動差し替え（同カテゴリ優先）。
        # eligible_for_slots を per-place で渡しているので LLM は本来この slot に充てるべき
        # でないが、soft hint を無視するケースを救済する（validator で OUTSIDE_OPENING_HOURS
        # を出して retry に頼るより自動修復が早い）。
        if not is_place_eligible_for_slot(
            place,
            slot_start_hhmm=slot_meta["start_hhmm"],
            slot_end_hhmm=slot_meta["end_hhmm"],
            date_=slot_date,
        ):
            alternate = _find_eligible_alternate_for_slot(
                pack=pack,
                target_place=place,
                slot_meta=slot_meta,
                slot_date=slot_date,
                prev_place_id=prev_place_id_for_swap,
                exclude_place_ids=used_place_ids,
            )
            if alternate is None:
                raise IneligiblePlaceForSlotError(
                    f"Place {place_id!r} is not eligible for slot {slot_meta['slot_id']!r} "
                    f"(opening_hours mismatch on {slot_date}); "
                    f"no eligible alternate place in pack"
                )
            logger.warning(
                "LLM picked ineligible place %r for slot %r; swapped to %r (category=%s)",
                place_id,
                slot_meta["slot_id"],
                alternate.place_id,
                alternate.category[0] if alternate.category else None,
            )
            place = alternate
            place_id = place.place_id

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
                # 代替選定: 同カテゴリ近接 + slot 適合 place に差し替え（設計書 §「代替選定ロジック」）
                alternate = _find_alternate_place(
                    pack=pack,
                    from_place_id=prev_place.place_id,
                    target_place=place,
                    slot_meta=slot_meta,
                    slot_date=slot_date,
                    exclude_place_ids=used_place_ids,
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
            # Codex Critical fix: post-shift で start_dt が place の opening close を
            # 超えるケースを assembler 側で raise する。validator が後段で catch する
            # 経路は retry ロジック上不安定（issue 単位で LLM 解釈が散漫になる）
            if not is_place_open_at_dt(place, start_dt):
                raise IneligiblePlaceForSlotError(
                    f"Place {place_id!r} closed at post-shift start "
                    f"{start_dt.strftime('%Y-%m-%d %H:%M')} (transit shift "
                    f"moved start past opening_hours close)"
                )
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
        used_place_ids.add(place_id)
        prev_entry = {"place": place, "end_dt": end_dt}

    # Phase 2 polish (A): 最終 invariant — defense-in-depth で重複が残ったら drop。
    # 上の proactive swap で網羅できているはずだが、想定外パスでの混入を log で可視化。
    items = _drop_duplicate_place_items(items)

    # Phase 2.1: anchor モード post-check（swap で anchor が落ちたケースも catch）
    _check_anchors_present(pack, items)

    return LlmGeneratedPlan(items=items)


def _drop_duplicate_place_items(items: list[LlmPlanItem]) -> list[LlmPlanItem]:
    """非 transit item の place_id が unique であることを保証する defense-in-depth。

    proactive duplicate-detection swap が想定外パスで漏らした場合のみ発動する。
    raise しない方針（Risk 1）: logger.error で記録し item を drop して fail-soft 継続。

    Codex review 2 Major 1: 単純に non-transit を drop すると transit_ref.from/to が
    drop された place_id を指して dangling になる。validator は edge 存在のみ見るので
    semantic 整合まで catch できない。よって 2 pass:
      1) 重複 non-transit を drop して `surviving_pids` を確定
      2) `transit_ref.from/to` のどちらかが surviving_pids に居ない transit も drop
    """
    # 1st pass: 重複 non-transit を識別、生き残る place_id 集合を確定
    surviving_pids: set[str] = set()
    keep_flags: list[bool] = []
    for it in items:
        if it.place_id is None:
            keep_flags.append(True)  # transit は 2nd pass で再判定
            continue
        if it.place_id in surviving_pids:
            keep_flags.append(False)
            logger.error(
                "Final invariant violation: duplicate place_id %r at order_index=%d; dropping item. "
                "This indicates a bug in proactive duplicate detection.",
                it.place_id, it.order_index,
            )
        else:
            surviving_pids.add(it.place_id)
            keep_flags.append(True)

    # 2nd pass: dangling transit (from/to が drop 先を指すもの) を除去
    deduped: list[LlmPlanItem] = []
    for keep, it in zip(keep_flags, items):
        if not keep:
            continue
        if it.transit_ref is not None:
            from_ok = it.transit_ref.from_place_id in surviving_pids
            to_ok = it.transit_ref.to_place_id in surviving_pids
            if not (from_ok and to_ok):
                logger.error(
                    "Dropping dangling transit item at order_index=%d "
                    "(from=%r to=%r): endpoint not in surviving place_ids",
                    it.order_index,
                    it.transit_ref.from_place_id,
                    it.transit_ref.to_place_id,
                )
                continue
        deduped.append(it)
    return deduped


def _check_anchors_present(pack: EvidencePack, items: list[LlmPlanItem]) -> None:
    """anchor モードで指定 place_id が全て plan items に含まれるか check。

    auto / theme モードでは何もしない。anchor モードで mode_payload が壊れている場合も
    fail-open（payload validate は API 入力層の責任）。
    """
    qc = pack.query_context
    if qc.start_mode != "anchor":
        return
    payload = qc.mode_payload
    if not isinstance(payload, dict):
        return
    raw_ids = payload.get("anchor_place_ids")
    if not isinstance(raw_ids, list) or not raw_ids:
        return
    anchor_ids = [pid for pid in raw_ids if isinstance(pid, str)]
    if not anchor_ids:
        return

    item_pids = {it.place_id for it in items if it.place_id is not None}
    missing = [pid for pid in anchor_ids if pid not in item_pids]
    if missing:
        raise AnchorMissingError(
            f"anchor mode: 指定 place_id が plan に含まれない: {missing}. "
            f"これらの id を必ずいずれかの slot に割当てよ"
        )


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


def is_place_open_at_dt(place: PlacePoint, dt: datetime) -> bool:
    """Place が指定 datetime に営業中か判定。validator の `_check_opening_hours` と
    完全整合（閉区間 `open <= hhmm <= close`）。

    transit shift 後の post-shift opening_hours check に使う（Codex Critical fix）。
    """
    dow = dt.weekday()
    if dow in place.opening_hours_unknown_days or not place.opening_hours:
        return True
    hhmm = dt.strftime("%H:%M")
    day_slots = [s for s in place.opening_hours if s.day_of_week == dow]
    if not day_slots:
        return False
    return any(s.open_hhmm <= hhmm <= s.close_hhmm for s in day_slots)


def is_place_eligible_for_slot(
    place: PlacePoint,
    *,
    slot_start_hhmm: str,
    slot_end_hhmm: str,
    date_: date,
) -> bool:
    """Place が指定 slot の時間帯 × 曜日に営業しているか判定（pure）。

    LLM プロンプトの per-place `eligible_for_slots` 構築用。
    `_fit_to_opening_hours` / validator (`_check_opening_hours`) と整合した判定:

    - opening_hours が空 → 検証スキップ → True 扱い（情報不足、reject しない）
    - opening_hours_unknown_days に当該曜日含む → 検証スキップ → True
    - 当該曜日に opening 枠が無い → 定休日 → False
    - 当該曜日 opening 枠と slot 時間帯に **半開区間で重なり > 0** → True
      （重なり = open_hhmm < slot_end_hhmm AND slot_start_hhmm < close_hhmm）
    """
    dow = date_.weekday()
    if dow in place.opening_hours_unknown_days or not place.opening_hours:
        return True
    day_slots = [s for s in place.opening_hours if s.day_of_week == dow]
    if not day_slots:
        return False  # 定休日
    return any(
        s.open_hhmm < slot_end_hhmm and slot_start_hhmm < s.close_hhmm
        for s in day_slots
    )


def compute_eligible_slot_ids_for_place(
    place: PlacePoint,
    *,
    slot_catalog: list[dict],
    base_date: date,
) -> list[str]:
    """Place に対して slot_catalog のうち eligible な slot_id 配列を返す。

    Phase 1.3e (iv) per-slot tailored places: LLM プロンプトに各 place の
    `eligible_for_slots` フィールドを付与するための補助。
    `slot_id` は `dayN_<key>` 形式で N から日付オフセットを計算し
    `is_place_eligible_for_slot` で判定する。
    """
    eligible: list[str] = []
    for c in slot_catalog:
        day_index = _day_index_from_slot_id(c["slot_id"])
        slot_date = base_date + timedelta(days=day_index - 1)
        if is_place_eligible_for_slot(
            place,
            slot_start_hhmm=c["start_hhmm"],
            slot_end_hhmm=c["end_hhmm"],
            date_=slot_date,
        ):
            eligible.append(c["slot_id"])
    return eligible


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


def _find_eligible_alternate_for_slot(
    *,
    pack: EvidencePack,
    target_place: PlacePoint,
    slot_meta: dict,
    slot_date: date,
    prev_place_id: str | None = None,
    exclude_place_ids: set[str] | None = None,
) -> PlacePoint | None:
    """Phase 1.3e (iv) hard self-healing 用: opening_hours 不適合 place の代替選定。

    優先順位:
      1. 同 `category[0]` を持ち、かつ slot に eligible + (prev から transit 到達可能) な place のうち rating 最高
      2. category 共通集合 + 上記同条件のうち rating 最高
      3. 任意の上記同条件 place のうち rating 最高
      4. 見つからなければ None
    target_place 自身は常に除外。

    Codex Major fix: `prev_place_id` が渡された場合、transit 到達可能性も必須条件に。
    これがないと「opening は OK だが transit 不能」の代替を選んで後段で
    `NoFeasibleTransitError` を引き起こすケースがあった。最初の slot
    （prev_entry None）では `prev_place_id=None` で transit check をスキップ。

    Phase 2 polish (A) Major 1: `exclude_place_ids` で別 slot で既に採用された place を
    除外できる。重複防止の中核。
    """
    reachable_ids: set[str] | None = None
    if prev_place_id is not None:
        reachable_ids = {
            e.to_place_id
            for e in pack.transit_matrix
            if e.from_place_id == prev_place_id
        }
    excluded = exclude_place_ids or set()
    candidates: list[PlacePoint] = []
    for p in pack.places:
        if p.place_id == target_place.place_id:
            continue
        if p.place_id in excluded:
            continue
        if reachable_ids is not None and p.place_id not in reachable_ids:
            continue
        if not is_place_eligible_for_slot(
            p,
            slot_start_hhmm=slot_meta["start_hhmm"],
            slot_end_hhmm=slot_meta["end_hhmm"],
            date_=slot_date,
        ):
            continue
        candidates.append(p)
    if not candidates:
        return None

    target_primary = target_place.category[0] if target_place.category else None
    target_categories = set(target_place.category)

    def _sort_key(p: PlacePoint) -> tuple[int, float]:
        # rating tie 安定化のため id 辞書順含めるが、Tuple 比較で rating 降順を優先
        rating = p.rating if p.rating is not None else 0.0
        return (-rating, 0)  # 降順

    # tier 1: 同 category[0]
    tier1 = [
        p for p in candidates
        if p.category and target_primary is not None and p.category[0] == target_primary
    ]
    if tier1:
        return min(tier1, key=lambda p: (-(p.rating or 0.0), p.place_id))
    # tier 2: category 共通集合
    tier2 = [p for p in candidates if set(p.category) & target_categories]
    if tier2:
        return min(tier2, key=lambda p: (-(p.rating or 0.0), p.place_id))
    # tier 3: 任意 eligible
    return min(candidates, key=lambda p: (-(p.rating or 0.0), p.place_id))


def _find_alternate_place(
    *,
    pack: EvidencePack,
    from_place_id: str,
    target_place: PlacePoint,
    slot_meta: dict,
    slot_date: date,
    exclude_place_ids: set[str] | None = None,
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

    Phase 2 polish (A) Major 1: `exclude_place_ids` で別 slot で既に採用された place を
    除外できる。重複防止の中核。
    """
    target_categories = set(target_place.category)
    reachable_ids = {
        e.to_place_id for e in pack.transit_matrix if e.from_place_id == from_place_id
    }
    excluded = exclude_place_ids or set()
    candidates: list[PlacePoint] = []
    for p in pack.places:
        if p.place_id == target_place.place_id:
            continue
        if p.place_id == from_place_id:
            # 自己ループ防止（slot[i-1] と同じ place へ戻る移動を作らない）
            continue
        if p.place_id in excluded:
            continue
        if p.place_id not in reachable_ids:
            continue
        if target_categories and not target_categories.intersection(p.category):
            continue
        # Phase 1.3e bug fix (run 22 で発見): transit 代替も slot の opening_hours
        # に適合している必要がある。これが抜けていたため transit edge 不在で同
        # category の月曜定休 place 等が選ばれ、validator で OUTSIDE_OPENING_HOURS
        # を catch されるケースが残っていた
        if not is_place_eligible_for_slot(
            p,
            slot_start_hhmm=slot_meta["start_hhmm"],
            slot_end_hhmm=slot_meta["end_hhmm"],
            date_=slot_date,
        ):
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

    規則（Codex Major fix 後）:
      1. start_dt の HH:mm（JST）**以降** で **最早** の候補を返す
      2. 全候補が start_dt より前なら `NoFeasibleTransitError` を raise（「過去の電車に乗る」
         意味的に誤った plan を出さないため。validator は順序を見ないので assembler 側で
         弾く）。retry に伝わって LLM が別 slot 配分を出す経路で解消する想定
      3. 空リストは `ClientTransitEdge.min_length=1` で禁止なので到達しない
    """
    start_hhmm = start_dt.astimezone(JST).strftime("%H:%M")
    candidates = edge.candidate_departures
    eligible = [d for d in candidates if d >= start_hhmm]
    if eligible:
        return min(eligible)
    raise NoFeasibleTransitError(
        f"All candidate_departures of edge "
        f"{edge.from_place_id!r}->{edge.to_place_id!r} are before "
        f"required start_hhmm={start_hhmm!r}; "
        f"candidates={candidates}"
    )


def _compose_title(item_type: str, place: PlacePoint) -> str:
    if item_type == "meal":
        return f"{place.name} で食事"
    if item_type == "lodging":
        return f"{place.name} に宿泊"
    return place.name
