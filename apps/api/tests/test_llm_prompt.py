"""`apps/api/src/llm/prompt.py` のテスト（Phase 1.3d Branch A）。

prompt builder が正しい形で system / user プロンプトを返し、previous_issues を含めて
LLM に自己訂正させる材料を提供できることを確認する。
"""

from __future__ import annotations

from datetime import date

import pytest

from src.evidence.pack import (
    BudgetBreakdownJPY,
    BudgetConstraints,
    EvidencePack,
    OpeningHoursSlot,
    PlacePoint,
    QueryContext,
    QueryContextParticipant,
    TemporalConstraints,
    TransitEdge,
)
from src.llm.prompt import (
    PROMPT_VERSION_DEFAULT,
    _build_budget_context_md,
    _build_retry_guidance_md,
    _extract_unknown_place_ids,
    build_system_prompt,
    build_user_prompt,
    count_prompt_tokens,
    load_prompt_version,
)
from src.llm.validator import IssueKind, ValidationIssue
from src.schemas import BudgetBreakdown


@pytest.fixture
def sample_pack() -> EvidencePack:
    return EvidencePack(
        query_context=QueryContext(
            region="箱根",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 2),
            departure_point="新宿駅",
            start_mode="auto",
            mode_payload=None,
            participants=[QueryContextParticipant(name="太郎", wishes="温泉", tags=["温泉"])],
        ),
        places=[
            PlacePoint(
                place_id="P_hakone_jinja",
                name="箱根神社",
                category=["tourist_attraction"],
                lat=35.2,
                lng=139.0,
                address="神奈川県箱根町",
                opening_hours=[
                    OpeningHoursSlot(day_of_week=0, open_hhmm="09:00", close_hhmm="17:00"),
                ],
                opening_hours_unknown_days=[],
                price_level=None,
                rating=4.5,
                user_ratings_total=1000,
                relevance_tags=[],
            ),
        ],
        transit_matrix=[
            TransitEdge(
                from_place_id="P_hakone_jinja",
                to_place_id="P_hakone_jinja",
                mode="walk",
                route_summary="徒歩",
                duration_min=5,
                fare_jpy=None,
                candidate_departures=["09:00"],
            ),
        ],
        budget_constraints=BudgetConstraints(
            total_jpy_per_person=30000,
            breakdown_percent=BudgetBreakdown(lodging=40, meal=30, activity=20, transit=10),
            breakdown_jpy=BudgetBreakdownJPY(lodging=12000, meal=9000, activity=6000, transit=3000),
        ),
        temporal_constraints=TemporalConstraints(
            start_datetime="2026-06-01T09:00:00+09:00",
            end_datetime="2026-06-02T20:00:00+09:00",
            total_days=2,
        ),
    )


def test_build_system_prompt_default_version():
    """default = v2.0.0 (Phase 1.10 で切替) の system prompt が読める。"""
    prompt = build_system_prompt()
    assert "旅行プランナー" in prompt
    assert "絶対ルール" in prompt
    assert "architecture" not in prompt.lower()  # 余計なもの混入なし
    # v2 の絶対ルールは 7 項目
    for i in range(1, 8):
        assert f"{i}." in prompt


def test_build_system_prompt_version_kwarg():
    # 明示版指定
    prompt = build_system_prompt(version="v1.0.0")
    assert "旅行プランナー" in prompt


def test_build_system_prompt_unknown_version_raises():
    with pytest.raises(FileNotFoundError):
        build_system_prompt(version="v99.99.99")


def test_build_user_prompt_includes_all_placeholders_filled(sample_pack):
    prompt = build_user_prompt(sample_pack, previous_issues=[])
    # JSON が埋め込まれている
    assert "箱根" in prompt
    assert "P_hakone_jinja" in prompt
    # placeholder が残ってない
    assert "{query_context_json}" not in prompt
    assert "{evidence_pack_places_json}" not in prompt
    assert "{transit_matrix_json}" not in prompt
    assert "{budget_constraints_json}" not in prompt
    assert "{temporal_constraints_json}" not in prompt
    assert "{previous_issues_json}" not in prompt


