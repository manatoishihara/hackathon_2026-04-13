"""Evidence Pack Builder のユニットテスト（モック）と integration テスト。

Phase 1.2 では builder は transit_matrix を埋めない（フロントが Phase 1.3 で
Maps JS SDK から取得する）。places / budget / temporal / query_context の組み立て
のみ検証する。
"""

from __future__ import annotations

import os
from datetime import date
from unittest.mock import patch

import pytest

from src.evidence.builder import (
    _bucket_quota,
    _classify_bucket,
    _dedupe_and_cap,
    _distance_ok_for_bucket,
    _generate_keywords,
    _merge_anchors_and_search,
    build_evidence_pack,
)
from src.evidence.pack import LodgingOption, PlacePoint, QueryContext, QueryContextParticipant
from src.schemas import (
    BudgetBreakdown,
    GeneratePlanRequest,
    ParticipantInput,
)


def _sample_request(**overrides) -> GeneratePlanRequest:
    defaults: dict = dict(
        title="箱根温泉旅",
        region="箱根",
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 2),
        departure_point="新宿駅",
        budget_per_person_jpy=30000,
        budget_breakdown=BudgetBreakdown(lodging=40, meal=30, activity=20, transit=10),
        start_mode="auto",
        mode_payload=None,
        participants=[
            ParticipantInput(
                display_name="太郎",
                avatar_color="#D97757",
                wishes_text="ゆったり温泉に浸かりたい",
                tags=["温泉", "和食"],
                order_index=0,
            ),
            ParticipantInput(
                display_name="花子",
                avatar_color="#2C5F5D",
                wishes_text="美味しいもの食べたい",
                tags=["カフェ"],
                order_index=1,
            ),
        ],
    )
    defaults.update(overrides)
    return GeneratePlanRequest(**defaults)


def _place(
    place_id: str,
    name: str,
    lat: float,
    lng: float,
    *,
    category: list[str] | None = None,
) -> PlacePoint:
    return PlacePoint(
        place_id=place_id,
        name=name,
        category=category if category is not None else ["tourist_attraction"],
        lat=lat,
        lng=lng,
        address="神奈川県箱根町",
        opening_hours=[],
        price_level=None,
        rating=None,
        user_ratings_total=None,
    )


# ==============================
# キーワード生成
# ==============================


def _make_ctx(*, mode="auto", payload=None, tags_per_participant=None) -> QueryContext:
    """test 用 QueryContext factory（短縮）。"""
    if tags_per_participant is None:
        tags_per_participant = [[]]
    return QueryContext(
        region="箱根",
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 2),
        departure_point="新宿駅",
        start_mode=mode,
        mode_payload=payload,
        participants=[
            QueryContextParticipant(name=f"P{i}", wishes="w", tags=t)
            for i, t in enumerate(tags_per_participant)
        ],
    )


_BASE_AXES = [
    "箱根 観光地",
    "箱根 温泉",
    "箱根 神社 寺",
    "箱根 食事処",
    # Phase 3 polish 案 2 (2026-04-28、lodging keyword 細分化):
    # 旧「箱根 旅館 ホテル」(2 単語複合) を `旅館` / `ホテル` / `温泉宿` の 3 keyword
    # に分割。Google relevance ranking で各カテゴリ別に top-N を取れるように。
    "箱根 旅館",
    "箱根 ホテル",
    "箱根 温泉宿",
    "箱根 名所",  # Phase 3 polish (2026-04-28): iconic spot coverage 改善
]


def test_generate_keywords_auto_no_tags_returns_8_base_axes():
    """Phase 3 polish 案 2 (2026-04-28): 基本 8 軸を必ず投入。

    観光地 / 温泉 / 神社寺 / 食事処 / 旅館 / ホテル / 温泉宿 / 名所 の 8 軸。
    lodging keyword を 3 分割で多様性向上、楽天 API 未設定でも Google Places
    fallback で lodging 候補 5-10 件確保できる。
    """
    ctx = _make_ctx(tags_per_participant=[[]])
    keywords = _generate_keywords(ctx)
    assert keywords == _BASE_AXES


def test_generate_keywords_auto_with_unique_tag_appends_one():
    ctx = _make_ctx(tags_per_participant=[["写真映え"]])
    keywords = _generate_keywords(ctx)
    assert len(keywords) == 9
    assert "箱根 写真映え" in keywords
    # 基本 8 軸が先頭にある
    assert keywords[:8] == _BASE_AXES


def test_generate_keywords_auto_with_duplicate_tag_skips():
    ctx = _make_ctx(tags_per_participant=[["温泉"]])
    keywords = _generate_keywords(ctx)
    # 「箱根 温泉」は基本 8 軸に既に含まれるので tag からは追加されない
    assert len(keywords) == 8
    assert keywords.count("箱根 温泉") == 1


def test_generate_keywords_auto_caps_tag_at_one():
    ctx = _make_ctx(
        tags_per_participant=[["温泉", "和食", "写真映え", "茶道", "着物"]]
    )
    keywords = _generate_keywords(ctx)
    # 基本 8 軸 + tag 最大 1 個（"温泉" は重複 skip → "和食" が採用）
    assert len(keywords) == 9
    assert "箱根 和食" in keywords
    assert "箱根 写真映え" not in keywords  # 1 個目で打ち切り


def test_generate_keywords_theme_mode_adds_theme_words_within_cap():
    ctx = _make_ctx(
        mode="theme",
        payload={"theme": "onsen"},
        tags_per_participant=[[]],
    )
    keywords = _generate_keywords(ctx)
    # Phase 3 案 2: 基本 8 軸 + theme 語彙
    # onsen theme keywords = ["温泉", "露天風呂", "旅館"] のうち
    # 「温泉」「旅館」は基本 8 軸に含まれて skip、「露天風呂」だけ extra として追加。
    # 結果: 8 + 1 = 9 keywords (cap 10 内)
    assert len(keywords) == 9
    assert keywords[:8] == _BASE_AXES
    # 残り 1 件が theme 語彙 (重複 skip)
    extra = [k for k in keywords if k not in set(_BASE_AXES)]
    assert len(extra) == 1
    assert "箱根 露天風呂" in keywords


def test_generate_keywords_anchor_mode_returns_base_8_axes():
    ctx = _make_ctx(
        mode="anchor",
        payload={"anchor_place_ids": ["place_X"]},
        tags_per_participant=[[]],
    )
    keywords = _generate_keywords(ctx)
    # anchor mode でも基本 8 軸（anchor は別経路で fetch）
    assert keywords == _BASE_AXES


def test_generate_keywords_theme_with_tag_keeps_theme_word():
    """Codex review 2 Major 2 反映: theme + tag 入力で theme 語彙が tag より先に入る。

    Phase 3 案 2: cap _MAX_KEYWORDS=10。onsen theme keyword は base と 2 つ重複する
    ので extra=1 (露天風呂)、合計 9。tag は cap 10 内に余地があり、写真映え が入って
    最終的に 10 keyword。tag より theme が先に入る順序は維持される。
    """
    ctx = _make_ctx(
        mode="theme",
        payload={"theme": "onsen"},
        tags_per_participant=[["写真映え"]],
    )
    keywords = _generate_keywords(ctx)
    # 基本 8 軸 + theme 語彙 1 個 (露天風呂、温泉/旅館は重複 skip) + tag 1 個 = 10
    assert len(keywords) == 10
    assert "箱根 露天風呂" in keywords  # theme 残った 1 個
    assert "箱根 写真映え" in keywords  # tag は枠余地ありで入る
    # theme が tag より先に挿入される順序確認
    assert keywords.index("箱根 露天風呂") < keywords.index("箱根 写真映え")


