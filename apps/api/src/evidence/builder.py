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

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from ..schemas import GeneratePlanRequest
from ..themes import get_keywords as _theme_keywords
from .pack import (
    BudgetConstraints,
    BudgetBreakdownJPY,
    EvidencePack,
    LodgingOption,
    PlacePoint,
    QueryContext,
    QueryContextParticipant,
    TemporalConstraints,
)
from .lodging import RakutenLodgingError, fetch_lodging_options
from .places import PlacesError, fetch_place_details, search_by_text

JST = ZoneInfo("Asia/Tokyo")
MAX_PLACES = 15  # Evidence Pack に載せる最大スポット数
PARALLEL_WORKERS = 5
DEFAULT_START_HOUR = 9
DEFAULT_END_HOUR = 20

class AnchorFetchError(Exception):
    """anchor mode で指定 place_id が **存在しない (404)** ため pack を組めなかった
    （Phase 2.1 / Codex Major 3）。

    user 入力ミス相当なので route 側で 400 を返し missing_ids を user に伝える。
    インフラ障害（5xx / network 断）は別の `AnchorFetchUpstreamError` で扱う
    （Codex 再レビュー Major 1 対応、誤った 400 で運用監視を歪めない）。
    """

    def __init__(self, missing_ids: list[str]):
        self.missing_ids = list(missing_ids)
        super().__init__(f"anchor place_ids not found (404): {self.missing_ids}")


class AnchorFetchUpstreamError(Exception):
    """anchor 詳細取得で Places API 側のインフラ障害（5xx / network / 認証）が発生した
    （Codex 再レビュー Major 1 対応）。

    user 入力ミスではないので route 側で 502 を返す。再試行で回復する可能性あり。
    """

    def __init__(self, place_id: str, cause: Exception):
        self.place_id = place_id
        self.__cause__ = cause
        super().__init__(f"anchor fetch upstream error for {place_id!r}: {cause}")


# Phase 2.1: theme モードの検索 keyword は src/themes.py の THEME_REGISTRY を参照
# （Codex Minor 5）。`_theme_keywords(theme)` で list[str] を取得。


def build_evidence_pack(request: GeneratePlanRequest) -> EvidencePack:
    """GeneratePlanRequest から Evidence Pack の **places-only 部分**を組み立てる。

    transit_matrix は空で返す。フロントが Maps JS SDK DirectionsService を使って
    埋め、最終的に `/api/plans/generate` でサーバーに戻す（Phase 1.3 で実装）。

    個別 search 呼び出しの一時的失敗は fail-soft（該当キーワードの結果が空になる）。
    全件失敗しても build は成功し、空 places の EvidencePack を返す。

    Phase 2.1 出発モード切替:
    - anchor: mode_payload.anchor_place_ids を Place Details で取得して pack の先頭に
      載せる（user 明示意思なので area filter は skip）。1 件でも fetch 失敗したら
      AnchorFetchError を raise（Codex Major 3、fail-fast）。
    - theme: mode_payload.theme で _generate_keywords が theme 別語彙を追加する。
    - auto: 従来通り（変更なし）。

    Phase 2.1 Codex Major 2: search と anchor fetch を **同一 ThreadPoolExecutor で並列化**
    して anchor mode の P95 レイテンシを短縮する（旧: search → anchor の直列）。
    """
    ctx = _build_query_context(request)
    queries = _generate_keywords(ctx)
    anchor_ids = _extract_anchor_ids(request)

    # search × N + anchor fetch × M を同一 executor で並列実行（Codex Major 2 対応）。
    # anchor を **先に submit** して worker 枠を確保し、`as_completed` で完了順に監視。
    # upstream error なら `shutdown(wait=False, cancel_futures=True)` で pending を破棄
    # して関数を即時 return（実行中タスクは background 完了に委ねる、Codex 再々々レビュー Major 1）。
    anchor_fetched_by_id: dict[str, PlacePoint | None] = {}
    ex = ThreadPoolExecutor(max_workers=PARALLEL_WORKERS)
    try:
        anchor_future_to_pid = {ex.submit(_fetch_anchor_safe, pid): pid for pid in anchor_ids}
        search_futures = [ex.submit(_search_safe, q) for q in queries]

        for fut in as_completed(anchor_future_to_pid):
            pid = anchor_future_to_pid[fut]
            # AnchorFetchUpstreamError は finally の shutdown を経由して上に伝播する。
            # 404 None も含む正常 result はここで集約。
            anchor_fetched_by_id[pid] = fut.result()

        search_results = [f.result() for f in search_futures]
    finally:
        # success path: 全 future 完了後なので即返る。
        # error path: pending future を破棄して即時 return（実行中は background）。
        ex.shutdown(wait=False, cancel_futures=True)

    # anchor 結果から missing を抽出して fail-fast（Codex Major 3）
    anchor_places: list[PlacePoint] = []
    missing_anchors: list[str] = []
    for pid in anchor_ids:
        place = anchor_fetched_by_id.get(pid)
        if place is None:
            missing_anchors.append(pid)
        else:
            anchor_places.append(place)
    if missing_anchors:
        raise AnchorFetchError(missing_anchors)

    places = _merge_anchors_and_search(anchor_places, search_results, MAX_PLACES)
    temporal = _compute_temporal_constraints(request)
    budget = _compute_budget_constraints(request)
    lodging_options = _fetch_lodging_safe(ctx, request, temporal, budget)

    return EvidencePack(
        query_context=ctx,
        places=places,
        transit_matrix=[],  # Phase 1.3 でフロントが埋める
        lodging_options=lodging_options if lodging_options else None,
        budget_constraints=budget,
        temporal_constraints=temporal,
    )