def test_build_user_prompt_with_previous_issues(sample_pack):
    issues = [
        ValidationIssue(
            kind=IssueKind.UNKNOWN_PLACE_ID,
            message="place_id='X' は存在しない",
            item_index=2,
        ),
        ValidationIssue(
            kind=IssueKind.BUDGET_EXCEEDED,
            message="activity 合計超過",
            item_index=None,
        ),
    ]
    prompt = build_user_prompt(sample_pack, previous_issues=issues)
    assert "unknown_place_id" in prompt
    assert "budget_exceeded" in prompt
    assert "place_id='X'" in prompt


def test_build_user_prompt_empty_issues_shows_initial_run(sample_pack):
    prompt = build_user_prompt(sample_pack, previous_issues=[])
    # 空配列 [] が JSON で入っていること
    assert "[]" in prompt


def test_build_user_prompt_omits_server_only_fields(sample_pack):
    """place に address / user_ratings_total / lat / lng / relevance_tags など LLM に不要な
    冗長フィールドは渡さない（token 節約、@tasks/lessons.md 2026-04-25 方針）。
    """
    prompt = build_user_prompt(sample_pack, previous_issues=[])
    # address は冗長なので含めない
    assert "神奈川県箱根町" not in prompt
    # user_ratings_total も不要
    assert "user_ratings_total" not in prompt
    # lat / lng は LLM が使わないので含めない（空間判断は transit_matrix で間接）
    assert '"lat"' not in prompt
    assert '"lng"' not in prompt
    # Phase 1.3 時点では空配列運用の relevance_tags も冗長
    assert "relevance_tags" not in prompt


def test_build_user_prompt_v2_strips_transit_edge_to_minimal(sample_pack):
    """Phase 1.3e β: v2 は transit edge を `{from, to}` のみに縮小（LCaMO 介入カタログ縮小）。

    v2 の LLM は system prompt rule 7 で transit_matrix を「到達可能ペア」としてしか使わない。
    mode/route_summary/duration_min/fare_jpy/candidate_departures は assembler が
    元 TransitEdge から決定論で埋めるため、LLM 表現に含めるのは prompt token の浪費。
    """
    prompt = build_user_prompt(sample_pack, previous_issues=[], version="v2.0.0")
    # edge 補助情報は v2 prompt から除外
    assert "徒歩" not in prompt  # route_summary
    assert "duration_min" not in prompt
    assert "candidate_departures" not in prompt
    assert "fare_jpy" not in prompt
    assert '"mode"' not in prompt
    # ただし from/to のペアは残る（到達可能性判断に必要）
    assert "P_hakone_jinja" in prompt


def test_build_user_prompt_v1_keeps_full_transit_edge(sample_pack):
    """v1 regression 防止: v1 は LLM が transit_ref.departure_time を直接生成するため、
    candidate_departures など full edge 情報を保持する必要がある。
    """
    prompt = build_user_prompt(sample_pack, previous_issues=[], version="v1.0.0")
    assert "徒歩" in prompt  # route_summary 保持
    assert "candidate_departures" in prompt
    assert "duration_min" in prompt


# ==============================
# Phase 2.1: mode_context（出発モードに応じた追加指示）
# ==============================


def _pack_with_mode(sample_pack, start_mode, mode_payload):
    """sample_pack の query_context だけ start_mode/mode_payload を差し替え。"""
    return sample_pack.model_copy(
        update={
            "query_context": sample_pack.query_context.model_copy(
                update={"start_mode": start_mode, "mode_payload": mode_payload}
            )
        }
    )


