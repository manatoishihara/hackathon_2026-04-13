"""Evidence Pack の組み立て（docs/evidence-pack.md 「Pack 構築フロー」）。

Phase 1.2 の範囲:
1. GeneratePlanRequest から QueryContext を派生
2. 決定論的にキーワードを生成（`{region} 観光` 等）
3. Places API を並列に叩いて dedupe
4. 予算と時間制約を展開
5. transit_matrix は空配列で返す（フロントが Maps JS SDK で後から埋める、Phase 1.3）

**transit をサーバー側で取らない理由**: Google Maps Platform の Directions / Routes API は
日本国内の公共交通データを返さない（`tasks/lessons.md` 参照）。transit 情報はフロント側
の Maps JS SDK DirectionsService 経由で取得し、`/api/plans/generate` に添えて送る設計。

relevance_tags のスコアリングと candidate_departures の複数化は Phase 1.3 で実装。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from ..schemas import GeneratePlanRequest
from .pack import (
    BudgetConstraints,
    BudgetBreakdownJPY,
    EvidencePack,
    PlacePoint,
    QueryContext,
    QueryContextParticipant,
    TemporalConstraints,
)
from .places import PlacesError, search_by_text

JST = ZoneInfo("Asia/Tokyo")
MAX_PLACES = 15  # Evidence Pack に載せる最大スポット数
PARALLEL_WORKERS = 5
DEFAULT_START_HOUR = 9
DEFAULT_END_HOUR = 20


def build_evidence_pack(request: GeneratePlanRequest) -> EvidencePack:
    """GeneratePlanRequest から Evidence Pack の **places-only 部分**を組み立てる。

    transit_matrix は空で返す。フロントが Maps JS SDK DirectionsService を使って
    埋め、最終的に `/api/plans/generate` でサーバーに戻す（Phase 1.3 で実装）。

    個別 Places 呼び出しの一時的失敗は fail-soft（該当キーワードの結果が空になる
    だけ）。全件失敗しても build は成功し、空 places の EvidencePack を返す。
    """
    ctx = _build_query_context(request)
    queries = _generate_keywords(ctx)

    with ThreadPoolExecutor(max_workers=PARALLEL_WORKERS) as ex:
        search_results = list(ex.map(_search_safe, queries))

    places = _dedupe_and_cap(search_results, MAX_PLACES)

    return EvidencePack(
        query_context=ctx,
        places=places,
        transit_matrix=[],  # Phase 1.3 でフロントが埋める
        budget_constraints=_compute_budget_constraints(request),
        temporal_constraints=_compute_temporal_constraints(request),
    )


# ==============================
# Query Context の派生
# ==============================


def _build_query_context(request: GeneratePlanRequest) -> QueryContext:
    return QueryContext(
        region=request.region,
        start_date=request.start_date,
        end_date=request.end_date,
        departure_point=request.departure_point,
        start_mode=request.start_mode,
        mode_payload=request.mode_payload,
        participants=[
            QueryContextParticipant(
                name=p.display_name,
                wishes=p.wishes_text,
                tags=list(p.tags),
            )
            for p in request.participants
        ],
    )


# ==============================
# キーワード生成（決定論）
# ==============================


def _generate_keywords(ctx: QueryContext) -> list[str]:
    """region と参加者 tag から 3〜5 個の検索キーワードを作る。

    Phase 1.3 で LLM ベース or 希望文からの抽出に置き換え可能。
    """
    keywords = [
        f"{ctx.region} 観光",
        f"{ctx.region} 飲食",
    ]
    seen: list[str] = []
    for participant in ctx.participants:
        for tag in participant.tags:
            if tag not in seen:
                seen.append(tag)
            if len(seen) >= 3:
                break
        if len(seen) >= 3:
            break
    for tag in seen:
        keywords.append(f"{ctx.region} {tag}")
    return keywords


# ==============================
# Places 並列取得 + dedupe
# ==============================


def _search_safe(query: str) -> list[PlacePoint]:
    """Places API 失敗時は空リストを返す（全体の build を止めない）。"""
    try:
        return search_by_text(query)
    except PlacesError:
        return []


def _dedupe_and_cap(batches: list[list[PlacePoint]], cap: int) -> list[PlacePoint]:
    unique: dict[str, PlacePoint] = {}
    for batch in batches:
        for p in batch:
            if p.place_id not in unique:
                unique[p.place_id] = p
    return list(unique.values())[:cap]


# ==============================
# 予算・時間の展開
# ==============================


def _compute_budget_constraints(request: GeneratePlanRequest) -> BudgetConstraints:
    total = request.budget_per_person_jpy
    pct = request.budget_breakdown
    breakdown_jpy = BudgetBreakdownJPY(
        lodging=int(total * pct.lodging / 100),
        meal=int(total * pct.meal / 100),
        activity=int(total * pct.activity / 100),
        transit=int(total * pct.transit / 100),
    )
    return BudgetConstraints(
        total_jpy_per_person=total,
        breakdown_percent=pct,
        breakdown_jpy=breakdown_jpy,
    )


def _compute_temporal_constraints(request: GeneratePlanRequest) -> TemporalConstraints:
    start_dt = datetime.combine(request.start_date, time(DEFAULT_START_HOUR, 0), tzinfo=JST)
    end_dt = datetime.combine(request.end_date, time(DEFAULT_END_HOUR, 0), tzinfo=JST)
    total_days = (request.end_date - request.start_date).days + 1
    return TemporalConstraints(
        start_datetime=start_dt,
        end_datetime=end_dt,
        total_days=total_days,
    )
