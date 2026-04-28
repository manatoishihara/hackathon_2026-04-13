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
from difflib import SequenceMatcher
from typing import Iterator
from zoneinfo import ZoneInfo

from ..evidence.pack import EvidencePack, OpeningHoursSlot, PlacePoint, TransitEdge
from .schema import LlmGeneratedPlan, LlmGeneratedPlanV2, LlmPlanItem, LlmTransitRef
from .validator import _categories_indicate_lodging, _categories_indicate_meal

JST = ZoneInfo("Asia/Tokyo")

logger = logging.getLogger(__name__)


# Phase 2 polish v4 (2026-04-28、本番 Run 13d 失敗を受けて):
# gpt-4.1 が `ChIJ` を `ChIJJ` のような短縮/prefix duplication で出力するハルシ
# (本番 Run 13d で 3 attempts 連続観測) を救済するための fuzzy match safety net。
#
# 動作: SequenceMatcher.ratio() ≥ FUZZY_MATCH_RATIO かつ長さ差 ≤ FUZZY_MAX_LEN_DIFF
# かつ pack 内で **唯一** マッチする place_id だけを採用 (false positive を厳しく排除)。
# 複数候補が同条件で hit するなら救済せず raise (誤 canonical 化リスク回避)。
FUZZY_MATCH_RATIO = 0.95
FUZZY_MAX_LEN_DIFF = 2


def _resolve_fuzzy_place_id(
    llm_id: str, places_by_id: dict[str, PlacePoint]
) -> str | None:
    """LLM が出した近似 place_id を pack 内 ID に救済する。

    pack の place_id 集合と LLM 出力を比較し:
    - 長さ差 ≤ FUZZY_MAX_LEN_DIFF
    - SequenceMatcher.ratio() ≥ FUZZY_MATCH_RATIO
    のうち **唯一** マッチするものを返す。0 件 or 複数なら None。

    Phase 2 polish v5 (Codex review 1 Minor 1 reverse): 旧 `ChIJ` prefix guard を削除。
    本番 Run 13e で gpt-4.1 が `ChIJ` を `ChIH` / `ChIh` (J→H or J→h typo) に間違える
    最頻ハルシパターンが guard で逆に救済対象外になっていた事故の対処。
    false positive 抑制は unique-match + ratio 0.95 + len_diff ≤ 2 で十分。

    例:
    - "ChIJJE69IgAHnHWARDJVsAgxtjCQ" (LLM、J 余分) → "ChIJE69IgAHnHWARDJVsAgxtjCQ" (pack)
    - "ChIHhY2RO4XnHWAReFs51v9XU3A" (LLM、J→H typo) → "ChIJhY2RO4XnHWAReFs51v9XU3A" (pack)
    - "ChIhY2RO4XnHWAReFs51v9XU3A" (LLM、J→h lowercase) → "ChIJhY2RO4XnHWAReFs51v9XU3A" (pack)
    """
    matches: list[str] = []
    for pid in places_by_id:
        if abs(len(pid) - len(llm_id)) > FUZZY_MAX_LEN_DIFF:
            continue
        ratio = SequenceMatcher(None, llm_id, pid).ratio()
        if ratio >= FUZZY_MATCH_RATIO:
            matches.append(pid)
    if len(matches) == 1:
        return matches[0]
    return None


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