def test_build_user_prompt_v2_anchor_mode_includes_anchor_ids(sample_pack):
    """anchor モード: 必須 place_id 一覧 が prompt に明示される。"""
    pack = _pack_with_mode(
        sample_pack,
        "anchor",
        {"anchor_place_ids": ["P_hakone_jinja", "anc2"]},
    )
    prompt = build_user_prompt(pack, previous_issues=[], version="v2.0.0")
    # 「必須」「アンカー」のいずれか + 各 place_id が現れる
    assert "アンカー" in prompt or "必須" in prompt
    assert "P_hakone_jinja" in prompt
    assert "anc2" in prompt


def test_build_user_prompt_v2_theme_mode_includes_theme_label(sample_pack):
    """theme モード: テーマ名 (日本語ラベル) が prompt に明示される。"""
    pack = _pack_with_mode(sample_pack, "theme", {"theme": "onsen"})
    prompt = build_user_prompt(pack, previous_issues=[], version="v2.0.0")
    assert "テーマ" in prompt
    assert "温泉" in prompt  # onsen の日本語ラベル


def test_build_user_prompt_v2_auto_mode_no_extra_mode_section(sample_pack):
    """auto モード: 追加 mode_context 出力なし（"アンカー" / "テーマ:" 等の見出しが出ない）。"""
    pack = _pack_with_mode(sample_pack, "auto", None)
    prompt = build_user_prompt(pack, previous_issues=[], version="v2.0.0")
    # mode_context 由来の見出しは含まれない
    assert "アンカー" not in prompt
    assert "テーマ:" not in prompt


def test_build_user_prompt_v2_anchor_with_unknown_payload_skip(sample_pack):
    """anchor モード payload が壊れてる場合、prompt は安全に空 mode_context で出力。"""
    # mode_payload が anchor_place_ids を含まない
    pack = _pack_with_mode(sample_pack, "anchor", {"unrelated": True})
    prompt = build_user_prompt(pack, previous_issues=[], version="v2.0.0")
    # 「アンカー」「必須」見出しは出ない（payload 無効なため）
    assert "アンカー" not in prompt
    assert "必須スポット" not in prompt


# =================================================================
# Phase 2 polish (2026-04-27): transport_mode（移動手段指定）
# =================================================================


def _pack_with_transport(sample_pack, transport_mode):
    """sample_pack の query_context.transport_mode だけ差し替え。"""
    return sample_pack.model_copy(
        update={
            "query_context": sample_pack.query_context.model_copy(
                update={"transport_mode": transport_mode}
            )
        }
    )


def test_build_user_prompt_v2_public_transit_only_includes_transport_section(sample_pack):
    """transport_mode='public_transit_only' のとき公共交通明示の section が出る。"""
    pack = _pack_with_transport(sample_pack, "public_transit_only")
    prompt = build_user_prompt(pack, previous_issues=[], version="v2.0.0")
    assert "公共交通機関のみ" in prompt
    assert "車を運転しない" in prompt


def test_build_user_prompt_v2_all_modes_no_transport_section(sample_pack):
    """transport_mode='all_modes'（default）では transport section は出ない。"""
    pack = _pack_with_transport(sample_pack, "all_modes")
    prompt = build_user_prompt(pack, previous_issues=[], version="v2.0.0")
    assert "公共交通機関のみ" not in prompt
    assert "車を運転しない" not in prompt


def test_build_user_prompt_v2_anchor_and_public_transit_compose_both_sections(sample_pack):
    """anchor + public_transit_only を併用したとき、両方の section が prompt に出る。

    Codex Major 2 の「合成方式」refactor で旧の早期 return 設計が落としていた組み合わせ。
    """
    pack = sample_pack.model_copy(
        update={
            "query_context": sample_pack.query_context.model_copy(
                update={
                    "start_mode": "anchor",
                    "mode_payload": {"anchor_place_ids": ["P_hakone_jinja"]},
                    "transport_mode": "public_transit_only",
                }
            )
        }
    )
    prompt = build_user_prompt(pack, previous_issues=[], version="v2.0.0")
    # anchor section
    assert "アンカー" in prompt or "必須" in prompt
    assert "P_hakone_jinja" in prompt
    # transport section も同時に出る（旧の早期 return では落ちていた）
    assert "公共交通機関のみ" in prompt