def test_generate_keywords_max_10_regardless_of_input():
    """mode 別キーワード回帰: Phase 3 案 2 で _MAX_KEYWORDS=10 (8 base + theme + tag) に拡張。
    いかなる入力でも合計 10 を超えない。
    """
    for mode, payload in [
        ("auto", None),
        ("theme", {"theme": "onsen"}),
        ("anchor", {"anchor_place_ids": ["X", "Y"]}),
    ]:
        ctx = _make_ctx(
            mode=mode,
            payload=payload,
            tags_per_participant=[["温泉", "和食", "写真"]],
        )
        keywords = _generate_keywords(ctx)
        assert len(keywords) <= 10, f"{mode} mode produced {len(keywords)} keywords"


# =================================================================
# Phase 1.10 fix: bucket 分類 + quota + 距離ガード + MIN_PLACES 補填
# (tasks/plans/2026-04-26-evidence-pack-diversity.md)
# =================================================================


def test_classify_bucket_lodging_takes_priority_over_attraction():
    """混合 category で lodging が attraction より優先されることを確認（Codex review 2 Minor 1 反映、
    `tourist_attraction` (attraction allowlist) と `lodging` の真の競合を test）。"""
    place = _place(
        "p_onsen_ryokan",
        "温泉旅館",
        0,
        0,
        category=["lodging", "tourist_attraction"],
    )
    assert _classify_bucket(place) == "lodging"


def test_classify_bucket_lodging_takes_priority_over_meal():
    place = _place("p_hotel_with_restaurant", "ホテル", 0, 0, category=["lodging", "restaurant"])
    assert _classify_bucket(place) == "lodging"


def test_classify_bucket_attraction_when_no_lodging():
    place = _place("p_museum", "美術館", 0, 0, category=["museum", "tourist_attraction"])
    assert _classify_bucket(place) == "attraction"


def test_classify_bucket_attraction_with_meal_returns_attraction():
    """lodging なし、attraction と meal 両方 → attraction が勝つ。"""
    place = _place("p_park_cafe", "公園内カフェ", 0, 0, category=["park", "cafe"])
    assert _classify_bucket(place) == "attraction"


def test_classify_bucket_temple_via_place_of_worship():
    place = _place("p_temple", "寺", 0, 0, category=["place_of_worship", "tourist_attraction"])
    assert _classify_bucket(place) == "attraction"


def test_classify_bucket_meal_via_restaurant():
    place = _place("p_restaurant", "和食店", 0, 0, category=["restaurant", "food"])
    assert _classify_bucket(place) == "meal"


def test_classify_bucket_meal_via_restaurant_suffix():
    """`*_restaurant` 接尾辞（japanese_restaurant 等）で meal 判定。"""
    place = _place("p_yakiniku", "焼肉", 0, 0, category=["yakiniku_restaurant", "food"])
    assert _classify_bucket(place) == "meal"


def test_classify_bucket_lodging_via_ryokan():
    place = _place("p_ryokan", "旅館", 0, 0, category=["ryokan"])
    assert _classify_bucket(place) == "lodging"


def test_classify_bucket_other_for_unknown_category():
    place = _place("p_mall", "ショッピング", 0, 0, category=["shopping_mall"])
    assert _classify_bucket(place) == "other"


def test_classify_bucket_other_for_empty_category():
    place = _place("p_unknown", "unknown", 0, 0, category=[])
    assert _classify_bucket(place) == "other"


# --- _bucket_quota ---


def test_bucket_quota_day_trip_zero_lodging():
    quota = _bucket_quota(1)
    assert quota["lodging"] == 0
    assert sum(quota.values()) == 15


def test_bucket_quota_one_night():
    """Phase 3 polish 案 1 (2026-04-28): lodging quota +1 増量で multi-night plan の
    `item_type_category_mismatch` を緩和。1 泊 plan は 1→2 に増。"""
    quota = _bucket_quota(2)
    assert quota["lodging"] == 2
    assert sum(quota.values()) == 15


def test_bucket_quota_two_nights():
    """Phase 3 polish 案 1 (2026-04-28): 3 日 plan の lodging quota を 2 → 3 に増量。
    LLM が lodging slot に spa/restaurant 系を選ぶ問題対策で pack 候補を厚くする。
    合計は 17 維持 (attraction 7 → 6 でバランス)。"""
    quota = _bucket_quota(3)
    assert quota["lodging"] == 3
    assert quota["attraction"] == 6
    assert quota["meal"] == 6
    assert sum(quota.values()) == 17


def test_bucket_quota_three_nights_phase3():
    """Phase 3 polish 案 1: 4 日 plan の lodging quota を 3 → 4 に増量、合計 22 places 維持。"""
    quota = _bucket_quota(4)
    assert quota["lodging"] == 4
    assert quota["attraction"] == 8
    assert quota["meal"] == 8
    assert sum(quota.values()) == 22


def test_bucket_quota_five_days_phase3():
    """Phase 3 polish 案 1: 5 日 plan の lodging quota を 4 → 5 に増量。

    Codex review 1 Major 2 反映: max_places_for(total_days) と sum(quota.values()) の
    contract 一致を保証する。
    """
    from src.evidence.builder import max_places_for
    quota = _bucket_quota(5)
    assert quota["lodging"] == 5
    assert quota["attraction"] == 10
    assert quota["meal"] == 10
    # 残差 = max_places_for(5) - (10+10+5) = 27 - 25 = 2 が other に入る
    assert quota["other"] == 2
    assert sum(quota.values()) == max_places_for(5)


def test_bucket_quota_contract_matches_max_places_for_all_days():
    """Codex review 1 Major 2: total_days 1〜7 で sum(quota) == max_places_for(td)。"""
    from src.evidence.builder import max_places_for
    for td in range(1, 8):
        quota = _bucket_quota(td)
        assert sum(quota.values()) == max_places_for(td), (
            f"contract mismatch at total_days={td}: "
            f"sum={sum(quota.values())} max_places_for={max_places_for(td)}"
        )


# --- max_places_for（Phase 2 polish v4: total_days 依存の cap）---


def test_max_places_for_short_trips_keeps_15():
    """1〜2 日 plan は cap=15 維持 (4〜9 slot に対し十分なバッファ)。"""
    from src.evidence.builder import max_places_for
    assert max_places_for(1) == 15
    assert max_places_for(2) == 15


def test_max_places_for_three_days_returns_17():
    """3 日 plan: 14 slot + 3 buffer = 17。"""
    from src.evidence.builder import max_places_for
    assert max_places_for(3) == 17


def test_max_places_for_four_days_returns_22():
    """4 日 plan: 19 slot + 3 buffer = 22 (本番 Run 13d 失敗の根本対応)。"""
    from src.evidence.builder import max_places_for
    assert max_places_for(4) == 22


