"""`apps/api/src/llm/generator.py` のテスト（Phase 1.3d Branch B）。

OpenAI SDK をモックして retry / fallback / deadline の挙動を検証する。
実 API は叩かないのでコスト ゼロ。実経路の確認は Branch C の integration テストで行う。
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest

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