def test_build_user_prompt_v2_theme_and_public_transit_compose_both(sample_pack):
    """theme + public_transit_only でも両方の section が出る。"""
    pack = sample_pack.model_copy(
        update={
            "query_context": sample_pack.query_context.model_copy(
                update={
                    "start_mode": "theme",
                    "mode_payload": {"theme": "onsen"},
                    "transport_mode": "public_transit_only",
                }
            )
        }
    )
    prompt = build_user_prompt(pack, previous_issues=[], version="v2.0.0")
    assert "テーマ" in prompt
    assert "温泉" in prompt
    assert "公共交通機関のみ" in prompt


def test_build_user_prompt_v2_mode_context_section_order(sample_pack):
    """Codex review 2 Minor 1: anchor + theme + transport の合成順序を固定検証。

    `_build_mode_context_md` は anchor → theme → transport の順で連結する。
    anchor と theme は discriminated union で同時には出ないので、anchor + transport
    と theme + transport の各順序を assert。

    Codex review 3 Minor 1 修正: 「P_anchor_test」「温泉」のような汎用語で find する
    と query_context_json / participants wishes 側にもヒットして偽陽性になる。
    mode_context_md 特有の section 見出し文字列（query_context_json には現れない
    日本語フレーズ）で順序を判定する。
    """
    # 各 section の section 見出し（mode_context_md 専用フレーズ）
    ANCHOR_HEADER = "アンカー（必須スポット）"
    THEME_HEADER = "テーマ:"
    TRANSPORT_HEADER = "移動手段:"

    # anchor + transport
    pack_anchor = sample_pack.model_copy(
        update={
            "query_context": sample_pack.query_context.model_copy(
                update={
                    "start_mode": "anchor",
                    "mode_payload": {"anchor_place_ids": ["P_anchor_test"]},
                    "transport_mode": "public_transit_only",
                }
            )
        }
    )
    p1 = build_user_prompt(pack_anchor, previous_issues=[], version="v2.0.0")
    anchor_idx = p1.find(ANCHOR_HEADER)
    transport_idx = p1.find(TRANSPORT_HEADER)
    assert anchor_idx >= 0, f"anchor section header {ANCHOR_HEADER!r} がない"
    assert transport_idx >= 0, f"transport section header {TRANSPORT_HEADER!r} がない"
    assert anchor_idx < transport_idx, "anchor section が transport より前に来るはず"

    # theme + transport
    pack_theme = sample_pack.model_copy(
        update={
            "query_context": sample_pack.query_context.model_copy(
                update={
                    "start_mode": "theme",
                    "mode_payload": {"theme": "onsen"},
                    "transport_mode": "public_transit_only",
                }
            )
        }
    )
    p2 = build_user_prompt(pack_theme, previous_issues=[], version="v2.0.0")
    theme_idx = p2.find(THEME_HEADER)
    transport_idx = p2.find(TRANSPORT_HEADER)
    assert theme_idx >= 0, f"theme section header {THEME_HEADER!r} がない"
    assert transport_idx >= 0, f"transport section header {TRANSPORT_HEADER!r} がない"
    assert theme_idx < transport_idx, "theme section が transport より前に来るはず"


# =================================================================
# Phase 2.2: 予算配分の制約化（_build_budget_context_md）
# =================================================================