def _resolve_cost_with_rakuten_override(
    item_type: str,
    place: PlacePoint,
    pack: EvidencePack,
) -> tuple[int, str]:
    """cost 決定 logic に楽天 lodging の verified 経路を追加 (Phase 3 polish 案 D 第 6 段、2026-04-28)。

    楽天 lodging (place_id が `rakuten_` prefix) は API で実価格を取得済なので、
    `_PRICE_MAP` の estimated 値で上書きせず、`pack.lodging_options` から
    `price_jpy_per_night` を直接引いて cost_confidence="verified" にする。

    対象外 (Google Places の lodging / meal / activity / 楽天マッチしない place_id):
        従来通り `_resolve_cost` で `_PRICE_MAP[item_type][price_level]` 経由。
    """
    if (
        item_type == "lodging"
        and place.place_id.startswith("rakuten_")
        and pack.lodging_options
    ):
        for lo in pack.lodging_options:
            if lo.place_id == place.place_id:
                return (lo.price_jpy_per_night, "verified")
    return _resolve_cost(item_type, place.price_level)


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
                # Phase 2 polish v4: case-insensitive miss 後の最後の救済手段として
                # SequenceMatcher.ratio() による fuzzy match を試す。本番 Run 13d で
                # gpt-4.1 が "ChIJJE69I..." (頭 J 余分) と systematic ハルシしたケースを救済。
                fuzzy_canonical = _resolve_fuzzy_place_id(place_id, places_by_id)
                if fuzzy_canonical is not None:
                    logger.warning(
                        "LLM produced fuzzy-matched place_id %r; resolved to canonical %r (slot=%s)",
                        place_id,
                        fuzzy_canonical,
                        slot_meta["slot_id"],
                    )
                    place_id = fuzzy_canonical
                else:
                    # 厳密一致なし、case-insensitive で 0 件 or ambiguous、fuzzy も unique 化失敗
                    raise UnknownPlaceInSlotError(
                        f"LLM assigned unknown place_id {place_id!r} to slot {slot_meta['slot_id']!r}"
                    )

        day_index = _day_index_from_slot_id(slot_meta["slot_id"])
        slot_date = start_date + timedelta(days=day_index - 1)
        place = places_by_id[place_id]
        prev_place_id_for_swap: str | None = (
            prev_entry["place"].place_id if prev_entry else None
        )

        # Phase 2 polish v6 (2026-04-28、本番 Run 13e で `item_type_category_mismatch` が
        # 支配 issue となった対策): LLM が meal slot に park、lodging slot に restaurant 等を
        # 割当てた場合、assembler が事前に検出して swap 試行する。validator が後段で catch
        # する経路 (4 attempts retry) より自動修復が早い。
        if not _is_item_type_compatible(slot_meta["item_type"], place.category):
            alternate = _find_eligible_alternate_for_slot(
                pack=pack,
                target_place=place,
                slot_meta=slot_meta,
                slot_date=slot_date,
                prev_place_id=prev_place_id_for_swap,
                exclude_place_ids=used_place_ids,
            )
            if alternate is not None and _is_item_type_compatible(
                slot_meta["item_type"], alternate.category
            ):
                logger.warning(
                    "LLM picked item_type-mismatched place %r (category=%s) for slot %r (item_type=%s); "
                    "swapped to %r (category=%s)",
                    place_id, place.category, slot_meta["slot_id"], slot_meta["item_type"],
                    alternate.place_id, alternate.category,
                )
                place = alternate
                place_id = place.place_id
            else:
                # Phase 2 polish v6.2 (2026-04-28、本番で alternate 候補不足 → tier3 filtered
                # out で accept されて validator の item_type_category_mismatch 連発が支配
                # issue となった対策):
                # alternate が item_type 適合な未使用 place で見つからないとき、
                # **used 集合内** で item_type compatible な place を探して **再使用** する。
                # lodging 連泊と同じく meal/activity も「枯渇時は重複許容で item_type 守る」
                # 設計。validator は重複自体を issue とせず通すので 422 を防げる。
                reused = _find_item_type_compatible_used_place(
                    pack=pack,
                    used_place_ids=used_place_ids,
                    item_type=slot_meta["item_type"],
                    slot_meta=slot_meta,
                    slot_date=slot_date,
                    prev_place_id=prev_place_id_for_swap,
                )
                if reused is not None:
                    logger.warning(
                        "LLM picked item_type-mismatched place %r (category=%s) for slot %r (item_type=%s); "
                        "no fresh alternate, reusing already-used %r (category=%s) to keep item_type integrity",
                        place_id, place.category, slot_meta["slot_id"], slot_meta["item_type"],
                        reused.place_id, reused.category,
                    )
                    place = reused
                    place_id = place.place_id
                else:
                    # 完全に詰む (used 集合にも item_type compatible なし) → warn + accept、
                    # validator catch で retry guidance に流す
                    logger.warning(
                        "LLM picked item_type-mismatched place %r (category=%s) for slot %r (item_type=%s); "
                        "no compatible alternate or reusable, accepting (validator will catch)",
                        place_id, place.category, slot_meta["slot_id"], slot_meta["item_type"],
                    )

        # Phase 2 polish v5 (2026-04-28、user 「重複は best-effort、エラー回避優先」):
        # lodging slot は連泊許容のため重複検出から除外。meal/activity slot は重複検出
        # するが、swap 失敗時は raise/drop ではなく **warn + accept** で続行する
        # (Codex review 1 で plan 確定、本番 Run 13e で対症療法の限界が露呈)。
        if place_id in used_place_ids and slot_meta["item_type"] != "lodging":
            alternate = _find_eligible_alternate_for_slot(
                pack=pack,
                target_place=place,
                slot_meta=slot_meta,
                slot_date=slot_date,
                prev_place_id=prev_place_id_for_swap,
                exclude_place_ids=used_place_ids,
            )
            if alternate is not None:
                logger.warning(
                    "Duplicate place_id %r in slot %r; swapped to %r",
                    place_id, slot_meta["slot_id"], alternate.place_id,
                )
                place = alternate
                place_id = place.place_id
            else:
                # 旧設計: drop item (or raise)。新設計 (v5): warn + accept で続行。
                # 重複は意図された feature (multi-day plan で候補枯渇時の妥協)、validator も
                # 重複自体を issue とせず通す。
                logger.warning(
                    "Duplicate place_id %r in slot %r (item_type=%s); no alternate, "
                    "accepting duplicate (best-effort policy)",
                    place_id, slot_meta["slot_id"], slot_meta["item_type"],
                )

        # Phase 1.3e (iv) hard self-healing: LLM が opening_hours 不適合 place を
        # 選んだ場合、assembler が pack 内の eligible 代替に自動差し替え（同カテゴリ優先）。
        # Phase 2 polish v5: swap 失敗時は raise せず warn + accept で続行
        # (validator が後段で OUTSIDE_OPENING_HOURS を catch して retry guidance に流す)。
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
            if alternate is not None:
                logger.warning(
                    "LLM picked ineligible place %r for slot %r; swapped to %r (category=%s)",
                    place_id,
                    slot_meta["slot_id"],
                    alternate.place_id,
                    alternate.category[0] if alternate.category else None,
                )
                place = alternate
                place_id = place.place_id
            else:
                # Phase 3 polish 案 3 (2026-04-28): opening_hours 軸の reuse fallback。
                # v6.2 で item_type 軸の reuse fallback を追加して `item_type_category_mismatch`
                # を吸収できたが、`outside_opening_hours` 軸は同じ仕組みで救済されていなかった。
                # 本番 Run で water 曜定休 等の date 依存 mismatch が candidate=1 まで縮退し、
                # validator catch → 4 attempts 尽きて 422 連発。`_find_item_type_compatible_used_place`
                # は item_type 適合 + opening_hours 適合 の両方を filter するので opening_hours
                # 軸の救済にもそのまま使える (関数内で is_place_eligible_for_slot を呼んでいる)。
                reused = _find_item_type_compatible_used_place(
                    pack=pack,
                    used_place_ids=used_place_ids,
                    item_type=slot_meta["item_type"],
                    slot_meta=slot_meta,
                    slot_date=slot_date,
                    prev_place_id=prev_place_id_for_swap,
                )
                if reused is not None:
                    logger.warning(
                        "Place %r ineligible for slot %r (opening_hours mismatch on %s); "
                        "no fresh alternate, reusing already-used %r (category=%s) to keep slot filled",
                        place_id, slot_meta["slot_id"], slot_date,
                        reused.place_id, reused.category,
                    )
                    place = reused
                    place_id = place.place_id
                else:
                    # 旧設計: raise IneligiblePlaceForSlotError。
                    # 新設計 (v5): warn + accept、validator が後段で catch して retry へ。
                    logger.warning(
                        "Place %r ineligible for slot %r (opening_hours mismatch on %s); "
                        "no alternate, accepting (validator will catch and retry)",
                        place_id, slot_meta["slot_id"], slot_date,
                    )

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
            # Phase 2 polish v5 (Codex review 2 Major 3): 連続同 place (lodging 連泊等) は
            # self-loop transit edge が transit_matrix で禁止のため transit item 生成 skip。
            # ただし時刻の単調増加は維持する必要があるので start_dt = max(start_dt, prev_end_dt) で補正。
            if prev_place.place_id == place_id:
                logger.info(
                    "Same place as previous slot (slot=%s, place_id=%r); skipping transit item (self-loop forbidden)",
                    slot_meta["slot_id"], place_id,
                )
                if prev_end_dt > start_dt:
                    shift = prev_end_dt - start_dt
                    start_dt = prev_end_dt
                    end_dt = end_dt + shift
            else:
                edge = _lookup_transit_edge(prev_place.place_id, place_id, pack.transit_matrix)
                if edge is None:
                    # 代替選定: 同カテゴリ近接 + slot 適合 place に差し替え
                    alternate = _find_alternate_place(
                        pack=pack,
                        from_place_id=prev_place.place_id,
                        target_place=place,
                        slot_meta=slot_meta,
                        slot_date=slot_date,
                        exclude_place_ids=used_place_ids,
                    )
                    if alternate is not None:
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

                if edge is None:
                    # Phase 2 polish v5: alternate も無いとき、旧設計は raise NoFeasibleTransitError。
                    # 新設計: transit item を skip + place_id をそのまま採用 (Codex review 1 Critical 1
                    # 反映、Codex review 2 Major 1 反映で時刻補正を transit 経路と統一)。
                    logger.warning(
                        "No transit edge from %r to %r; skipping transit item, accepting place as-is",
                        prev_place.place_id, place_id,
                    )
                    if prev_end_dt > start_dt:
                        shift = prev_end_dt - start_dt
                        start_dt = prev_end_dt
                        end_dt = end_dt + shift
                else:
                    transit_start = prev_end_dt
                    # Phase 2 polish v6 (2026-04-28、本番 Run 13e で `invalid_time_range`
                    # 多発の対策): edge.duration_min が 0 (徒歩 0 分の至近距離) のとき
                    # transit_start == transit_end になり validator が `start >= end` で catch。
                    # 最小 1 分の duration を保証して invalid_time_range を構造的に防ぐ。
                    duration_min = max(1, edge.duration_min)
                    transit_end = transit_start + timedelta(minutes=duration_min)
                    # activity 開始を transit 到着に合わせて繰り下げ
                    if transit_end > start_dt:
                        shift = transit_end - start_dt
                        start_dt = transit_end
                        end_dt = end_dt + shift
                    # Phase 2 polish v5: post-shift で opening close 超えのとき、
                    # 旧設計は raise IneligiblePlaceForSlotError。
                    # 新設計: warn + accept、validator が後段で OUTSIDE_OPENING_HOURS を catch。
                    if not is_place_open_at_dt(place, start_dt):
                        logger.warning(
                            "Place %r closed at post-shift start %s (transit shift moved start past close); "
                            "accepting (validator will catch)",
                            place_id, start_dt.strftime('%Y-%m-%d %H:%M'),
                        )
                    # Phase 2 polish v5: `_pick_departure_time` が候補時刻不足で raise する
                    # ケースも transit skip 扱いに緩和。`candidate_departures` 全部が
                    # start_hhmm より前なら transit を生成せず place のみ採用する。
                    try:
                        items.append(
                            _build_transit_item(
                                order_index=order_index,
                                edge=edge,
                                start_dt=transit_start,
                                end_dt=transit_end,
                            )
                        )
                        order_index += 1
                    except NoFeasibleTransitError as exc:
                        logger.warning(
                            "Transit edge %r->%r departure infeasible (%s); skipping transit item, accepting place",
                            prev_place.place_id, place_id, exc,
                        )

        # Phase 3 polish 案 D 第 6 段 (2026-04-28): 楽天 lodging は API 取得済の実価格を
        # 使い、cost_confidence="verified" にする。`_PRICE_MAP` 経由の estimated 値で
        # 上書きすると inline Evidence Badge が「推定」表示になり、楽天で実価格を取って
        # いる事実が見えなくなる問題への対応。
        cost_jpy, cost_conf = _resolve_cost_with_rakuten_override(
            slot_meta["item_type"], place, pack
        )
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
        # Phase 2 polish v5: lodging slot は連泊許容のため used_place_ids に加えない。
        # 他 type 副作用の補足 (Codex review 1 Minor 3 反映、validator 仕様の正確化):
        #   - meal slot で lodging place を再使用するケースは validator の
        #     item_type_category_mismatch (lodging category は meal allowlist 外) で catch される
        #   - lodging slot で meal place を再使用するケースも同様に validator が catch
        #   - activity slot は validator が category 整合を check しないので素通りリスクあり、
        #     ただし LLM 側で eligible_for_slots 機構で誘導されるため実害は限定的
        if slot_meta["item_type"] != "lodging":
            used_place_ids.add(place_id)
        prev_entry = {"place": place, "end_dt": end_dt}

    # Phase 2 polish v5: 旧 v1 の `_drop_duplicate_place_items` 最終 invariant drop は削除。
    # 重複は best-effort 政策で意図的に許容するため、最終 drop は矛盾する。
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


