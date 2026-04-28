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

from math import asin, cos, radians, sin, sqrt

from ..llm.validator import _LODGING_CATEGORIES, _MEAL_CATEGORIES
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
# Phase 2 polish v4 (2026-04-28、本番 Run 13d 失敗を受けて):
# 4 日プランは 19 slot 必要 (5 slot/day × 4 - 1 lodging on last day) で重複完全禁止には
# pack に slot 数 + buffer 必要。固定 MAX_PLACES=15 だと 4 日で必ず候補枯渇 →
# `_find_alternate_place exhausted` で 422。total_days に応じて動的に決定する。
def max_places_for(total_days: int) -> int:
    """total_days に応じた pack 上限。slot 数 + 3 を最低、固定下限 15。

    - 1 日 (4 slot): 15 (current default)
    - 2 日 (9 slot): 15 (current default)
    - 3 日 (14 slot): 17 (= 14 + 3 buffer)
    - 4 日 (19 slot): 22 (= 19 + 3 buffer)
    - 5 日 (24 slot): 27
    """
    slot_count = max(0, 5 * total_days - 1)
    return max(15, slot_count + 3)


# Backward compat: 旧定数として参照されている箇所のため keep。
# **新規コードは max_places_for(total_days) を使うこと**。
MAX_PLACES = 15  # 旧 default、test fixture / 1〜2 日プランで参照
MIN_PLACES = 12  # bucket 不足時にここまで補填する閾値（Run 8 fix、tasks/plans/2026-04-26-evidence-pack-diversity.md）
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

    temporal = _compute_temporal_constraints(request)
    budget = _compute_budget_constraints(request)
    cap = max_places_for(temporal.total_days)
    places = _merge_anchors_and_search(
        anchor_places, search_results, cap, total_days=temporal.total_days
    )
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
    # Phase 2 polish (2026-04-27, A 案撤回): request.transport_mode は deprecated。
    # 旧 client 互換のため受信は許容するが、QueryContext / EvidencePack 内部には伝播させない。
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


_BASE_KEYWORD_SUFFIXES: tuple[str, ...] = (
    "観光地",
    "温泉",
    "神社 寺",
    "食事処",
    # Phase 2 polish v6 (2026-04-28、本番 4 日 plan で lodging 欠損対策):
    # 楽天トラベル API が UUID applicationId で 400 失敗中、Google Places search で
    # lodging 候補を確保する必要がある。「旅館 ホテル」を keyword に追加して
    # 4 日 plan の 3 lodging slot (連泊許容で 1 unique でも可) を埋められるようにする。
    "旅館 ホテル",
    # Phase 3 polish (2026-04-28、iconic spot coverage 改善):
    # 「箱根 観光地」だけだと relevance ranking で取り逃す iconic spot
    # (大涌谷・芦ノ湖・ポーラ美術館・ガラスの森) を「箱根 名所」で拾う狙い。
    # ガイドブック系 keyword は人気度 ranking が強くバイアスされる傾向がある。
    "名所",
)
# Phase 3 polish (2026-04-28、5 → 6 base axes):
# 旧 5 から 6 に拡張、PARALLEL_WORKERS=5 で 2 batch 直列だが許容範囲のレイテンシ。
# theme + tag で +1〜2 されると上限 8 だが _MAX_KEYWORDS=8 まで許容。
_MAX_KEYWORDS = 8