def _budget_constraints(
    *,
    total: int = 30000,
    pct: tuple[int, int, int, int] = (40, 30, 20, 10),
    jpy: tuple[int, int, int, int] = (12000, 9000, 6000, 3000),
) -> BudgetConstraints:
    return BudgetConstraints(
        total_jpy_per_person=total,
        breakdown_percent=BudgetBreakdown(
            lodging=pct[0], meal=pct[1], activity=pct[2], transit=pct[3]
        ),
        breakdown_jpy=BudgetBreakdownJPY(
            lodging=jpy[0], meal=jpy[1], activity=jpy[2], transit=jpy[3]
        ),
    )


def test_build_budget_context_md_standard_distribution():
    """標準配分 40/30/20/10、3 桁区切りで 4 行のリストを出す。"""
    md = _build_budget_context_md(_budget_constraints())
    # 各カテゴリ行が含まれる
    assert "宿泊" in md and "40%" in md and "12,000" in md
    assert "食事" in md and "30%" in md and "9,000" in md
    assert "観光" in md and "20%" in md and "6,000" in md
    assert "交通" in md and "10%" in md and "3,000" in md
    # 「絶対制約」「validator」「+5%」などの強調語が含まれる
    assert "絶対制約" in md
    assert "validator" in md
    assert "+5%" in md or "5%" in md
    # 1 人あたり総予算も入る
    assert "30,000" in md


def test_build_budget_context_md_skewed_lodging_heavy():
    """偏り配分（宿泊 80%）でも数値が正しく反映される。"""
    md = _build_budget_context_md(
        _budget_constraints(
            total=50000,
            pct=(80, 10, 5, 5),
            jpy=(40000, 5000, 2500, 2500),
        )
    )
    assert "宿泊" in md and "80%" in md and "40,000" in md
    assert "食事" in md and "10%" in md and "5,000" in md
    assert "観光" in md and "5%" in md and "2,500" in md
    assert "交通" in md and "5%" in md and "2,500" in md


def test_build_budget_context_md_zero_categories_kept_explicit():
    """0% カテゴリは行ごと消さず「0%（¥0 以内）」で明示する（Codex OK 反映）。"""
    md = _build_budget_context_md(
        _budget_constraints(
            total=30000,
            pct=(50, 50, 0, 0),
            jpy=(15000, 15000, 0, 0),
        )
    )
    # 4 行とも残る
    assert "宿泊" in md and "50%" in md
    assert "食事" in md and "50%" in md
    assert "観光" in md and "0%" in md
    assert "交通" in md and "0%" in md
    # 0 表記
    assert "¥0" in md or "0 円" in md


def test_build_budget_context_md_jpy_thousands_separator():
    """3 桁区切りで整形（Intl 風、漢字「円」前 or `¥` prefix）。"""
    md = _build_budget_context_md(
        _budget_constraints(
            total=10000,
            pct=(33, 33, 17, 17),
            jpy=(3300, 3300, 1700, 1700),
        )
    )
    # 4 桁の数値が 3 桁区切りで表示
    assert "3,300" in md
    assert "1,700" in md
    # 整数化済（小数点なし）
    assert "3,300.0" not in md


def test_build_budget_context_md_includes_slot_guidance():
    """LLM の slot 配分への指示文が含まれる（Phase 1.3e cost_jpy 決定論との整合）。"""
    md = _build_budget_context_md(_budget_constraints())
    # 「slot 配分で守れ」「上限目標」など key word が文中にある
    assert "slot" in md or "枠" in md  # slot 配分言及
    # tolerance の文言（+5% allowance を明示）
    assert "+5%" in md or "5%" in md


# =================================================================
# build_user_prompt 統合テスト（Phase 2.2）
# =================================================================


def test_build_user_prompt_v2_includes_budget_context_md(sample_pack):
    """v2 prompt に予算絶対制約 Markdown が展開されて含まれる。"""
    prompt = build_user_prompt(sample_pack, previous_issues=[], version="v2.0.0")
    assert "予算配分の絶対制約" in prompt
    # placeholder が残ってない
    assert "{budget_context_md}" not in prompt