def _extract_anchor_ids(request: GeneratePlanRequest) -> list[str]:
    """anchor モード時に mode_payload から place_id 配列を取り出す（auto/theme/壊れた payload は []）。"""
    if request.start_mode != "anchor" or not request.mode_payload:
        return []
    raw_ids = request.mode_payload.get("anchor_place_ids") if isinstance(request.mode_payload, dict) else None
    if not isinstance(raw_ids, list):
        return []
    return [pid for pid in raw_ids if isinstance(pid, str)]


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

    Phase 2.1: theme モードでは _THEME_KEYWORDS の語彙を追加（pack を theme 寄りに bias）。
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

    # Phase 2.1: theme モード時の追加 keyword（重複は無視）
    if ctx.start_mode == "theme" and ctx.mode_payload:
        theme = ctx.mode_payload.get("theme") if isinstance(ctx.mode_payload, dict) else None
        if isinstance(theme, str):
            for word in _theme_keywords(theme):
                kw = f"{ctx.region} {word}"
                if kw not in keywords:
                    keywords.append(kw)

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


# Google Places API が返す「region/area」相当の primary category。
# これらが先頭にある place は specific spot ではなく地理範囲（locality=市町村、
# colloquial_area=俗称エリア、political/administrative_area=行政区分）を表すため
# plan item にできず、opening_hours も無い。pack 構築時に除外する
# （@tasks/lessons.md 2026-04-25 診断、Phase 1.3e success rate 改善）。
_AREA_PRIMARY_CATEGORIES: frozenset[str] = frozenset(
    {
        "locality",
        "sublocality",
        "sublocality_level_1",
        "sublocality_level_2",
        "colloquial_area",
        "political",
        "country",
        "administrative_area_level_1",
        "administrative_area_level_2",
        "administrative_area_level_3",
        "neighborhood",
        "postal_code",
    }
)


def _is_area_place(place: PlacePoint) -> bool:
    """primary category（category[0]）が area 系なら True。"""
    if not place.category:
        return False
    return place.category[0] in _AREA_PRIMARY_CATEGORIES


def _dedupe_and_cap(batches: list[list[PlacePoint]], cap: int) -> list[PlacePoint]:
    unique: dict[str, PlacePoint] = {}
    for batch in batches:
        for p in batch:
            if p.place_id in unique:
                continue
            if _is_area_place(p):
                continue
            unique[p.place_id] = p
    return list(unique.values())[:cap]


# ==============================
# Phase 2.1: anchor モード補助
# ==============================


def _fetch_anchor_safe(place_id: str) -> PlacePoint | None:
    """anchor 1 件取得。

    - 404 (None 返却) → None のまま返す（build_evidence_pack 側で missing_ids に集約 → 400）
    - PlacesError（5xx / network / 認証等）→ AnchorFetchUpstreamError に変換して raise
      （build_evidence_pack 側でそのまま伝播 → route で 502）
    """
    try:
        return fetch_place_details(place_id)
    except PlacesError as e:
        raise AnchorFetchUpstreamError(place_id, e) from e


def _merge_anchors_and_search(
    anchors: list[PlacePoint],
    search_results: list[list[PlacePoint]],
    cap: int,
) -> list[PlacePoint]:
    """anchor を先頭に、後ろに search 結果を続ける。dedupe + cap。

    anchor は user 明示意思なので area_place フィルタを skip する。
    search 結果側は従来通り area_place を除外。
    """
    unique: dict[str, PlacePoint] = {}
    # anchors（area filter skip）
    for p in anchors:
        if p.place_id not in unique:
            unique[p.place_id] = p
    # search results（area filter 適用、anchor と重複は無視）
    for batch in search_results:
        for p in batch:
            if p.place_id in unique:
                continue
            if _is_area_place(p):
                continue
            unique[p.place_id] = p
    return list(unique.values())[:cap]


# ==============================
# 楽天トラベル宿泊候補取得
# ==============================

import logging as _logging
_logger = _logging.getLogger(__name__)


def _fetch_lodging_safe(
    ctx: QueryContext,
    request: "GeneratePlanRequest",
    temporal: TemporalConstraints,
    budget: BudgetConstraints,
) -> list[LodgingOption]:
    """楽天トラベル API で宿泊候補を取得する。失敗時は空リストを返す（fail-soft）。"""
    # 日帰り（1 泊なし）なら宿泊不要
    if temporal.total_days <= 1:
        return []
    try:
        checkin = request.start_date.isoformat()
        checkout = request.end_date.isoformat()
        adult_num = max(1, len(request.participants))
        max_charge = budget.breakdown_jpy.lodging
        return fetch_lodging_options(
            region=ctx.region,
            checkin_date=checkin,
            checkout_date=checkout,
            adult_num=adult_num,
            max_charge_per_night=max_charge,
        )
    except RakutenLodgingError as e:
        _logger.warning("rakuten lodging fetch skipped: %s", e)
        return []


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