def _is_item_type_compatible(item_type: str, place_categories: list[str]) -> bool:
    """slot.item_type に対し place の category が validator の整合性チェックを通るか。

    `validator._check_item_type_category_consistency` と同じ判定で、tier3 fallback での
    `item_type_category_mismatch` 誘発を防ぐ (Phase 2 polish v3 T7、Codex review 1 M2)。
    validator helper (`_categories_indicate_meal` / `_categories_indicate_lodging`) を再利用
    することで、将来 allowlist が更新された時に assembler tier3 も自動追従する
    (Codex review 2 Major: 独自 list が validator より狭く正常候補を回帰で落とすリスク回避)。

    Codex review 4 Major: validator 本体は空 category を **skip (許容)** するため、
    本 helper も空なら True を返して挙動を一致させる。さもなくば tier3 候補が不要に減って
    `NoFeasibleTransitError` を増やすリスク。
    """
    if not place_categories:
        return True
    if item_type == "meal":
        return _categories_indicate_meal(place_categories)
    if item_type == "lodging":
        return _categories_indicate_lodging(place_categories)
    return True  # activity slot は category 制約なし (validator も activity はチェックしない)


def _find_item_type_compatible_used_place(
    *,
    pack: EvidencePack,
    used_place_ids: set[str],
    item_type: str,
    slot_meta: dict,
    slot_date: date,
    prev_place_id: str | None = None,
) -> PlacePoint | None:
    """item_type pre-check で fresh alternate 候補が枯渇したとき、used_place_ids 集合内で
    item_type compatible な place を再使用するための fallback (Phase 2 polish v6.2)。

    本番 Run 13e+13f で `item_type_category_mismatch` が支配 issue となり、原因は pack の
    meal candidate 不足 + 重複防止で 4-6 meal slot 埋めるには candidate 足りない構造。
    解: 「meal 枯渇時は同じ restaurant を再使用してでも item_type は守る」設計。

    優先順位:
      1. used 集合内 + item_type compatible + slot eligibility OK
      2. rating 最高、tie は place_id 辞書順
      3. 見つからなければ None (caller は warn + accept で validator catch に流す)

    **reachability は filter しない**: 同 place 連続 (self-loop) は後段 transit logic で
    skip される、edge 不在は同じく transit skip path に流れる。reuse は item_type 守る
    ための fallback で reachability は別の問題として後段が handle する。
    """
    if not used_place_ids:
        return None
    candidates: list[PlacePoint] = []
    for p in pack.places:
        if p.place_id not in used_place_ids:
            continue
        if not _is_item_type_compatible(item_type, p.category):
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
    return min(candidates, key=lambda p: (-(p.rating or 0.0), p.place_id))


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
      3. 任意の上記同条件 place のうち rating 最高 (Phase 2 polish v3 T7: item_type 整合 filter 追加)
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
        # Phase 2 polish v3 T4-1: 候補枯渇時の可視性 log。本番 Run 13c では
        # 「reachable + eligible + 未使用」候補 0 件で `unknown_transit_edge` 多発、
        # ここで count breakdown を残して原因切り分けを高速化する。
        logger.warning(
            "_find_eligible_alternate_for_slot exhausted: target=%s slot_id=%s item_type=%s "
            "prev_place_id=%s reachable_ids=%d excluded=%d total_places=%d",
            target_place.place_id,
            slot_meta.get("slot_id"),
            slot_meta.get("item_type"),
            prev_place_id,
            len(reachable_ids) if reachable_ids is not None else -1,
            len(excluded),
            len(pack.places),
        )
        return None

    target_primary = target_place.category[0] if target_place.category else None
    target_categories = set(target_place.category)
    item_type = slot_meta.get("item_type", "activity")

    # Phase 2 polish v6 (Codex review 1 Major 1 反映): tier1/tier2 にも item_type filter を
    # 適用する。target_place 自体が item_type 不適合 (例: meal slot に LLM が park を割当)
    # のとき、tier1/2 で同 category 系 (park の同 category) を返してしまうと結局 swap が
    # 機能せず park のままになる事故を防ぐ。
    # tier 1: 同 category[0] かつ item_type 適合
    tier1 = [
        p for p in candidates
        if p.category and target_primary is not None and p.category[0] == target_primary
        and _is_item_type_compatible(item_type, p.category)
    ]
    if tier1:
        return min(tier1, key=lambda p: (-(p.rating or 0.0), p.place_id))
    # tier 2: category 共通集合 かつ item_type 適合
    tier2 = [
        p for p in candidates
        if set(p.category) & target_categories
        and _is_item_type_compatible(item_type, p.category)
    ]
    if tier2:
        return min(tier2, key=lambda p: (-(p.rating or 0.0), p.place_id))
    # tier 3 (Phase 2 polish v3 T7): item_type と category の整合 filter を validator と
    # 同じ判定で適用する。空 category は許容（validator と挙動一致）。
    tier3 = [p for p in candidates if _is_item_type_compatible(item_type, p.category)]
    if tier3:
        return min(tier3, key=lambda p: (-(p.rating or 0.0), p.place_id))
    # tier3 全落ち（item_type 不整合のみで eligibility は OK）。Codex review 5 Minor 1 反映:
    # candidates 自体は 0 件ではないので最初の exhausted log path には入らない、ここで補完。
    logger.warning(
        "_find_eligible_alternate_for_slot tier3 filtered out all candidates: target=%s "
        "slot_id=%s item_type=%s candidates=%d",
        target_place.place_id,
        slot_meta.get("slot_id"),
        item_type,
        len(candidates),
    )
    return None


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
        # Phase 2 polish v3 T4-1: 候補枯渇 warning log。「reachable + 同 category +
        # 営業時間 OK + 未使用」全部満たす候補 0 件 = transit 不成立 swap も詰む状態。
        logger.warning(
            "_find_alternate_place exhausted: target=%s target_category=%s "
            "from_place_id=%s reachable=%d excluded=%d total_places=%d",
            target_place.place_id,
            target_place.category,
            from_place_id,
            len(reachable_ids),
            len(excluded),
            len(pack.places),
        )
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