def _generate_keywords(ctx: QueryContext) -> list[str]:
    """region から「観光地 / 温泉 / 神社 寺 / 食事処」の 4 軸を必ず投入し、theme 語彙 + tag 1 個を上限 5 で追加する（Phase 1.10 fix、tasks/plans/2026-04-26-evidence-pack-diversity.md）。

    auto / anchor / theme 全 mode で基本 4 軸を投入することで、Places API text search の
    人気度 ranking 偏重（飲食店ばかり来る Run 7 型）を構造的に防ぐ。

    順序: 基本 4 軸 → theme 語彙（theme モード時、tag より先に予約）→ tag 1 個（重複は無視、
    残り枠分のみ）。合計 ≤ 5。
    Codex review 2 Major 2 反映: theme 語彙を tag より先に入れることで、tag 入力時に
    theme bias が消えてしまう問題を回避。
    """
    keywords: list[str] = [f"{ctx.region} {suffix}" for suffix in _BASE_KEYWORD_SUFFIXES]

    # theme モード時の追加 keyword（tag より先に予約、空き枠分のみ）
    if ctx.start_mode == "theme" and ctx.mode_payload:
        theme = ctx.mode_payload.get("theme") if isinstance(ctx.mode_payload, dict) else None
        if isinstance(theme, str):
            for word in _theme_keywords(theme):
                if len(keywords) >= _MAX_KEYWORDS:
                    break
                kw = f"{ctx.region} {word}"
                if kw not in keywords:
                    keywords.append(kw)

    # tag 1 個（重複は無視、最初に見つけた tag、残り枠分のみ）
    if len(keywords) < _MAX_KEYWORDS:
        for participant in ctx.participants:
            added = False
            for tag in participant.tags:
                kw = f"{ctx.region} {tag}"
                if kw not in keywords:
                    keywords.append(kw)
                    added = True
                    break
            if added:
                break

    return keywords[:_MAX_KEYWORDS]


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


# ==============================
# Phase 1.10 fix: bucket 分類 + quota + 距離ガード
# (tasks/plans/2026-04-26-evidence-pack-diversity.md)
# ==============================

# attraction の category allowlist。観光地として扱うべき Places API type。
# 神社・寺は place_of_worship + tourist_attraction の組み合わせで来ることが多い。
_ATTRACTION_CATEGORIES: frozenset[str] = frozenset(
    {
        "tourist_attraction",
        "museum",
        "park",
        "art_gallery",
        "aquarium",
        "zoo",
        "place_of_worship",
        "church",
        "hindu_temple",
        "mosque",
        "synagogue",
        "natural_feature",
    }
)

# bucket 別の距離閾値 (km)。同 bucket かつこの距離以内なら新候補は skip。
# attraction は施設内 spots 保持のため緩め、lodging は分散重視で厳しめ。
_BUCKET_DISTANCE_KM: dict[str, float] = {
    "attraction": 0.15,
    "meal": 0.30,
    "lodging": 0.50,
    "other": 0.30,
}

# bucket の出力順（pack 先頭から並べる順番）
_BUCKET_OUTPUT_ORDER: tuple[str, ...] = ("attraction", "lodging", "meal", "other")

# 補填の優先順位（MIN_PLACES 未満時に余り候補から取る順）。
# total_days >= 2 のときは lodging 余りも補填対象に含める（Codex review 2 Major 1 反映、
# 候補は十分あるのに 12 未達となるケースを回避）。
_BUCKET_FILL_ORDER_DAY_TRIP: tuple[str, ...] = ("meal", "other", "attraction")
_BUCKET_FILL_ORDER_OVERNIGHT: tuple[str, ...] = ("meal", "other", "attraction", "lodging")


def _classify_bucket(place: PlacePoint) -> str:
    """place の category list から bucket を判定。

    優先順位: lodging > attraction > meal > other（Codex Major 3 反映）。
    複数 category 該当時は最優先 bucket にマップ。例えば ["spa", "lodging"] は lodging。
    `_MEAL_CATEGORIES` / `_LODGING_CATEGORIES` は validator 側を import 再利用（drift 防止）。
    """
    cats = place.category or []
    if any(c in _LODGING_CATEGORIES for c in cats):
        return "lodging"
    if any(c in _ATTRACTION_CATEGORIES for c in cats):
        return "attraction"
    if any(c in _MEAL_CATEGORIES or c.endswith("_restaurant") for c in cats):
        return "meal"
    return "other"