def test_max_places_for_five_days_returns_27():
    """5 日 plan: 24 slot + 3 buffer = 27。"""
    from src.evidence.builder import max_places_for
    assert max_places_for(5) == 27


# --- _distance_ok_for_bucket（bucket 別境界、Codex Major 5）---


def test_distance_ok_meal_bucket_excludes_at_threshold():
    """meal bucket の距離閾値 300m。同距離の境界以下は skip（<=）。"""
    a = _place("p_a", "A", 35.2, 139.0)
    # 緯度 0.001° ≒ 111m
    near = _place("p_near", "near", 35.2 + 0.0024, 139.0)  # ~267m → skip
    far = _place("p_far", "far", 35.2 + 0.0030, 139.0)  # ~334m → ok
    assert _distance_ok_for_bucket(near, [a], "meal") is False
    assert _distance_ok_for_bucket(far, [a], "meal") is True


def test_distance_ok_attraction_bucket_uses_150m_threshold():
    """attraction bucket は 150m。施設内 spots を許容する。"""
    a = _place("p_a", "A", 35.2, 139.0)
    inside = _place("p_inside", "inside", 35.2 + 0.0014, 139.0)  # ~155m → OK
    too_close = _place("p_too", "too", 35.2 + 0.0010, 139.0)  # ~111m → skip
    assert _distance_ok_for_bucket(inside, [a], "attraction") is True
    assert _distance_ok_for_bucket(too_close, [a], "attraction") is False


def test_distance_ok_lodging_bucket_uses_500m_threshold():
    """lodging は 500m で分散重視。"""
    a = _place("p_a", "A", 35.2, 139.0)
    near = _place("p_near", "near", 35.2 + 0.004, 139.0)  # ~444m → skip
    far = _place("p_far", "far", 35.2 + 0.005, 139.0)  # ~555m → OK
    assert _distance_ok_for_bucket(near, [a], "lodging") is False
    assert _distance_ok_for_bucket(far, [a], "lodging") is True


def test_distance_ok_returns_true_for_empty_accepted():
    a = _place("p_a", "A", 35.2, 139.0)
    assert _distance_ok_for_bucket(a, [], "meal") is True


def test_distance_ok_strict_threshold_via_haversine_mock(monkeypatch):
    """Codex review 2 Minor 2 反映: `<=` 境界の厳密 test。
    haversine をモックして閾値 ちょうど / +微小 / -微小 を直接検証。
    """
    from src.evidence import builder as builder_mod

    a = _place("p_a", "A", 0, 0)
    b = _place("p_b", "B", 0, 0)

    # meal threshold = 0.30 km
    monkeypatch.setattr(builder_mod, "_haversine_km", lambda x, y: 0.30)
    assert _distance_ok_for_bucket(b, [a], "meal") is False  # ちょうど境界 → skip

    monkeypatch.setattr(builder_mod, "_haversine_km", lambda x, y: 0.30001)
    assert _distance_ok_for_bucket(b, [a], "meal") is True  # 境界 +ε → ok

    monkeypatch.setattr(builder_mod, "_haversine_km", lambda x, y: 0.29999)
    assert _distance_ok_for_bucket(b, [a], "meal") is False  # 境界 -ε → skip

    # attraction threshold = 0.15 km
    monkeypatch.setattr(builder_mod, "_haversine_km", lambda x, y: 0.15)
    assert _distance_ok_for_bucket(b, [a], "attraction") is False
    monkeypatch.setattr(builder_mod, "_haversine_km", lambda x, y: 0.15001)
    assert _distance_ok_for_bucket(b, [a], "attraction") is True

    # lodging threshold = 0.50 km
    monkeypatch.setattr(builder_mod, "_haversine_km", lambda x, y: 0.50)
    assert _distance_ok_for_bucket(b, [a], "lodging") is False
    monkeypatch.setattr(builder_mod, "_haversine_km", lambda x, y: 0.50001)
    assert _distance_ok_for_bucket(b, [a], "lodging") is True


# --- _merge_anchors_and_search（quota + 距離ガード + 補填）---


def _spread(prefix: str, n: int, lat0: float, bucket_cat: list[str]) -> list[PlacePoint]:
    """同 bucket でも距離ガードに引っかからない 1km 間隔の places を生成。"""
    return [
        _place(
            f"{prefix}{i}",
            f"{prefix}{i}",
            lat0 + 0.01 * i,  # 約 1.1km 刻み
            139.0,
            category=bucket_cat,
        )
        for i in range(n)
    ]


def test_merge_full_buckets_at_two_nights():
    """Phase 3 polish 案 1: 2 泊 (total_days=3) の bucket quota が
    attraction 6 / meal 6 / lodging 3 / other 2 = 17 になっていることを確認。"""
    attractions = _spread("a", 10, 35.0, ["tourist_attraction"])
    meals = _spread("m", 10, 36.0, ["restaurant"])
    lodgings = _spread("l", 5, 37.0, ["lodging"])
    others = _spread("o", 5, 38.0, ["shopping_mall"])
    out = _merge_anchors_and_search(
        anchors=[],
        search_results=[attractions, meals, lodgings, others],
        cap=17,  # max_places_for(3) = 17
        total_days=3,
    )
    assert len(out) == 17
    buckets = [_classify_bucket(p) for p in out]
    assert buckets.count("attraction") == 6
    assert buckets.count("meal") == 6
    assert buckets.count("lodging") == 3
    assert buckets.count("other") == 2


def test_merge_4day_lodging_short_buffers_filled_to_cap():
    """Codex review 1 Major 1: 4 日 plan で lodging 候補が quota 未満でも、
    leftover の attraction/meal で fill_threshold=cap まで埋めて buffer 確保する。

    旧設計 (fill_threshold=cap-3) では bucket 偏りで pack が 19 で停止 →
    `_find_alternate_place exhausted` 再発。本 fix で 22 まで埋まる。
    """
    from src.evidence.builder import max_places_for
    # 4 日 plan で lodging quota=3 だが 1 件しか候補なし、attraction/meal は余裕あり
    attractions = _spread("a", 15, 35.0, ["tourist_attraction"])
    meals = _spread("m", 15, 36.0, ["restaurant"])
    lodgings = _spread("l", 1, 37.0, ["lodging"])
    others = _spread("o", 5, 38.0, ["shopping_mall"])
    cap = max_places_for(4)  # 22
    out = _merge_anchors_and_search(
        anchors=[],
        search_results=[attractions, meals, lodgings, others],
        cap=cap,
        total_days=4,
    )
    # cap=22 まで補填されることを確認 (旧設計だと 19 で停止)
    assert len(out) == cap, (
        f"fill_threshold=cap で bucket 偏りでも cap まで埋まる必要あり (got {len(out)})"
    )


