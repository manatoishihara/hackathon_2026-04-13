"""10 回プラン生成してハルシネーション発生率を測る手動検証スクリプト。

Phase 1.3d 検証項目「架空スポット出力率 0%」を確認するために使う。
実 OpenAI / 実 Places を呼ぶ（1 run あたり概ね $0.10-0.30、10 回で合計 $1-3 の想定）。
通常の pytest スイートには含めず、`apps/api/scripts/` 配下の手動 run 専用。

## 使い方

    cd apps/api
    .venv/bin/python scripts/verify_hallucination_rate.py         # デフォルト 10 回
    .venv/bin/python scripts/verify_hallucination_rate.py --runs 3  # 回数を指定

### 必要な環境変数（リポジトリ root の .env を自動ロード）
- OPENAI_API_KEY
- GOOGLE_MAPS_API_KEY

## 判定

各 run の結果を以下で分類し、最後に集計する:
- success:      `generate_plan()` が LlmGeneratedPlan を返した（validator 全通過）
- hallucination: LlmGenerationError かつ最終 issues に UNKNOWN_PLACE_ID を含む（= 架空スポット）
- other_failure: LlmGenerationError だが UNKNOWN_PLACE_ID は無い（時刻・予算違反 等）
- transport:    LlmTransportError（OpenAI 通信系、検証対象外）
- refusal:      LlmRefusalError（safety refuse、検証対象外）
- bad_request:  LlmBadRequestError（schema 不整合、実装バグ）
- deadline:     DeadlineExceededError（150s 超過）

「architecture 1.3d 検証項目」として合格条件は hallucination == 0。
通信・refusal・deadline は外乱扱いで集計から除外しない（参考情報）。
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date
from pathlib import Path
from uuid import uuid4

# apps/api を sys.path に追加（リポジトリ root の .env を拾うため dotenv は cwd 依存）
API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv(".env", usecwd=True), override=False)
load_dotenv(find_dotenv(".env.local", usecwd=True), override=True)

from src.evidence.builder import build_evidence_pack  # noqa: E402
from src.evidence.pack import EvidencePack, TransitEdge  # noqa: E402
from src.llm.generator import (  # noqa: E402
    DeadlineExceededError,
    LlmBadRequestError,
    LlmGenerationError,
    LlmRefusalError,
    LlmTransportError,
    generate_plan,
)
from src.llm.validator import IssueKind  # noqa: E402
from src.schemas import (  # noqa: E402
    BudgetBreakdown,
    GeneratePlanRequest,
    ParticipantInput,
)


def _build_request() -> GeneratePlanRequest:
    """検証用の固定入力（箱根 1 泊 2 日、複数参加者で wishes に多様性）。"""
    return GeneratePlanRequest(
        title="箱根温泉検証旅",
        region="箱根",
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 2),
        departure_point="新宿駅",
        budget_per_person_jpy=35000,
        # 旅行実態に即した配分（食事 25→30、宿 45→40 で旅行者の実比率に近づける）。
        # 4 食 × 2,500 円が 8,750 円ベンチマークを超える問題を解消（@tasks/lessons.md 2026-04-25）
        budget_breakdown=BudgetBreakdown(lodging=40, meal=30, activity=20, transit=10),
        start_mode="auto",
        mode_payload=None,
        participants=[
            ParticipantInput(
                display_name="太郎",
                avatar_color="#D97757",
                wishes_text="温泉でゆったり、和食を食べたい",
                tags=["温泉", "和食"],
                order_index=0,
            ),
            ParticipantInput(
                display_name="花子",
                avatar_color="#2C5F5D",
                wishes_text="美術館や散策、甘味も好き",
                tags=["美術館", "散策", "カフェ"],
                order_index=1,
            ),
        ],
    )


def _km(p, q) -> float:
    from math import asin, cos, radians, sin, sqrt

    R = 6371.0
    dlat = radians(q.lat - p.lat)
    dlng = radians(q.lng - p.lng)
    h = (
        sin(dlat / 2) ** 2
        + cos(radians(p.lat)) * cos(radians(q.lat)) * sin(dlng / 2) ** 2
    )
    return 2 * R * asin(sqrt(h))


def _build_transit_matrix(
    pack: EvidencePack,
    *,
    max_distance_km: float = 14.0,
    nearest_k: int = 5,
    hard_cap: int = 100,
) -> list[TransitEdge]:
    """各 place から最近傍 `nearest_k` 件の有向エッジを生成（実運用密度に近い）。

    フロント SDK (`apps/web/src/lib/transit.ts`) は 10km 以内 + 並列 5 + 10s 締切で
    40 前後の edge を返す実装。本スクリプトはそれを代替するので全ペア展開せず
    「各 place から最近傍 5」で ~75 edge に抑える（places=15 なら 15×5×2=150 を上限、
    hard_cap=100 で更に capping）。prompt トークン数を現実のレンジ（10k 前後）に
    収めるための調整（詳細は `tasks/lessons.md` 2026-04-25 エントリ参照）。

    `candidate_departures` は validator で transit_ref.departure_time との厳密一致を
    求められるため、日中の主要時間帯を 3 件に絞る。10 件並べた run 4 で prompt token
    が 12k → 14.6k に肥大化し hallucination=66.7% に悪化したため、12k 以下に戻す
    （tasks/plans/2026-04-25-structured-plan-assembly.md「次セッション最初の一手」）。
    """
    places = pack.places
    edges: list[TransitEdge] = []
    edge_kwargs = dict(
        mode="train",
        route_summary="箱根近隣 想定経路",
        duration_min=20,
        fare_jpy=380,
        # β で v2 prompt から candidate_departures は除去済み（_edge_for_llm_v2）。
        # ここの拡張は assembler の _pick_departure_time 用で、prompt token に影響なし。
        # 5 候補で morning〜lodging 全 transit を覆う（Codex Major fix で過去時刻
        # fallback 廃止に伴い、十分な candidate を提供する必要があるため）
        candidate_departures=["09:00", "12:00", "15:00", "18:00", "21:00"],
    )
    seen: set[tuple[str, str]] = set()
    for a in places:
        # 距離昇順で最近傍 k 件を取る
        neighbors = sorted(
            ((_km(a, b), b) for b in places if b.place_id != a.place_id),
            key=lambda pair: pair[0],
        )
        added = 0
        for dist, b in neighbors:
            if dist > max_distance_km:
                break
            key = (a.place_id, b.place_id)
            if key in seen:
                continue
            edges.append(
                TransitEdge(from_place_id=a.place_id, to_place_id=b.place_id, **edge_kwargs)
            )
            seen.add(key)
            added += 1
            if added >= nearest_k:
                break
            if len(edges) >= hard_cap:
                return edges
    if not edges:
        raise RuntimeError(
            f"no pair within {max_distance_km}km among {len(places)} places; "
            "test fixture (region) 見直し対象"
        )
    return edges


def _classify_failure(exc: Exception) -> tuple[str, int, dict[str, int]]:
    """例外を分類し、`(category, hallucination_issue_count, issue_kind_counts)` を返す。"""
    if isinstance(exc, LlmGenerationError):
        kind_counts: dict[str, int] = {}
        for issue in exc.issues:
            kind_counts[issue.kind.value] = kind_counts.get(issue.kind.value, 0) + 1
        hallucinations = kind_counts.get(IssueKind.UNKNOWN_PLACE_ID.value, 0)
        if hallucinations > 0:
            return "hallucination", hallucinations, kind_counts
        return "other_failure", 0, kind_counts
    if isinstance(exc, LlmTransportError):
        return "transport", 0, {}
    if isinstance(exc, LlmRefusalError):
        return "refusal", 0, {}
    if isinstance(exc, LlmBadRequestError):
        return "bad_request", 0, {}
    if isinstance(exc, DeadlineExceededError):
        return "deadline", 0, {}
    return "unexpected", 0, {}


def run(runs: int) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger = logging.getLogger("verify_hallucination_rate")

    request = _build_request()
    logger.info("Building Evidence Pack (live Places)…")
    pack = build_evidence_pack(request)
    if len(pack.places) < 2:
        logger.error(
            f"pack.places has only {len(pack.places)} entries; 検証に不足。"
            f" region 設定や GOOGLE_MAPS_API_KEY の権限を確認。"
        )
        return 2
    transit_matrix = _build_transit_matrix(pack)
    merged = pack.model_copy(update={"transit_matrix": transit_matrix})
    logger.info(
        f"Pack ready: places={len(merged.places)}, transit_edges={len(merged.transit_matrix)}"
    )

    counts: dict[str, int] = {}
    all_issue_kinds: dict[str, int] = {}
    durations: list[float] = []
    for i in range(1, runs + 1):
        run_id = uuid4().hex[:8]
        logger.info(f"--- run {i}/{runs} [{run_id}] start ---")
        t0 = time.monotonic()
        try:
            plan = generate_plan(merged)
            elapsed = time.monotonic() - t0
            durations.append(elapsed)
            counts["success"] = counts.get("success", 0) + 1
            logger.info(
                f"run {i} [{run_id}] success in {elapsed:.1f}s, "
                f"items={len(plan.items)}"
            )
        except Exception as e:  # noqa: BLE001
            elapsed = time.monotonic() - t0
            durations.append(elapsed)
            category, hallucinations, kind_counts = _classify_failure(e)
            counts[category] = counts.get(category, 0) + 1
            for k, v in kind_counts.items():
                all_issue_kinds[k] = all_issue_kinds.get(k, 0) + v
            detail = (
                ", ".join(f"{k}={v}" for k, v in sorted(kind_counts.items()))
                if kind_counts
                else ""
            )
            logger.warning(
                f"run {i} [{run_id}] {category} in {elapsed:.1f}s: "
                f"{type(e).__name__}: {e}"
                + (f" | issues: {detail}" if detail else "")
            )
            # 詳細: 最終 attempt の各 issue の message も出して原因を特定可能に
            if isinstance(e, LlmGenerationError) and e.issues:
                for issue in e.issues:
                    logger.warning(
                        f"  └─ [{issue.kind.value}] item_index={issue.item_index}: {issue.message}"
                    )

    print("\n==== Summary ====")
    print(f"Total runs: {runs}")
    for category in (
        "success",
        "hallucination",
        "other_failure",
        "transport",
        "refusal",
        "bad_request",
        "deadline",
        "unexpected",
    ):
        if counts.get(category):
            print(f"  {category:<16}: {counts[category]}")
    if durations:
        print(
            f"Duration: avg {sum(durations) / len(durations):.1f}s, "
            f"min {min(durations):.1f}s, max {max(durations):.1f}s"
        )
    if all_issue_kinds:
        print("Validation issues (last-attempt, aggregated):")
        for kind, count in sorted(
            all_issue_kinds.items(), key=lambda kv: -kv[1]
        ):
            print(f"  {kind:<32}: {count}")
    hallucination_rate = counts.get("hallucination", 0) / runs
    print(f"Hallucination rate: {hallucination_rate:.1%}")
    print(
        "Phase 1.3d 合格条件: hallucination == 0 "
        f"→ {'PASS' if counts.get('hallucination', 0) == 0 else 'FAIL'}"
    )
    return 0 if counts.get("hallucination", 0) == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--runs",
        type=int,
        default=10,
        help="生成回数（デフォルト 10）",
    )
    args = parser.parse_args()
    if args.runs <= 0:
        print("--runs must be > 0", file=sys.stderr)
        return 2
    return run(args.runs)


if __name__ == "__main__":
    raise SystemExit(main())
