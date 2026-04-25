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