def test_merge_day_trip_zero_lodging_quota():
    """日帰り (total_days=1) で lodging が 0 件、attraction/meal が増える。"""
    attractions = _spread("a", 10, 35.0, ["tourist_attraction"])
    meals = _spread("m", 10, 36.0, ["restaurant"])
    lodgings = _spread("l", 5, 37.0, ["lodging"])
    others = _spread("o", 5, 38.0, ["shopping_mall"])
    out = _merge_anchors_and_search(
        anchors=[],
        search_results=[attractions, meals, lodgings, others],
        cap=15,
        total_days=1,
    )
    buckets = [_classify_bucket(p) for p in out]
    assert buckets.count("lodging") == 0
    assert buckets.count("attraction") == 7
    assert buckets.count("meal") == 6


def test_merge_min_places_fill_when_attraction_short():
    """observation 不足時、MIN_PLACES=12 まで meal/other/attraction の余りで補填。

    Phase 3 polish 案 1 で total_days=2 の lodging quota が 1 → 2 に増えたので、
    baseline 計算: attraction 3 + meal 5 + lodging 2 + other 2 = 12、すでに MIN_PLACES に
    到達するので補填路は走らない (旧設計では baseline 11 で補填 1 件、今は不要)。
    """
    # attraction は 1 件のみ、meal/other/lodging は余裕
    attractions = _spread("a", 1, 35.0, ["tourist_attraction"])
    meals = _spread("m", 10, 36.0, ["restaurant"])
    lodgings = _spread("l", 3, 37.0, ["lodging"])
    others = _spread("o", 5, 38.0, ["shopping_mall"])
    out = _merge_anchors_and_search(
        anchors=[],
        search_results=[attractions, meals, lodgings, others],
        cap=15,
        total_days=2,
    )
    # baseline 採用 = attraction 1 + meal 5 + lodging 2 + other 2 = 10、補填で >=12 に
    assert len(out) >= 12
    buckets = [_classify_bucket(p) for p in out]
    # 補填は meal が最初、distance ok の余りから 1 件以上採用
    assert buckets.count("meal") >= 6 or buckets.count("other") >= 3


def test_merge_distance_guard_blocks_clustered_meals():
    """同一 100m 圏の飲食店 5 件 → 距離ガードで 1 件のみ採用（Run 7 修正の再現テスト）。"""
    cluster = [
        _place(f"m{i}", f"meal{i}", 35.2 + 0.0001 * i, 139.0, category=["restaurant"])
        for i in range(5)
    ]
    # 補完用に距離離れた places を入れて MIN_PLACES に届くようにする
    far_meals = _spread("fm", 5, 36.0, ["restaurant"])
    far_attractions = _spread("a", 6, 37.0, ["tourist_attraction"])
    out = _merge_anchors_and_search(
        anchors=[],
        search_results=[cluster, far_meals, far_attractions],
        cap=15,
        total_days=2,
    )
    cluster_ids_in_out = [p.place_id for p in out if p.place_id.startswith("m")]
    assert len(cluster_ids_in_out) == 1  # クラスターから 1 件のみ採用


def test_merge_anchor_bypasses_quota_and_distance_guard():
    """anchor は quota / 距離ガード bypass、search 結果は通常通り。"""
    anchor1 = _place("anchor1", "A1", 35.2, 139.0, category=["tourist_attraction"])
    anchor2 = _place("anchor2", "A2", 35.20001, 139.0, category=["tourist_attraction"])  # 100m 以内
    attractions = _spread("a", 10, 35.0, ["tourist_attraction"])
    out = _merge_anchors_and_search(
        anchors=[anchor1, anchor2],
        search_results=[attractions],
        cap=15,
        total_days=2,
    )
    out_ids = [p.place_id for p in out]
    assert "anchor1" in out_ids
    assert "anchor2" in out_ids
    # anchor が先頭、anchor 同士の距離ガードはなし
    assert out_ids[:2] == ["anchor1", "anchor2"]


def test_merge_anchor_search_dedupe():
    """anchor と search に同一 place_id があれば search 側を重複として無視。"""
    place_x = _place("X", "X", 35.0, 139.0, category=["tourist_attraction"])
    out = _merge_anchors_and_search(
        anchors=[place_x],
        search_results=[[place_x]],
        cap=15,
        total_days=2,
    )
    assert len(out) == 1
    assert out[0].place_id == "X"


def test_merge_area_filter_applied_only_to_search():
    """area filter は search 結果側のみ。anchor は bypass。"""
    locality_anchor = _place(
        "loc", "箱根町", 0, 0, category=["locality", "political"]
    )
    locality_search = _place(
        "loc_s", "箱根町_search", 0, 0, category=["locality", "political"]
    )
    spot = _place("spot", "観光地", 35.5, 139.5, category=["tourist_attraction"])
    out = _merge_anchors_and_search(
        anchors=[locality_anchor],  # anchor は filter bypass
        search_results=[[locality_search, spot]],  # locality_search は除外
        cap=15,
        total_days=2,
    )
    out_ids = [p.place_id for p in out]
    assert "loc" in out_ids
    assert "loc_s" not in out_ids
    assert "spot" in out_ids


def test_merge_lodging_only_input_overnight_fills_to_min_places():
    """Codex review 2 Major 1 反映: lodging だけ大量にある場合、1 泊以上なら lodging を補填して >= MIN_PLACES。"""
    lodgings = _spread("l", 20, 35.0, ["lodging"])
    out = _merge_anchors_and_search(
        anchors=[],
        search_results=[lodgings],
        cap=15,
        total_days=2,  # 1 泊なので lodging 補填が有効
    )
    # baseline lodging quota=1、補填で MIN_PLACES=12 まで lodging 採用
    assert len(out) >= 12
    assert all(_classify_bucket(p) == "lodging" for p in out)


def test_merge_lodging_only_input_day_trip_does_not_fill_lodging():
    """日帰りのときは lodging 補填しない（plan に組み込めないため）。"""
    lodgings = _spread("l", 20, 35.0, ["lodging"])
    out = _merge_anchors_and_search(
        anchors=[],
        search_results=[lodgings],
        cap=15,
        total_days=1,
    )
    # 日帰り quota=0、補填も lodging 対象外 → 0 件
    assert len(out) == 0


def test_merge_caps_at_max_places():
    """cap=MAX_PLACES=15 を超えない。全 bucket 余裕あり (others 含む)。"""
    attractions = _spread("a", 20, 35.0, ["tourist_attraction"])
    meals = _spread("m", 20, 36.0, ["restaurant"])
    lodgings = _spread("l", 20, 37.0, ["lodging"])
    others = _spread("o", 20, 38.0, ["shopping_mall"])
    out = _merge_anchors_and_search(
        anchors=[],
        search_results=[attractions, meals, lodgings, others],
        cap=15,
        total_days=3,
    )
    assert len(out) == 15


