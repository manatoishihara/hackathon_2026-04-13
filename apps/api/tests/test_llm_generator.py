"""`apps/api/src/llm/generator.py` のテスト（Phase 1.3d Branch B）。

OpenAI SDK をモックして retry / fallback / deadline の挙動を検証する。
実 API は叩かないのでコスト ゼロ。実経路の確認は Branch C の integration テストで行う。

本ファイルは v1 schema (`LlmGeneratedPlan`) でモックを組んでいる。
v1 / v2 で retry / fallback / deadline のロジックは共通なので、構造は v1 で代表させ、
v2 (LCaMO) の assembly 経路は `test_llm_assembly.py` で別途網羅する。
そのため `PROMPT_VERSION=v1.0.0` を autouse fixture で固定する。
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def _force_prompt_v1(monkeypatch):
    """default は v2.0.0 (Phase 1.10 切替済) なので、v1 mock を使う本ファイルでは
    PROMPT_VERSION=v1.0.0 を明示する。"""
    monkeypatch.setenv("PROMPT_VERSION", "v1.0.0")

from src.evidence.pack import (
    BudgetBreakdownJPY,
    BudgetConstraints,
    EvidencePack,
    PlacePoint,
    QueryContext,
    QueryContextParticipant,
    TemporalConstraints,
    TransitEdge,
)
from src.llm.generator import (
    DEFAULT_FALLBACK_MODEL,
    DEFAULT_PRIMARY_MODEL,
    DeadlineExceededError,
    LlmBadRequestError,
    LlmGenerationError,
    LlmRefusalError,
    LlmTransportError,
    generate_plan,
)
from src.llm.schema import LlmGeneratedPlan, LlmPlanItem
from src.schemas import BudgetBreakdown


# ==============================
# Fixtures
# ==============================


def _pack(place_ids: list[str] | None = None) -> EvidencePack:
    ids = place_ids or ["A", "B"]
    return EvidencePack(
        query_context=QueryContext(
            region="箱根",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 2),
            departure_point="新宿",
            start_mode="auto",
            mode_payload=None,
            participants=[QueryContextParticipant(name="a", wishes="", tags=[])],
        ),
        places=[
            PlacePoint(
                place_id=pid,
                name=f"p-{pid}",
                category=[],
                lat=35.0,
                lng=139.0,
                address="addr",
                opening_hours=[],
                opening_hours_unknown_days=[],
                price_level=None,
                rating=None,
                user_ratings_total=None,
            )
            for pid in ids
        ],
        transit_matrix=[
            TransitEdge(
                from_place_id="A",
                to_place_id="B",
                mode="train",
                route_summary="JR",
                duration_min=30,
                fare_jpy=500,
                candidate_departures=["09:00"],
            )
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


def _valid_plan(place_id: str = "A") -> LlmGeneratedPlan:
    return LlmGeneratedPlan(
        items=[
            LlmPlanItem(
                order_index=0,
                item_type="activity",
                title="観光",
                description=None,
                start_time="2026-06-01T10:00:00+09:00",
                end_time="2026-06-01T12:00:00+09:00",
                place_id=place_id,
                cost_jpy=1000,
                cost_confidence="verified",
                transit_ref=None,
            )
        ]
    )


def _invalid_plan_unknown_place_id() -> LlmGeneratedPlan:
    # Pydantic はこれを通すが、validator が UnknownPlaceId で弾く
    return LlmGeneratedPlan(
        items=[
            LlmPlanItem(
                order_index=0,
                item_type="activity",
                title="観光",
                description=None,
                start_time="2026-06-01T10:00:00+09:00",
                end_time="2026-06-01T12:00:00+09:00",
                place_id="NOT_IN_PACK",
                cost_jpy=1000,
                cost_confidence="verified",
                transit_ref=None,
            )
        ]
    )


def _mock_client_returning(*responses, refusals=None):
    """responses: 各 attempt で parse が返す LlmGeneratedPlan or 例外。
    refusals: 各 attempt で refusal 文字列を返す（None なら parsed を返す）。"""
    client = MagicMock()
    parsed_iter = iter(responses)
    refusals_iter = iter(refusals or [None] * len(responses))

    def parse(*args, **kwargs):
        nxt = next(parsed_iter)
        if isinstance(nxt, Exception):
            raise nxt
        refusal = next(refusals_iter)
        choice = MagicMock()
        choice.message.refusal = refusal
        choice.message.parsed = nxt
        completion = MagicMock()
        completion.choices = [choice]
        return completion

    client.chat.completions.parse.side_effect = parse
    return client


# ==============================
# Happy path
# ==============================


def test_generate_plan_success_first_attempt():
    client = _mock_client_returning(_valid_plan())
    pack = _pack()
    plan = generate_plan(pack, client=client)
    assert isinstance(plan, LlmGeneratedPlan)
    assert len(plan.items) == 1
    assert client.chat.completions.parse.call_count == 1


# ==============================
# Retry 経路
# ==============================


def test_generate_plan_retry_on_validation_issue():
    """1 回目は validator で reject、2 回目で成功。issues が再プロンプトに含まれる。"""
    client = _mock_client_returning(_invalid_plan_unknown_place_id(), _valid_plan())
    pack = _pack()
    plan = generate_plan(pack, client=client)
    assert len(plan.items) == 1
    assert client.chat.completions.parse.call_count == 2

    # 2 回目の呼び出しで issue が user prompt に含まれている
    second_call = client.chat.completions.parse.call_args_list[1]
    user_msg = next(
        m for m in second_call.kwargs.get("messages", []) if m["role"] == "user"
    )
    assert "unknown_place_id" in user_msg["content"]


def test_generate_plan_uses_primary_model_on_retries():
    """attempt 1-3 は primary（gpt-4o）を使う。"""
    client = _mock_client_returning(
        _invalid_plan_unknown_place_id(),
        _invalid_plan_unknown_place_id(),
        _valid_plan(),
    )
    pack = _pack()
    generate_plan(pack, client=client)

    for i in range(3):
        call = client.chat.completions.parse.call_args_list[i]
        assert call.kwargs["model"] == DEFAULT_PRIMARY_MODEL


# ==============================
# Fallback 経路
# ==============================


def test_generate_plan_fallback_to_secondary_model():
    """primary 3 回失敗 → fallback 1 回で成功。"""
    client = _mock_client_returning(
        _invalid_plan_unknown_place_id(),
        _invalid_plan_unknown_place_id(),
        _invalid_plan_unknown_place_id(),
        _valid_plan(),
    )
    pack = _pack()
    plan = generate_plan(pack, client=client)
    assert len(plan.items) == 1
    assert client.chat.completions.parse.call_count == 4
    # 4 回目は fallback モデル
    final_call = client.chat.completions.parse.call_args_list[3]
    assert final_call.kwargs["model"] == DEFAULT_FALLBACK_MODEL


def test_generate_plan_exhausts_all_attempts_and_raises():
    """4 回全て validation 失敗 → LlmGenerationError。"""
    client = _mock_client_returning(
        _invalid_plan_unknown_place_id(),
        _invalid_plan_unknown_place_id(),
        _invalid_plan_unknown_place_id(),
        _invalid_plan_unknown_place_id(),
    )
    pack = _pack()
    with pytest.raises(LlmGenerationError) as exc_info:
        generate_plan(pack, client=client)
    assert exc_info.value.attempts == 4
    assert len(exc_info.value.issues) >= 1


# ==============================
# Transport error（retry に含める）
# ==============================


def test_generate_plan_openai_error_retried():
    """TimeoutError → retry カウントに含めて次を試行。"""
    client = _mock_client_returning(TimeoutError("timeout"), _valid_plan())
    pack = _pack()
    plan = generate_plan(pack, client=client)
    assert len(plan.items) == 1
    assert client.chat.completions.parse.call_count == 2


def test_generate_plan_all_transport_errors_raises_transport_error():
    """4 回すべて OpenAI エラー → LlmTransportError（generation ではなく transport 層の問題）。"""
    client = _mock_client_returning(
        TimeoutError("t1"),
        TimeoutError("t2"),
        TimeoutError("t3"),
        TimeoutError("t4"),
    )
    pack = _pack()
    with pytest.raises(LlmTransportError):
        generate_plan(pack, client=client)


# ==============================
# Refusal
# ==============================


def test_generate_plan_raises_on_refusal():
    """OpenAI が safety で refuse → LlmRefusalError（retry せず即時 raise）。"""
    client = _mock_client_returning(
        _valid_plan(),  # parsed は dummy、refusal フィールドが message に付く
        refusals=["safety refused"],
    )
    pack = _pack()
    with pytest.raises(LlmRefusalError):
        generate_plan(pack, client=client)


# ==============================
# Deadline
# ==============================


def test_generate_plan_aborts_after_deadline(monkeypatch):
    """global deadline を超えたら DeadlineExceededError。"""
    pack = _pack()
    # per_call を小さく + deadline 0 にして即アボート
    client = _mock_client_returning(_valid_plan())
    with pytest.raises(DeadlineExceededError):
        generate_plan(pack, client=client, global_deadline_sec=0.0)


# ==============================
# response_format / Pydantic 渡し
# ==============================


def test_generate_plan_passes_pydantic_model_as_response_format():
    client = _mock_client_returning(_valid_plan())
    pack = _pack()
    generate_plan(pack, client=client)
    call = client.chat.completions.parse.call_args_list[0]
    assert call.kwargs["response_format"] is LlmGeneratedPlan


def test_generate_plan_passes_timeout_per_call():
    client = _mock_client_returning(_valid_plan())
    pack = _pack()
    generate_plan(pack, client=client, per_call_timeout_sec=30.0)
    call = client.chat.completions.parse.call_args_list[0]
    assert call.kwargs["timeout"] == 30.0


# ==============================
# LlmGenerationError の形
# ==============================


def test_generate_plan_mixed_failures_prefers_validation_error():
    """1 回 transport 失敗 + 3 回 validation 失敗 → validation 到達しているので
    LlmGenerationError（計画書 v3 の Codex Must-fix #3 対応）。
    """
    client = _mock_client_returning(
        TimeoutError("t"),
        _invalid_plan_unknown_place_id(),
        _invalid_plan_unknown_place_id(),
        _invalid_plan_unknown_place_id(),
    )
    pack = _pack()
    with pytest.raises(LlmGenerationError):
        generate_plan(pack, client=client)


def test_generate_plan_bad_request_raises_immediately():
    """OpenAI BadRequestError は retry せず即 raise（schema 不整合等、実装バグの可能性）。"""
    try:
        from openai import BadRequestError
    except ImportError:
        pytest.skip("openai SDK not available")

    # BadRequestError は body と response を取るが、テスト用には dummy を渡す
    err = BadRequestError("schema mismatch", response=MagicMock(status_code=400), body={})
    client = _mock_client_returning(err, _valid_plan())
    pack = _pack()
    with pytest.raises(LlmBadRequestError):
        generate_plan(pack, client=client)
    # 1 回目で即 raise、2 回目以降は呼ばれない
    assert client.chat.completions.parse.call_count == 1


def test_generate_plan_timeout_clamped_to_remaining_deadline():
    """残 deadline < per_call_timeout の場合、attempt に渡す timeout が残 deadline で
    clamp されることを確認（計画書 v3 Must-fix #1）。
    """
    client = _mock_client_returning(_valid_plan())
    pack = _pack()
    # per_call 60s だが deadline は 10s なら、10s を下回る timeout で呼ばれる
    generate_plan(
        pack,
        client=client,
        per_call_timeout_sec=60.0,
        global_deadline_sec=10.0,
    )
    call = client.chat.completions.parse.call_args_list[0]
    timeout = call.kwargs["timeout"]
    # deadline 10s - epsilon < timeout <= 10s（min(60, remaining)）
    assert timeout <= 10.0
    assert timeout > 0


def test_llm_generation_error_exposes_issues():
    client = _mock_client_returning(
        _invalid_plan_unknown_place_id(),
        _invalid_plan_unknown_place_id(),
        _invalid_plan_unknown_place_id(),
        _invalid_plan_unknown_place_id(),
    )
    pack = _pack()
    with pytest.raises(LlmGenerationError) as exc_info:
        generate_plan(pack, client=client)
    # 少なくとも 1 つは UnknownPlaceId 種の issue
    kinds = {i.kind for i in exc_info.value.issues}
    from src.llm.validator import IssueKind

    assert IssueKind.UNKNOWN_PLACE_ID in kinds


# ==============================
# Phase 2.1: AssemblyError -> IssueKind マップ（Codex Major 4 対応）
# ==============================


def test_assembly_error_mapping_anchor_missing():
    """AnchorMissingError は IssueKind.ANCHOR_MISSING にマップされ retry prompt に inject される。"""
    from src.llm.assembly import AnchorMissingError
    from src.llm.generator import _assembly_error_to_issue_kind
    from src.llm.validator import IssueKind

    err = AnchorMissingError("anchor mode: 指定 place_id が plan に含まれない: ['ANCHOR1']")
    assert _assembly_error_to_issue_kind(err) == IssueKind.ANCHOR_MISSING


def test_assembly_error_mapping_known_classes():
    """既存 AssemblyError サブクラスのマップが安定して動く（regression check）。"""
    from src.llm.assembly import (
        IneligiblePlaceForSlotError,
        NoFeasibleTransitError,
        UnknownPlaceInSlotError,
        UnknownSlotIdError,
    )
    from src.llm.generator import _assembly_error_to_issue_kind
    from src.llm.validator import IssueKind

    assert _assembly_error_to_issue_kind(UnknownPlaceInSlotError("x")) == IssueKind.UNKNOWN_PLACE_ID
    assert _assembly_error_to_issue_kind(IneligiblePlaceForSlotError("x")) == IssueKind.OUTSIDE_OPENING_HOURS
    assert _assembly_error_to_issue_kind(NoFeasibleTransitError("x")) == IssueKind.UNKNOWN_TRANSIT_EDGE
    assert _assembly_error_to_issue_kind(UnknownSlotIdError("x")) == IssueKind.MISSING_REQUIRED_FIELD


# ==============================
# Phase 1.10 後段 fix: previous_issues の累積化（Codex Major 2）
# ==============================


def test_previous_issues_accumulated_across_attempts(monkeypatch):
    """retry で previous_issues が累積され、過去 attempts の unknown place_id が引き継がれる。

    本番 Run 10 で attempt 1 (unknown_place_id A) → attempt 2 (unknown_transit_edge) →
    attempt 3 (unknown_place_id A 再出現) と起こったケースを検証:
    attempt 3 の prompt には attempt 1 の unknown_place_id A が（直前 attempt 2 で
    別 issue が出た後でも）累積されて含まれる必要がある。
    """
    # 同じ unknown place_id を 3 回連続で生成（attempt 1, 2, 3 全部 fail）→ attempt 4 で成功
    unknown_id = "ChIJ_run10_repro"
    invalid = LlmGeneratedPlan(
        items=[
            LlmPlanItem(
                order_index=0,
                item_type="activity",
                title="観光",
                description=None,
                start_time="2026-06-01T10:00:00+09:00",
                end_time="2026-06-01T12:00:00+09:00",
                place_id=unknown_id,
                cost_jpy=1000,
                cost_confidence="verified",
                transit_ref=None,
            )
        ]
    )
    client = _mock_client_returning(invalid, invalid, invalid, _valid_plan())
    pack = _pack()
    generate_plan(pack, client=client)

    # attempt 4 (fallback) の user prompt に attempt 1 で出した unknown_id が引き継がれていること
    final_call = client.chat.completions.parse.call_args_list[3]
    user_msg = next(
        m for m in final_call.kwargs.get("messages", []) if m["role"] == "user"
    )
    # v1 prompt なので retry_guidance_md は注入されないが、previous_issues_json
    # の中に過去 attempt の issue が残っている（累積化されているか）を確認する。
    assert unknown_id in user_msg["content"]
    # Codex Major 1: UNKNOWN_PLACE_ID 1 件は dedup されて 1 つにまとまる
    # （3 attempts で 3 回出した同じ ID が攻撃的に増殖しない）
    assert user_msg["content"].count(unknown_id) <= 5


def test_issue_dedup_key_unknown_place_id_dedup_by_place_id():
    """`_issue_dedup_key` は UNKNOWN_PLACE_ID を place_id 単位で dedup（複数 slot で同じ ID → 1 つに）。"""
    from src.llm.generator import _issue_dedup_key
    from src.llm.validator import IssueKind, ValidationIssue

    issue1 = ValidationIssue(
        kind=IssueKind.UNKNOWN_PLACE_ID,
        message="LLM assigned unknown place_id 'ChIJ_x' to slot 'day1_lunch'",
        item_index=None,
    )
    issue2 = ValidationIssue(
        kind=IssueKind.UNKNOWN_PLACE_ID,
        message="LLM assigned unknown place_id 'ChIJ_x' to slot 'day1_dinner'",
        item_index=None,
    )
    # 同じ place_id だが slot は別 → message は違う、しかし dedup key は同じ
    assert _issue_dedup_key(issue1) == _issue_dedup_key(issue2)


def test_issue_dedup_key_other_kind_uses_message():
    """UNKNOWN_PLACE_ID 以外は (kind, message) で dedup（同じエラー文を重複させない）。"""
    from src.llm.generator import _issue_dedup_key
    from src.llm.validator import IssueKind, ValidationIssue

    issue1 = ValidationIssue(
        kind=IssueKind.BUDGET_EXCEEDED, message="activity 合計超過", item_index=None
    )
    issue2 = ValidationIssue(
        kind=IssueKind.BUDGET_EXCEEDED, message="lodging 合計超過", item_index=None
    )
    assert _issue_dedup_key(issue1) != _issue_dedup_key(issue2)


def test_dedup_previous_issues_recency_order():
    """Codex review 3 Major 反映: 同じ key の issue が再発したら末尾（直近）に来る。

    `dict[key] = ...` だけでは既存 key の position は更新されないため、
    `pop(key, None)` で削除してから再挿入する実装が必要。
    末尾 N 件スライスで「先に入って再発した issue が落ちる」現象を防ぐ。
    """
    from src.llm.generator import _dedup_previous_issues
    from src.llm.validator import IssueKind, ValidationIssue

    # 同じ unknown place_id 'AAA' が attempt 1 と attempt 5 (再発) で出る場合、
    # 直近 attempt 5 の issue が末尾に来ることを確認する
    issue_aaa_first = ValidationIssue(
        kind=IssueKind.UNKNOWN_PLACE_ID,
        message="LLM assigned unknown place_id 'AAA' to slot 'day1_lunch'",
        item_index=None,
    )
    issue_bbb = ValidationIssue(
        kind=IssueKind.UNKNOWN_PLACE_ID,
        message="LLM assigned unknown place_id 'BBB' to slot 'day1_dinner'",
        item_index=None,
    )
    issue_ccc = ValidationIssue(
        kind=IssueKind.UNKNOWN_PLACE_ID,
        message="LLM assigned unknown place_id 'CCC' to slot 'day2_lunch'",
        item_index=None,
    )
    issue_aaa_again = ValidationIssue(
        kind=IssueKind.UNKNOWN_PLACE_ID,
        message="LLM assigned unknown place_id 'AAA' to slot 'day2_dinner'",  # 別 slot で再発
        item_index=None,
    )

    deduped = _dedup_previous_issues(
        [issue_aaa_first, issue_bbb, issue_ccc, issue_aaa_again]
    )

    # 'AAA' は dedup されて 1 件、最新 (issue_aaa_again) が残る
    aaa_issues = [i for i in deduped if "'AAA'" in i.message]
    assert len(aaa_issues) == 1
    assert aaa_issues[0] is issue_aaa_again  # 直近の issue が残る

    # 順序は BBB → CCC → AAA (再発で末尾に移動)
    assert [i.message for i in deduped] == [
        issue_bbb.message,
        issue_ccc.message,
        issue_aaa_again.message,
    ]


def test_dedup_previous_issues_max_retain_keeps_recent():
    """累積件数が _MAX_RETAIN_PREVIOUS_ISSUES を超えたら直近 N 件を残す。"""
    from src.llm.generator import _dedup_previous_issues, _MAX_RETAIN_PREVIOUS_ISSUES
    from src.llm.validator import IssueKind, ValidationIssue

    # 各 issue は異なる place_id で全部 dedup されない (12 件)
    issues = [
        ValidationIssue(
            kind=IssueKind.UNKNOWN_PLACE_ID,
            message=f"LLM assigned unknown place_id 'PID{i:02d}' to slot 'day1_lunch'",
            item_index=None,
        )
        for i in range(12)
    ]

    deduped = _dedup_previous_issues(issues)

    # 直近 _MAX_RETAIN_PREVIOUS_ISSUES (=10) 件
    assert len(deduped) == _MAX_RETAIN_PREVIOUS_ISSUES
    # 末尾 10 件 = 'PID02' から 'PID11'（最初の 2 件 'PID00', 'PID01' が落ちる）
    assert "'PID02'" in deduped[0].message
    assert "'PID11'" in deduped[-1].message