def _bucket_quota(total_days: int) -> dict[str, int]:
    """total_days に応じた bucket 別 quota。**合計は max_places_for(total_days) と一致** する
    ように `other` で残差を吸収する (Codex review 1 Major 2: contract 一致保証)。

    Phase 2 polish v4 (2026-04-28): 3 日以上のプランで quota が slot 数を満たさず
    重複完全禁止で詰む問題を解消。以下の slot 数別 sizing:

    - 日帰り (total_days <= 1, 4 slot): lodging=0、attraction +1 / meal +1 → 15 places
    - 1 泊 (total_days == 2, 9 slot): lodging=1、attraction +1 → 15 places
    - 2 泊 (total_days == 3, 14 slot): lodging=2、3 日 plan の attraction/meal に
      余裕を持たせる → 17 places
    - 3 泊 (total_days == 4, 19 slot): lodging=3 (3 泊分)、activity 8 + meal 8 +
      buffer 2 → 22 places
    - 4 泊 以上 (total_days >= 5, 24+ slot): activity = meal = 2*total_days、
      lodging = total_days - 1、`other` で max_places_for との差分を吸収
    """
    if total_days <= 1:
        return {"attraction": 7, "meal": 6, "lodging": 0, "other": 2}  # 15
    if total_days == 2:
        return {"attraction": 7, "meal": 5, "lodging": 1, "other": 2}  # 15
    if total_days == 3:
        return {"attraction": 7, "meal": 6, "lodging": 2, "other": 2}  # 17
    if total_days == 4:
        return {"attraction": 9, "meal": 8, "lodging": 3, "other": 2}  # 22
    # 5+ 日 (slot 24+): activity = meal = 2 * total_days, lodging = total_days - 1
    activity_q = 2 * total_days
    meal_q = 2 * total_days
    lodging_q = total_days - 1
    # other で max_places_for との差分を吸収して合計一致を保証する。
    other_q = max(2, max_places_for(total_days) - activity_q - meal_q - lodging_q)
    return {"attraction": activity_q, "meal": meal_q, "lodging": lodging_q, "other": other_q}


def _haversine_km(a: PlacePoint, b: PlacePoint) -> float:
    R = 6371.0
    dlat = radians(b.lat - a.lat)
    dlng = radians(b.lng - a.lng)
    h = (
        sin(dlat / 2) ** 2
        + cos(radians(a.lat)) * cos(radians(b.lat)) * sin(dlng / 2) ** 2
    )
    return 2 * R * asin(sqrt(h))


def _distance_ok_for_bucket(
    candidate: PlacePoint,
    accepted_in_bucket: list[PlacePoint],
    bucket: str,
) -> bool:
    """候補が同 bucket の採用済 places から距離閾値以上離れているか。

    閾値以下（境界含む、`<=`）なら overcrowding と判定して False を返す。
    """
    threshold = _BUCKET_DISTANCE_KM[bucket]
    for accepted in accepted_in_bucket:
        if _haversine_km(candidate, accepted) <= threshold:
            return False
    return True