def test_merge_sorts_candidates_by_popularity_before_quota_assignment():
    """Phase 3 polish (2026-04-28、iconic spot coverage 改善):

    各 bucket の quota 採用前に candidates を `user_ratings_total × rating` で sort。
    これによりガイドブック系 iconic spot (review 5000+ 件) が中規模 spot
    (review 200 件) より優先採用される。

    setup: 同 bucket attraction で 2 件、片方は超人気 (大涌谷 想定、
    rating 4.5 × 5000 reviews)、もう片方は中規模 (飛竜の滝 想定、4.0 × 200 reviews)。
    quota=1 のときに人気の方が採用されることを確認。
    """
    iconic = PlacePoint(
        place_id="iconic_spot",
        name="大涌谷 (iconic)",
        category=["tourist_attraction"],
        lat=35.0, lng=139.0,
        address="箱根町",
        opening_hours=[],
        price_level=None,
        rating=4.5,
        user_ratings_total=5000,
    )
    medium = PlacePoint(
        place_id="medium_spot",
        name="飛竜の滝 (medium)",
        category=["tourist_attraction"],
        lat=36.0, lng=139.0,  # 距離ガード回避のため離す
        address="箱根町",
        opening_hours=[],
        price_level=None,
        rating=4.0,
        user_ratings_total=200,
    )
    # search_results 順序として medium が先、iconic が後 (Google relevance ranking で
    # iconic が下位に来るケースを模擬)。post-rank sort なしだと medium が先採用される。
    # post-rank sort ありなら iconic が先採用される。
    out = _merge_anchors_and_search(
        anchors=[],
        search_results=[[medium, iconic]],
        cap=1,
        total_days=2,
    )
    assert len(out) == 1
    assert out[0].place_id == "iconic_spot", (
        "post-rank sort で人気度上位 (user_ratings_total × rating) が先に採用されるべき"
    )


def test_merge_sort_handles_missing_rating_or_count():
    """Phase 3 polish: rating / user_ratings_total が None の place は最下位扱い。

    Google Places API で評価データが取れない place (新規店舗等) は人気度 sort で
    末尾に配置される。逆順 sort なので (None or 0) * (None or 0.0) = 0 で最下位。
    """
    rated = PlacePoint(
        place_id="rated",
        name="評価あり",
        category=["tourist_attraction"],
        lat=35.0, lng=139.0,
        address="箱根町",
        opening_hours=[],
        price_level=None,
        rating=3.5,
        user_ratings_total=100,
    )
    unrated = PlacePoint(
        place_id="unrated",
        name="評価なし",
        category=["tourist_attraction"],
        lat=36.0, lng=139.0,
        address="箱根町",
        opening_hours=[],
        price_level=None,
        rating=None,
        user_ratings_total=None,
    )
    out = _merge_anchors_and_search(
        anchors=[],
        search_results=[[unrated, rated]],
        cap=1,
        total_days=2,
    )
    assert len(out) == 1
    assert out[0].place_id == "rated", (
        "評価データありの place が None の place より優先されるべき"
    )


# ==============================
# Dedupe + cap
# ==============================


def test_dedupe_preserves_first_occurrence():
    batch_a = [_place("p1", "A", 0, 0), _place("p2", "B", 0, 0)]
    batch_b = [_place("p2", "B-dup", 0, 0), _place("p3", "C", 0, 0)]
    unique = _dedupe_and_cap([batch_a, batch_b], cap=10)
    ids = [p.place_id for p in unique]
    assert ids == ["p1", "p2", "p3"]
    assert unique[1].name == "B"


def test_dedupe_caps_total_count():
    batches = [[_place(f"p{i}", str(i), 0, 0) for i in range(20)]]
    unique = _dedupe_and_cap(batches, cap=5)
    assert len(unique) == 5


def test_dedupe_excludes_area_categories():
    """Phase 1.3e: area 系 category（locality / colloquial_area / political /
    administrative_area_*）は plan item にできない（specific spot ではなく region 名で
    opening_hours も無い）ため、pack 構築時に除外する。

    実例: Places API は region 名 query で「箱根町（locality）」「箱根温泉（colloquial_area）」
    を返すが、これらが pack に入ると LLM が slot に充てて自己ループの origin になり
    `unknown_transit_edge` で詰む（@tasks/lessons.md 2026-04-25 診断）。
    """
    batches = [
        [
            _place("p_spot", "観光地", 0, 0, category=["tourist_attraction"]),
            _place("p_locality", "箱根町", 0, 0, category=["locality", "political"]),
            _place(
                "p_colloquial",
                "箱根温泉",
                0,
                0,
                category=["colloquial_area", "establishment"],
            ),
            _place(
                "p_admin",
                "神奈川県",
                0,
                0,
                category=["administrative_area_level_1"],
            ),
            _place("p_food", "和食店", 0, 0, category=["japanese_restaurant"]),
        ]
    ]
    unique = _dedupe_and_cap(batches, cap=10)
    ids = [p.place_id for p in unique]
    assert "p_spot" in ids
    assert "p_food" in ids
    # area 系は除外
    assert "p_locality" not in ids
    assert "p_colloquial" not in ids
    assert "p_admin" not in ids
    assert len(unique) == 2


def test_dedupe_keeps_place_with_secondary_area_tag_if_primary_is_specific():
    """`category[0]` が specific な場合、secondary に area tag が混じっていても残す。

    例: Google Places は商業施設に `establishment` / `point_of_interest` の generic tag を
    必ず付ける。これらは除外対象にしない。除外は **primary（category[0]）が area 系** の
    時のみ作用する。
    """
    batches = [
        [
            _place(
                "p_mixed",
                "ホテル",
                0,
                0,
                category=["lodging", "establishment", "point_of_interest"],
            ),
        ]
    ]
    unique = _dedupe_and_cap(batches, cap=10)
    assert [p.place_id for p in unique] == ["p_mixed"]


# ==============================
# build_evidence_pack（places のみ、transit はフロント側で後埋め）
# ==============================


@patch("src.evidence.builder._fetch_lodging_safe")
@patch("src.evidence.builder.search_by_text")
def test_build_evidence_pack_assembles_structure(mock_search, mock_lodging):
    """Phase 3 polish 案 D 第 2 段 (2026-04-28): 楽天 lodging を pack.places に
    forced 注入する変更後、本 test は楽天 API を mock してフラットなフィクスチャ環境で
    pack.places の純粋な search 結果のみを検証する。
    """
    mock_search.return_value = [
        _place("p1", "箱根神社", 35.20, 139.02),
        _place("p2", "箱根湯本駅", 35.23, 139.10),
    ]
    # 楽天 lodging は本 test の責務外なので空で mock (本 fetch logic は test_lodging.py)
    mock_lodging.return_value = []

    req = _sample_request()
    pack = build_evidence_pack(req)

    # query_context
    assert pack.query_context.region == "箱根"
    assert len(pack.query_context.participants) == 2

    # places: 5 キーワード × 2 スポット = 10、dedupe で 2 つに
    assert len(pack.places) == 2
    assert {p.place_id for p in pack.places} == {"p1", "p2"}

    # transit_matrix: Phase 1.2 では常に空（フロントが埋める）
    assert pack.transit_matrix == []

    # budget: 30000 × 40/30/20/10 = 12000/9000/6000/3000
    assert pack.budget_constraints.total_jpy_per_person == 30000
    assert pack.budget_constraints.breakdown_jpy.lodging == 12000
    assert pack.budget_constraints.breakdown_jpy.meal == 9000
    assert pack.budget_constraints.breakdown_jpy.activity == 6000
    assert pack.budget_constraints.breakdown_jpy.transit == 3000

    # temporal: 2 日間
    assert pack.temporal_constraints.total_days == 2
    assert pack.temporal_constraints.start_datetime.hour == 9


