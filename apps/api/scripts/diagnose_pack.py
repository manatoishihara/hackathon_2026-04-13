"""Phase 1.3e success rate 改善の事前診断スクリプト。

verify_hallucination_rate.py と同じ pack を組み立て、以下を表で出力する:
- places の category と opening_hours の day_of_week カバー
- 検証日（2026-06-01 月 / 2026-06-02 火）の各 slot 時間帯に対する各 place の重なり
- 自己ループ的な「他に同 category が居ない」place の検出

使い方:
    cd apps/api
    .venv/bin/python scripts/diagnose_pack.py
"""

from __future__ import annotations

import sys
from collections import Counter
from datetime import date
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from dotenv import find_dotenv, load_dotenv  # noqa: E402

load_dotenv(find_dotenv(".env", usecwd=True), override=False)
load_dotenv(find_dotenv(".env.local", usecwd=True), override=True)

from src.evidence.builder import build_evidence_pack  # noqa: E402
from src.llm.assembly import generate_slot_catalog  # noqa: E402
from scripts.verify_hallucination_rate import _build_request  # noqa: E402

DOW_NAME = ["月", "火", "水", "木", "金", "土", "日"]


def _slot_overlaps(slot_open: str, slot_close: str, slot_start: str, slot_end: str) -> bool:
    """簡易: HH:mm 文字列同士で半閉区間の重なり判定（assembly._fit_to_opening_hours と同等の意味論）。"""
    return slot_open < slot_end and slot_start < slot_close


def main() -> int:
    request = _build_request()
    pack = build_evidence_pack(request)
    places = pack.places
    print(f"Pack: places={len(places)}, transit_edges={len(pack.transit_matrix)}")
    print(f"Date range: {request.start_date} ({DOW_NAME[request.start_date.weekday()]}) "
          f"〜 {request.end_date} ({DOW_NAME[request.end_date.weekday()]})")
    print()

    # 1) category distribution
    print("=== Category distribution ===")
    cat_counter: Counter[str] = Counter()
    for p in places:
        for c in p.category:
            cat_counter[c] += 1
    primary_counter: Counter[str] = Counter(p.category[0] if p.category else "(none)" for p in places)
    for cat, n in primary_counter.most_common():
        print(f"  {cat:<28} primary={n:<2}")
    print()

    # 2) places summary
    print("=== Places summary ===")
    print(f"{'idx':<4}{'pid':<28}{'name':<28}{'cat0':<28}{'#oh':<5}{'unknown_days'}")
    for i, p in enumerate(places):
        cat0 = p.category[0] if p.category else "(none)"
        print(
            f"{i:<4}{p.place_id[:24]+'..':<28}{p.name[:24]:<28}"
            f"{cat0[:24]:<28}{len(p.opening_hours):<5}"
            f"{p.opening_hours_unknown_days}"
        )
    print()

    # 3) day-of-week opening coverage for verify dates
    target_days = [request.start_date, request.end_date]
    print("=== Opening coverage on target days ===")
    print(
        f"{'idx':<4}{'name':<28}"
        + "".join(f"{DOW_NAME[d.weekday()]:>4}" for d in target_days)
    )
    for i, p in enumerate(places):
        cells = []
        for d in target_days:
            dow = d.weekday()
            if dow in p.opening_hours_unknown_days:
                cells.append(" U  ")  # Unknown
            elif not p.opening_hours:
                cells.append(" -  ")  # 営業時間情報なし
            else:
                day_slots = [s for s in p.opening_hours if s.day_of_week == dow]
                cells.append(f"{len(day_slots):>4}")
        print(f"{i:<4}{p.name[:24]:<28}{''.join(cells)}")
    print("  凡例: 数字=その曜日の slot 数 / U=unknown_days / - = opening_hours 空")
    print()

    # 4) slot × place の重なり、最も問題になる slot を特定
    catalog = generate_slot_catalog(pack.temporal_constraints.total_days)
    base_date = request.start_date
    print("=== Slot × Place 重なり数 (verify date) ===")
    print(f"{'slot_id':<22}{'item_type':<10}{'eligible places (count, list)'}")
    for s in catalog:
        # day index -> date
        d_idx = int(s["slot_id"].split("_")[0].removeprefix("day")) - 1
        slot_date = date.fromordinal(base_date.toordinal() + d_idx)
        dow = slot_date.weekday()
        eligible = []
        for p in places:
            if dow in p.opening_hours_unknown_days or not p.opening_hours:
                eligible.append(p.name[:10])
                continue
            day_slots = [ss for ss in p.opening_hours if ss.day_of_week == dow]
            if not day_slots:
                continue
            if any(
                _slot_overlaps(ds.open_hhmm, ds.close_hhmm, s["start_hhmm"], s["end_hhmm"])
                for ds in day_slots
            ):
                eligible.append(p.name[:10])
        names = ", ".join(eligible) if eligible else "(NONE!)"
        print(
            f"  {s['slot_id']:<20}{s['item_type']:<10}"
            f"n={len(eligible):<3} [{names}]"
        )
    print()

    # 5) singleton categories (代替選定が枯渇するもの)
    print("=== Singleton primary categories (代替選定が困難) ===")
    for cat, n in primary_counter.items():
        if n == 1:
            place = next(p for p in places if (p.category[0] if p.category else None) == cat)
            print(f"  {cat:<28} → only: {place.name} ({place.place_id})")
    print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