def test_build_user_prompt_v2_budget_context_after_mode_context(sample_pack):
    """挿入順検証: 予算絶対制約は mode_context_md の **後** + previous_issues の **前**。

    Codex review 2 回目 Minor 2 反映: 「mode より後」だけでなく「issues より前」まで担保する。
    """
    prompt = build_user_prompt(sample_pack, previous_issues=[], version="v2.0.0")
    mode_idx = prompt.index("出発モード補足")
    budget_idx = prompt.index("予算配分の絶対制約")
    issues_idx = prompt.index("前回の生成で失敗した検証項目")
    assert mode_idx < budget_idx < issues_idx, (
        "budget_context_md は mode_context_md と previous_issues の間に来るべき"
    )


def test_build_user_prompt_v2_budget_context_with_anchor_mode(sample_pack):
    """anchor モードでも budget_context_md と mode_context_md が両立して含まれる。"""
    pack = _pack_with_mode(
        sample_pack, "anchor", {"anchor_place_ids": ["P_hakone_jinja"]}
    )
    prompt = build_user_prompt(pack, previous_issues=[], version="v2.0.0")
    assert "予算配分の絶対制約" in prompt
    assert "アンカー" in prompt or "必須" in prompt


def test_build_user_prompt_v2_budget_context_with_theme_mode(sample_pack):
    """theme モードでも両立。"""
    pack = _pack_with_mode(sample_pack, "theme", {"theme": "onsen"})
    prompt = build_user_prompt(pack, previous_issues=[], version="v2.0.0")
    assert "予算配分の絶対制約" in prompt
    assert "テーマ" in prompt


def test_build_user_prompt_v1_does_not_include_budget_absolute_constraint(sample_pack):
    """v1 prompt は変更しないので「予算配分の絶対制約」は出ない（後方互換）。"""
    prompt = build_user_prompt(sample_pack, previous_issues=[], version="v1.0.0")
    assert "予算配分の絶対制約" not in prompt


def test_count_prompt_tokens_returns_int(sample_pack):
    system = build_system_prompt()
    user = build_user_prompt(sample_pack, previous_issues=[])
    tokens = count_prompt_tokens(system, user)
    assert isinstance(tokens, int)
    assert tokens > 0


def test_load_prompt_version_default_constant():
    # Phase 1.10 で v2 (LCaMO 構造化版、hallucination 0% / success 100%) をデフォルトに
    assert PROMPT_VERSION_DEFAULT == "v2.0.0"


def test_load_prompt_version_reads_env(monkeypatch):
    monkeypatch.setenv("PROMPT_VERSION", "v1.0.0")
    assert load_prompt_version() == "v1.0.0"


def test_load_prompt_version_falls_back_to_default(monkeypatch):
    monkeypatch.delenv("PROMPT_VERSION", raising=False)
    assert load_prompt_version() == "v2.0.0"


# ==============================
# Phase 1.10 後段 fix: retry guidance（Codex review 2 反映）
# ==============================


def test_build_retry_guidance_md_empty():
    """previous_issues が空なら空文字列を返す（初回試行で template 形状が崩れない）。"""
    assert _build_retry_guidance_md([]) == ""


def test_build_retry_guidance_md_unknown_place_id_assembly_format():
    """assembly UnknownPlaceInSlotError 由来の message から place_id を抽出して禁止リストに。"""
    issues = [
        ValidationIssue(
            kind=IssueKind.UNKNOWN_PLACE_ID,
            message="assembly error: LLM assigned unknown place_id 'ChIJ123' to slot 'day1_lunch'",
            item_index=None,
        ),
        ValidationIssue(
            kind=IssueKind.UNKNOWN_PLACE_ID,
            message="assembly error: LLM assigned unknown place_id 'ChIJ456' to slot 'day1_dinner'",
            item_index=None,
        ),
    ]
    md = _build_retry_guidance_md(issues)
    assert "ChIJ123" in md
    assert "ChIJ456" in md
    assert "絶対に再使用するな" in md