@patch("src.evidence.builder.search_by_text")
def test_search_failure_does_not_abort_build(mock_search):
    """Places API の 1 クエリが失敗しても他のクエリは続行する（fail-soft）。"""
    from src.evidence.places import PlacesError

    call_count = {"n": 0}

    def search_side_effect(query: str):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise PlacesError("network error on keyword 2")
        return [_place(f"p{call_count['n']}", query, 35.0 + call_count["n"] * 0.001, 139.0)]

    mock_search.side_effect = search_side_effect

    req = _sample_request()
    pack = build_evidence_pack(req)

    assert len(pack.places) >= 1
    assert pack.transit_matrix == []


@patch("src.evidence.builder._fetch_lodging_safe")
@patch("src.evidence.builder.search_by_text")
def test_all_searches_failing_still_returns_pack(mock_search, mock_lodging):
    """全 Places クエリが失敗しても、空 places で pack は返る（LLM 側で空処理可）。

    Phase 3 polish 案 D 第 2 段 (2026-04-28): 楽天 lodging も pack.places に
    forced 注入されるので本 test は楽天も空で mock。
    """
    from src.evidence.places import PlacesError

    mock_search.side_effect = PlacesError("everything broken")
    mock_lodging.return_value = []
    pack = build_evidence_pack(_sample_request())
    assert pack.places == []
    assert pack.transit_matrix == []
    # budget/temporal は Places の成否と無関係に計算される
    assert pack.budget_constraints.total_jpy_per_person == 30000


# ==============================
# Phase 3 polish 案 D 第 2 段: 楽天 lodging を pack.places に forced 注入
# (2026-04-28)
# ==============================


@patch("src.evidence.builder._fetch_lodging_safe")
@patch("src.evidence.builder.search_by_text")
def test_rakuten_lodging_injected_into_pack_places(mock_search, mock_lodging):
    """Phase 3 polish 案 D 第 2 段: 楽天 fetch 結果が PlacePoint 化されて pack.places
    の先頭 (anchor 同等扱い) に注入される。LLM の slot 候補に登場させるための再設計。

    Before: 楽天 lodging は pack.lodging_options にのみ入り pack.places に居なかったため
    LLM プロンプトの slot 候補から落ちて plan に楽天宿が出ない構造的問題があった。
    """
    mock_search.return_value = [
        _place("p1", "箱根神社", 35.20, 139.02),
        _place("p2", "箱根湯本駅", 35.23, 139.10),
    ]
    mock_lodging.return_value = [
        LodgingOption(
            place_id="rakuten_12345",
            name="箱根温泉旅館 テスト館",
            price_jpy_per_night=15000,
            lat=35.23,
            lng=139.10,
            url="https://travel.rakuten.co.jp/hotel/12345/",
        ),
        LodgingOption(
            place_id="rakuten_67890",
            name="箱根ホテル",
            price_jpy_per_night=20000,
            lat=35.24,
            lng=139.05,
            url="https://travel.rakuten.co.jp/hotel/67890/",
        ),
    ]

    pack = build_evidence_pack(_sample_request())

    # 楽天 lodging が pack.places に登場している (LLM slot 候補に届く)
    rakuten_in_places = [p for p in pack.places if p.place_id.startswith("rakuten_")]
    assert len(rakuten_in_places) == 2
    assert {p.place_id for p in rakuten_in_places} == {"rakuten_12345", "rakuten_67890"}

    # category は固定で lodging 系 (LLM が lodging slot で識別可能)
    for p in rakuten_in_places:
        assert "lodging" in p.category
        assert "hotel" in p.category

    # opening_hours_unknown_days 全曜日 (lodging は 24h 営業仮定で eligibility skip)
    for p in rakuten_in_places:
        assert set(p.opening_hours_unknown_days) == {0, 1, 2, 3, 4, 5, 6}

    # pack.lodging_options も維持 (将来の表示拡張・bookings 機能用)
    assert pack.lodging_options is not None
    assert len(pack.lodging_options) == 2


@patch("src.evidence.builder._fetch_lodging_safe")
@patch("src.evidence.builder.search_by_text")
def test_rakuten_lodging_empty_does_not_break_pack(mock_search, mock_lodging):
    """楽天 fetch 0 件 (env 未設定 / API 失敗) でも pack 構築は続行 (fail-soft)。"""
    mock_search.return_value = [
        _place("p1", "箱根神社", 35.20, 139.02),
    ]
    mock_lodging.return_value = []

    pack = build_evidence_pack(_sample_request())
    # 楽天 0 件でも Google Places は pack.places に入る
    assert len(pack.places) == 1
    assert pack.places[0].place_id == "p1"
    # lodging_options は None (空のとき)
    assert pack.lodging_options is None


# Phase 3 polish 案 D 第 8 段 (2026-04-28、楽天 only 方針)
# ==============================


@patch("src.evidence.builder._fetch_lodging_safe")
@patch("src.evidence.builder.search_by_text")
def test_rakuten_only_when_present_excludes_google_lodging(mock_search, mock_lodging):
    """Phase 3 polish 案 D 第 8 段: 楽天 lodging が 1 件以上取れたとき、Google Places の
    lodging は pack から完全排除される。LLM が複合カテゴリ Google hotel を meal slot に
    誤選する事故を構造的に防ぐため。
    """
    google_hotel = _place(
        "google_hotel_1", "Google ホテル箱根", 35.21, 139.03, category=["lodging", "hotel"],
    )
    google_attraction = _place(
        "google_park", "箱根強羅公園", 35.25, 139.04, category=["tourist_attraction", "park"],
    )
    google_restaurant = _place(
        "google_meal", "そば処", 35.22, 139.06, category=["restaurant", "food"],
    )
    mock_search.return_value = [google_hotel, google_attraction, google_restaurant]
    mock_lodging.return_value = [
        LodgingOption(
            place_id="rakuten_55555",
            name="楽天宿テスト",
            price_jpy_per_night=15000,
            lat=35.23,
            lng=139.10,
            url="https://travel.rakuten.co.jp/hotel/55555/",
            rating=4.5,
        ),
    ]

    pack = build_evidence_pack(_sample_request())
    place_ids = {p.place_id for p in pack.places}

    # 楽天宿は pack に入る
    assert "rakuten_55555" in place_ids
    # Google Places の lodging は排除される (本対策の核心)
    assert "google_hotel_1" not in place_ids
    # attraction / meal は維持
    assert "google_park" in place_ids
    assert "google_meal" in place_ids


@patch("src.evidence.builder._fetch_lodging_safe")
@patch("src.evidence.builder.search_by_text")
def test_rakuten_zero_keeps_google_lodging_as_fallback(mock_search, mock_lodging):
    """Phase 3 polish 案 D 第 8 段: 楽天 0 件 (env 未設定 / API 障害 / 検索範囲外) の
    ときは Google Places の lodging を pack に残す fallback で demo blocker を回避。
    """
    google_hotel = _place(
        "google_hotel_1", "Google ホテル箱根", 35.21, 139.03, category=["lodging", "hotel"],
    )
    google_attraction = _place(
        "google_park", "箱根強羅公園", 35.25, 139.04, category=["tourist_attraction"],
    )
    mock_search.return_value = [google_hotel, google_attraction]
    mock_lodging.return_value = []  # 楽天 0 件

    pack = build_evidence_pack(_sample_request())
    place_ids = {p.place_id for p in pack.places}

    # 楽天 0 件のときは Google Places lodging が fallback で残る
    assert "google_hotel_1" in place_ids
    assert "google_park" in place_ids
    # 楽天は当然存在しない
    assert not any(pid.startswith("rakuten_") for pid in place_ids)