def _merge_anchors_and_search(
    anchors: list[PlacePoint],
    search_results: list[list[PlacePoint]],
    cap: int,
    total_days: int,
) -> list[PlacePoint]:
    """anchor + search 結果を bucket quota + 距離ガード + MIN_PLACES 補填で組み立てる。

    フロー（Phase 1.10 fix）:
    1. anchor を先頭に置く（user 明示意思、area filter / quota / 距離ガード bypass）
    2. search 結果を flatten、area filter で除外（anchor と重複も除外）
    3. bucket 分類 → quota 内採用（距離ガードを適用）、超過分は leftover に保留
    4. cap (MAX_PLACES) で打ち切り
    5. 第 2 段: 合計 < MIN_PLACES なら leftover から meal > other > attraction の順で補填
       （補填でも距離ガードは維持）
    """
    out: list[PlacePoint] = []
    seen_ids: set[str] = set()
    # anchors（area filter / quota / 距離ガード すべて bypass）
    for p in anchors:
        if p.place_id not in seen_ids:
            out.append(p)
            seen_ids.add(p.place_id)

    # search 結果を flatten + area filter + 既 seen 除外
    candidates: list[PlacePoint] = []
    for batch in search_results:
        for p in batch:
            if p.place_id in seen_ids:
                continue
            if _is_area_place(p):
                continue
            candidates.append(p)
            seen_ids.add(p.place_id)

    # Phase 3 polish (2026-04-28、iconic spot coverage 改善):
    # 各 bucket の quota 採用前に「人気度 = user_ratings_total × rating」で sort。
    # これによりガイドブック系 iconic spot (大涌谷の評価 5000+ 件 など) が、
    # 中規模 spot (飛竜の滝の評価 200 件 など) より優先採用される。
    # Google relevance ranking 任せでは「箱根 観光地」検索 top 10 に大涌谷が
    # 入らない事象 (実証済) を構造的に解消する。
    # Tie-break: rating のみ高い (件数少ない) 新店より、評価件数多い定番を優先。
    candidates.sort(
        key=lambda p: (
            (p.user_ratings_total or 0) * (p.rating or 0.0),
            p.user_ratings_total or 0,
        ),
        reverse=True,
    )

    quota = _bucket_quota(total_days)
    accepted_by_bucket: dict[str, list[PlacePoint]] = {b: [] for b in _BUCKET_OUTPUT_ORDER}
    leftover_by_bucket: dict[str, list[PlacePoint]] = {b: [] for b in _BUCKET_OUTPUT_ORDER}

    # 第 1 段: 各 bucket を quota まで採用
    for p in candidates:
        bucket = _classify_bucket(p)
        if len(accepted_by_bucket[bucket]) >= quota[bucket]:
            leftover_by_bucket[bucket].append(p)
            continue
        if not _distance_ok_for_bucket(p, accepted_by_bucket[bucket], bucket):
            leftover_by_bucket[bucket].append(p)
            continue
        accepted_by_bucket[bucket].append(p)

    # bucket 順序で out に追加
    for bucket in _BUCKET_OUTPUT_ORDER:
        for p in accepted_by_bucket[bucket]:
            if len(out) >= cap:
                return out[:cap]
            out.append(p)

    # 第 2 段: 補填閾値未満なら leftover から補填（meal > other > attraction、
    # 1 泊以上なら lodging も追加）。日帰りで lodging を補填しないのは「1 件入っても
    # plan に組み込めない」ため。
    # Phase 2 polish v4 (Codex review 1 Major 1 反映):
    # - 旧設計: fill_threshold = max(MIN_PLACES, cap - 3) で止めていたが、bucket 分布が
    #   偏ると 4 日 plan で実 pack が 19 で停止 → buffer 消失 →
    #   `_find_alternate_place exhausted` 再発リスク
    # - 新設計: 3 日以上は cap まで埋める（leftover が枯れた時点で自然停止）。
    #   1〜2 日 plan は MIN_PLACES (=12) で従来通り（4〜9 slot に対し十分なバッファ）。
    fill_order = (
        _BUCKET_FILL_ORDER_OVERNIGHT if total_days >= 2 else _BUCKET_FILL_ORDER_DAY_TRIP
    )
    fill_threshold = cap if total_days >= 3 else MIN_PLACES
    if len(out) < fill_threshold:
        for fill_bucket in fill_order:
            if len(out) >= fill_threshold or len(out) >= cap:
                break
            for p in leftover_by_bucket[fill_bucket]:
                if len(out) >= fill_threshold or len(out) >= cap:
                    break
                if not _distance_ok_for_bucket(
                    p, accepted_by_bucket[fill_bucket], fill_bucket
                ):
                    continue
                accepted_by_bucket[fill_bucket].append(p)
                out.append(p)

    return out[:cap]


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