def test_build_retry_guidance_md_unknown_place_id_validator_format():
    """validator 由来の `place_id='XXX'` 形式 message も regex で拾えること。"""
    issues = [
        ValidationIssue(
            kind=IssueKind.UNKNOWN_PLACE_ID,
            message="place_id='ChIJ789' は evidence_pack.places に存在しない",
            item_index=0,
        ),
    ]
    md = _build_retry_guidance_md(issues)
    assert "ChIJ789" in md


def test_build_retry_guidance_md_dedup():
    """同じ unknown_place_id が複数 issue に含まれていても 1 つに dedup（Codex Major 1）。"""
    issues = [
        ValidationIssue(
            kind=IssueKind.UNKNOWN_PLACE_ID,
            message="LLM assigned unknown place_id 'ChIJ123' to slot 'day1_lunch'",
            item_index=None,
        ),
        ValidationIssue(
            kind=IssueKind.UNKNOWN_PLACE_ID,
            message="LLM assigned unknown place_id 'ChIJ123' to slot 'day1_dinner'",
            item_index=None,
        ),
    ]
    md = _build_retry_guidance_md(issues)
    assert md.count("ChIJ123") == 1


def test_build_retry_guidance_md_ignores_other_kinds():
    """UNKNOWN_PLACE_ID 以外の IssueKind は無視（regex 誤動作防止）。"""
    issues = [
        ValidationIssue(
            kind=IssueKind.OUTSIDE_OPENING_HOURS,
            message="place_id='ChIJ_other' の営業時間外",
            item_index=0,
        ),
        ValidationIssue(
            kind=IssueKind.BUDGET_EXCEEDED,
            message="activity 合計超過",
            item_index=None,
        ),
    ]
    assert _build_retry_guidance_md(issues) == ""


def test_extract_unknown_place_ids_returns_sorted_unique():
    """`_extract_unknown_place_ids` は sorted unique list を返す（dedup helper として使う）。"""
    issues = [
        ValidationIssue(
            kind=IssueKind.UNKNOWN_PLACE_ID,
            message="LLM assigned unknown place_id 'ChIJ_z' to slot 'day1_lunch'",
            item_index=None,
        ),
        ValidationIssue(
            kind=IssueKind.UNKNOWN_PLACE_ID,
            message="LLM assigned unknown place_id 'ChIJ_a' to slot 'day1_dinner'",
            item_index=None,
        ),
        ValidationIssue(
            kind=IssueKind.UNKNOWN_PLACE_ID,
            message="LLM assigned unknown place_id 'ChIJ_a' to slot 'day1_breakfast'",
            item_index=None,
        ),
    ]
    assert _extract_unknown_place_ids(issues) == ["ChIJ_a", "ChIJ_z"]


def test_build_user_prompt_v2_includes_retry_guidance_when_unknown_place_id(sample_pack):
    """v2 prompt は retry guidance (`絶対に再使用するな` ブロック) を含む。"""
    issues = [
        ValidationIssue(
            kind=IssueKind.UNKNOWN_PLACE_ID,
            message="LLM assigned unknown place_id 'ChIJ_bad' to slot 'day1_lunch'",
            item_index=None,
        ),
    ]
    prompt = build_user_prompt(sample_pack, previous_issues=issues, version="v2.0.0")
    assert "ChIJ_bad" in prompt
    assert "絶対に再使用するな" in prompt
    # placeholder が残ってない
    assert "{retry_guidance_md}" not in prompt


def test_build_user_prompt_v2_no_retry_guidance_on_first_attempt(sample_pack):
    """初回 attempt は retry guidance が空文字列 → template 形状が崩れない。"""
    prompt = build_user_prompt(sample_pack, previous_issues=[], version="v2.0.0")
    assert "絶対に再使用するな" not in prompt
    assert "{retry_guidance_md}" not in prompt