@patch("src.evidence.builder._fetch_lodging_safe")
@patch("src.evidence.builder.search_by_text")
def test_rakuten_only_keeps_attraction_meal_other_buckets(mock_search, mock_lodging):
    """Phase 3 polish 案 D 第 8 段: 楽天 only モード時も attraction / meal / other の
    bucket は Google Places で従来通り埋まる (lodging だけが楽天で占有)。
    """
    # 各 bucket に十分な candidate を用意
    attractions = [
        _place(f"a{i}", f"観光地{i}", 35.20 + 0.01 * i, 139.02, category=["tourist_attraction"])
        for i in range(5)
    ]
    meals = [
        _place(f"m{i}", f"食事{i}", 35.30 + 0.01 * i, 139.05, category=["restaurant"])
        for i in range(5)
    ]
    google_hotel = _place(
        "google_h1", "Google ホテル", 35.21, 139.03, category=["lodging", "hotel"],
    )
    mock_search.return_value = attractions + meals + [google_hotel]
    mock_lodging.return_value = [
        LodgingOption(
            place_id="rakuten_99999",
            name="楽天 only テスト宿",
            price_jpy_per_night=12000,
            lat=35.23,
            lng=139.10,
            rating=4.0,
        ),
    ]

    pack = build_evidence_pack(_sample_request())
    place_ids = {p.place_id for p in pack.places}

    # 楽天宿は入る、Google hotel は排除
    assert "rakuten_99999" in place_ids
    assert "google_h1" not in place_ids
    # attraction / meal は Google Places で残る
    google_attraction_ids = [p.place_id for p in pack.places if p.place_id.startswith("a")]
    google_meal_ids = [p.place_id for p in pack.places if p.place_id.startswith("m")]
    assert len(google_attraction_ids) > 0, "attraction bucket は Google Places で残るべき"
    assert len(google_meal_ids) > 0, "meal bucket は Google Places で残るべき"


def test_lodging_to_place_point_conversion():
    """_lodging_to_place_point が LodgingOption → PlacePoint に正しく変換することを単体検証。

    Phase 3 polish 案 D 第 3 段 (2026-04-28): rating + price_level も引き継がれる。
    """
    from src.evidence.builder import _lodging_to_place_point

    lo = LodgingOption(
        place_id="rakuten_99999",
        name="変換テスト旅館",
        price_jpy_per_night=12000,
        lat=35.5,
        lng=139.5,
        url="https://example.com/",
        rating=4.3,
    )
    pp = _lodging_to_place_point(lo)
    assert pp.place_id == "rakuten_99999"
    assert pp.name == "変換テスト旅館"
    assert "lodging" in pp.category
    assert "hotel" in pp.category
    assert pp.lat == 35.5
    assert pp.lng == 139.5
    # opening_hours は空、unknown_days は全曜日
    assert pp.opening_hours == []
    assert set(pp.opening_hours_unknown_days) == {0, 1, 2, 3, 4, 5, 6}
    # Phase 3 案 D 第 3 段: rating は LodgingOption から引き継がれる
    assert pp.rating == 4.3
    # 価格は 12000 → level 2 (8000〜15000 円)
    assert pp.price_level == 2
    assert pp.user_ratings_total is None


def test_lodging_to_place_point_handles_missing_coords():
    """LodgingOption.lat/lng が None でも PlacePoint は生成可能 (0.0 にフォールバック)。"""
    from src.evidence.builder import _lodging_to_place_point

    lo = LodgingOption(
        place_id="rakuten_no_coords",
        name="座標欠損テスト",
        price_jpy_per_night=8000,
        lat=None,
        lng=None,
        url=None,
    )
    pp = _lodging_to_place_point(lo)
    assert pp.lat == 0.0
    assert pp.lng == 0.0


def test_price_jpy_to_level_thresholds():
    """Phase 3 polish 案 D 第 3 段: price_jpy → price_level (1〜4) の閾値変換を検証。

    閾値:
    - level 1: < 8,000 円 (ビジホ・ゲストハウス)
    - level 2: 8,000 〜 15,000 円 (中位旅館・標準温泉宿)
    - level 3: 15,000 〜 30,000 円 (上位旅館)
    - level 4: 30,000 円 以上 (高級旅館・リゾート)
    """
    from src.evidence.builder import _price_jpy_to_level

    # 境界値 + 代表値
    assert _price_jpy_to_level(0) == 1
    assert _price_jpy_to_level(7_999) == 1
    assert _price_jpy_to_level(8_000) == 2
    assert _price_jpy_to_level(12_000) == 2
    assert _price_jpy_to_level(14_999) == 2
    assert _price_jpy_to_level(15_000) == 3
    assert _price_jpy_to_level(25_000) == 3
    assert _price_jpy_to_level(29_999) == 3
    assert _price_jpy_to_level(30_000) == 4
    assert _price_jpy_to_level(100_000) == 4


def test_lodging_to_place_point_rating_fallback_to_none():
    """LodgingOption.rating が None なら PlacePoint.rating も None。

    楽天 hotelRatingInfo が無い hotel (新規開業 / 評価未集計) では None になる挙動を保証。
    """
    from src.evidence.builder import _lodging_to_place_point

    lo = LodgingOption(
        place_id="rakuten_no_rating",
        name="評価無し宿",
        price_jpy_per_night=10000,
        lat=35.0,
        lng=139.0,
        rating=None,
    )
    pp = _lodging_to_place_point(lo)
    assert pp.rating is None
    # price_level は引き継がれる (10000 → level 2)
    assert pp.price_level == 2


# ==============================
# Phase 2.1: 出発モード切替（anchor / theme）
# ==============================


def test_generate_keywords_includes_theme_keywords():
    """theme モードでは pack 構築検索 keyword に theme 用語が追加される。"""
    ctx = QueryContext(
        region="箱根",
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 2),
        departure_point="新宿",
        start_mode="theme",
        mode_payload={"theme": "onsen"},
        participants=[QueryContextParticipant(name="a", wishes="", tags=[])],
    )
    keywords = _generate_keywords(ctx)
    # 温泉系 keyword が含まれる（少なくとも 1 つ）
    assert any("温泉" in kw for kw in keywords)


def test_generate_keywords_history_theme():
    ctx = QueryContext(
        region="京都",
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 2),
        departure_point="東京",
        start_mode="theme",
        mode_payload={"theme": "history"},
        participants=[QueryContextParticipant(name="a", wishes="", tags=[])],
    )
    keywords = _generate_keywords(ctx)
    # history 系（神社 / 寺 / 歴史 のいずれか）
    assert any(("神社" in kw) or ("寺" in kw) or ("歴史" in kw) for kw in keywords)


def test_generate_keywords_auto_mode_no_theme_extension():
    """auto モードでは theme keyword は追加されない（regression check）。

    Phase 3 polish 案 2 (2026-04-28): 基本 8 軸 (観光地 / 温泉 / 神社 寺 / 食事処 /
    旅館 / ホテル / 温泉宿 / 名所) + tag「温泉」は重複 skip = 合計 8 件。
    """
    ctx = QueryContext(
        region="箱根",
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 2),
        departure_point="新宿",
        start_mode="auto",
        mode_payload=None,
        participants=[QueryContextParticipant(name="a", wishes="", tags=["温泉"])],
    )
    keywords = _generate_keywords(ctx)
    # 基本 8 軸（"温泉" は重複 skip）= 8 件
    assert len(keywords) == 8
    assert "箱根 温泉" in keywords  # 基本 8 軸の 1 つとして含まれる
    assert "箱根 旅館" in keywords  # Phase 3 案 2 で「旅館 ホテル」を分割
    assert "箱根 ホテル" in keywords
    assert "箱根 温泉宿" in keywords
    assert "箱根 名所" in keywords  # Phase 3 polish 追加分


@patch("src.evidence.builder.fetch_place_details")
@patch("src.evidence.builder.search_by_text")
def test_build_evidence_pack_anchor_mode_includes_anchors_first(
    mock_search, mock_fetch
):
    """anchor モードで指定 place_id が pack の先頭に配置され、area filter も skip される。"""
    mock_search.return_value = [
        _place("search1", "箱根神社", 35.20, 139.02),
    ]
    mock_fetch.side_effect = lambda pid: _place(
        pid, f"anchor-{pid}", 35.0, 139.0, category=["restaurant"]
    )

    req = _sample_request(
        start_mode="anchor",
        mode_payload={"anchor_place_ids": ["anc1", "anc2"]},
    )
    pack = build_evidence_pack(req)

    place_ids = [p.place_id for p in pack.places]
    # anchor が先頭 2 件
    assert place_ids[:2] == ["anc1", "anc2"]
    # text search の結果も含まれる
    assert "search1" in place_ids


@patch("src.evidence.builder.fetch_place_details")
@patch("src.evidence.builder.search_by_text")
def test_build_evidence_pack_anchor_mode_skips_area_filter_for_anchors(
    mock_search, mock_fetch
):
    """anchor は user 明示意思なので area_place フィルタを skip（locality カテゴリでも残す）。"""
    mock_search.return_value = []
    mock_fetch.side_effect = lambda pid: _place(
        pid, "箱根町", 35.2, 139.0, category=["locality", "political"]
    )

    req = _sample_request(
        start_mode="anchor",
        mode_payload={"anchor_place_ids": ["loc_anchor"]},
    )
    pack = build_evidence_pack(req)

    assert "loc_anchor" in [p.place_id for p in pack.places]


@patch("src.evidence.builder.fetch_place_details")
@patch("src.evidence.builder.search_by_text")
def test_build_evidence_pack_anchor_failure_raises_fetch_error(mock_search, mock_fetch):
    """fetch_place_details が None を返した anchor があれば fail-fast で AnchorFetchError raise
    （Codex Major 3 対応: pack に anchor が無いまま LLM retry を浪費させない）。"""
    from src.evidence.builder import AnchorFetchError

    mock_search.return_value = [_place("s1", "箱根神社", 35.20, 139.02)]
    fetch_results = {
        "good_anchor": _place("good_anchor", "良い場所", 35.1, 139.1, category=["museum"]),
    }
    mock_fetch.side_effect = lambda pid: fetch_results.get(pid)  # bad_anchor → None

    req = _sample_request(
        start_mode="anchor",
        mode_payload={"anchor_place_ids": ["good_anchor", "bad_anchor"]},
    )
    with pytest.raises(AnchorFetchError) as exc:
        build_evidence_pack(req)
    assert "bad_anchor" in exc.value.missing_ids
    assert "good_anchor" not in exc.value.missing_ids


@patch("src.evidence.builder.fetch_place_details")
@patch("src.evidence.builder.search_by_text")
def test_build_evidence_pack_anchor_api_error_raises_upstream_error(mock_search, mock_fetch):
    """Codex 再レビュー Major 1: PlacesError (5xx / network / 認証) は 404 と区別して
    AnchorFetchUpstreamError raise（route 側で 502 に分岐）。"""
    from src.evidence.builder import AnchorFetchUpstreamError
    from src.evidence.places import PlacesError

    mock_search.return_value = []

    def fetch_side_effect(pid):
        if pid == "transient_failure":
            raise PlacesError("network error")
        return _place(pid, "ok", 35.0, 139.0, category=["museum"])

    mock_fetch.side_effect = fetch_side_effect

    req = _sample_request(
        start_mode="anchor",
        mode_payload={"anchor_place_ids": ["transient_failure"]},
    )
    with pytest.raises(AnchorFetchUpstreamError) as exc:
        build_evidence_pack(req)
    assert exc.value.place_id == "transient_failure"
    assert isinstance(exc.value.__cause__, PlacesError)


@patch("src.evidence.builder.search_by_text")
def test_build_evidence_pack_theme_mode_passes_through(mock_search):
    """theme モードでは builder が theme keyword を生成して search するが、
    出力 pack の構造自体は auto と同じ。"""
    mock_search.return_value = [_place("p_onsen", "温泉宿", 35.2, 139.0)]
    req = _sample_request(
        start_mode="theme",
        mode_payload={"theme": "onsen"},
    )
    pack = build_evidence_pack(req)
    assert pack.query_context.start_mode == "theme"
    assert pack.query_context.mode_payload == {"theme": "onsen"}
    # search は呼ばれた（keywords ベースで 5 件くらい）
    assert mock_search.call_count >= 1


# ==============================
# Integration（ライブ Places API、transit はフロント task なのでここでは検証しない）
# ==============================


def _has_real_maps_key() -> bool:
    val = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    return len(val) >= 20 and val.startswith("AIza")


@pytest.mark.integration
@pytest.mark.skipif(not _has_real_maps_key(), reason="GOOGLE_MAPS_API_KEY not set")
def test_integration_build_hakone_pack():
    """箱根の小さな Evidence Pack を実 API で構築。places だけ検証。

    コストは Places 検索 5 回分（推定 $0.1 未満）。transit はフロント側で後埋めする
    ので、integration テストでも transit_matrix=[] が期待値。
    """
    req = GeneratePlanRequest(
        title="箱根日帰り",
        region="箱根",
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 1),
        departure_point="新宿駅",
        budget_per_person_jpy=20000,
        budget_breakdown=BudgetBreakdown(lodging=0, meal=40, activity=30, transit=30),
        start_mode="auto",
        mode_payload=None,
        participants=[
            ParticipantInput(
                display_name="太郎",
                avatar_color="#D97757",
                wishes_text="温泉と和食",
                tags=["温泉", "和食"],
                order_index=0,
            ),
        ],
    )
    pack = build_evidence_pack(req)

    assert len(pack.places) > 0, "箱根で places が 1 件も取れないのは Places API の問題"
    assert all(p.place_id for p in pack.places)
    assert pack.transit_matrix == []
    assert pack.budget_constraints.total_jpy_per_person == 20000
    assert pack.budget_constraints.breakdown_jpy.lodging == 0
