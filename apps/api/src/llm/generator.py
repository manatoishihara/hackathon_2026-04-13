"""OpenAI による LLM プラン生成（Phase 1.3d、Branch B）。

retry + fallback + deadline + ハルシネーション検出（validator）を組み込んだ
`generate_plan(pack, client=None, ...)` を提供する。

戦略（計画書 v3「リトライ + フォールバックポリシー」節参照）:
    attempt 1-3: gpt-4o + previous_issues を prompt に注入（self-correction）
    attempt 4: gpt-4o-mini（fallback、残 deadline 次第でスキップ可能）

タイムアウト:
    - per_call: 35 秒（計画書）
    - global deadline: 150 秒（計画書、Render HTTP timeout 180s 内に収まる）
    - **各 attempt の timeout = min(per_call, 残 deadline)** に強制して global deadline を絶対に超えない

失敗形:
    - LlmGenerationError: validation が最後まで通らない（ハルシネーション持続）
    - LlmTransportError: OpenAI 通信系例外が続いて 1 度も validation にたどり着かない
    - LlmRefusalError: OpenAI が safety refuse（retry せず即 raise）
    - LlmBadRequestError: schema 違反等の非 retry な OpenAI 例外（即 raise）
    - DeadlineExceededError: global deadline 超過（attempt の呼び出し前に検知）

Structured Output は `client.chat.completions.parse(response_format=LlmGeneratedPlan)` を使用
（OpenAI SDK 1.58+ の GA、strict schema + Pydantic 直渡し）。
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from ..evidence.pack import EvidencePack
from .prompt import build_system_prompt, build_user_prompt, count_prompt_tokens
from .schema import LlmGeneratedPlan
from .validator import ValidationIssue, validate_llm_output

if TYPE_CHECKING:
    from openai import OpenAI

logger = logging.getLogger(__name__)

DEFAULT_PRIMARY_MODEL = "gpt-4o"
DEFAULT_FALLBACK_MODEL = "gpt-4o-mini"
DEFAULT_PER_CALL_TIMEOUT_SEC = 35.0
DEFAULT_GLOBAL_DEADLINE_SEC = 150.0
DEFAULT_MAX_PRIMARY_ATTEMPTS = 3  # attempt 1-3
DEFAULT_MAX_FALLBACK_ATTEMPTS = 1  # attempt 4

# 呼び出し前に「残 deadline がこれ未満なら意味のある応答が返らない」と判断する下限。
# 短すぎると fallback 経路を無駄に 1 attempt 使うだけなので、early abort する。
_MIN_USEFUL_TIMEOUT_SEC = 3.0


class LlmGenerationError(Exception):
    """validator が最後まで通らない（ハルシネーション持続）。"""

    def __init__(self, issues: list[ValidationIssue], attempts: int):
        self.issues = issues
        self.attempts = attempts
        super().__init__(
            f"LLM generation failed after {attempts} attempts with {len(issues)} issues"
        )


class LlmTransportError(Exception):
    """OpenAI 通信系例外が続いて 1 度も validation にたどり着かない。route 側で 502。"""

    def __init__(self, last_error: Exception, attempts: int):
        self.last_error = last_error
        self.attempts = attempts
        super().__init__(
            f"LLM transport error after {attempts} attempts: "
            f"{type(last_error).__name__}: {last_error}"
        )


class LlmRefusalError(Exception):
    """OpenAI が safety refuse（retry せず即 raise、UX 側でエラー表示）。"""


class LlmBadRequestError(Exception):
    """OpenAI が schema 不整合等で BadRequest を返した。実装バグの可能性高、即 raise。"""

    def __init__(self, inner: Exception):
        self.inner = inner
        super().__init__(f"LLM bad request: {type(inner).__name__}: {inner}")


class DeadlineExceededError(Exception):
    """global deadline を使い切った。"""


# OpenAI SDK の例外分類。
# - transport（retry する）: タイムアウト、ネットワーク、429、5xx
# - non-transport（即 raise）: BadRequest、content filter、UnprocessableEntity 等
# `openai` パッケージが無い環境でも import error にしないため実行時に解決する。
def _classify_openai_exception(e: Exception) -> str:
    """return 'transport' | 'bad_request' | 'unknown'"""
    try:
        from openai import (
            APIConnectionError,
            APITimeoutError,
            BadRequestError,
            InternalServerError,
            RateLimitError,
        )
    except ImportError:
        return "unknown"

    if isinstance(e, (APITimeoutError, APIConnectionError, RateLimitError, InternalServerError)):
        return "transport"
    if isinstance(e, BadRequestError):
        return "bad_request"
    # content filter 等の派生は BadRequest か UnprocessableEntity 扱い
    # OpenAI SDK の UnprocessableEntityError も非 retry
    try:
        from openai import UnprocessableEntityError  # type: ignore[attr-defined]
    except ImportError:
        UnprocessableEntityError = None  # type: ignore[assignment]
    if UnprocessableEntityError is not None and isinstance(e, UnprocessableEntityError):
        return "bad_request"

    # builtins の TimeoutError / ConnectionError は transport 扱い（テスト用）
    if isinstance(e, (TimeoutError, ConnectionError)):
        return "transport"

    return "unknown"


def generate_plan(
    pack: EvidencePack,
    *,
    client: "OpenAI | None" = None,
    model_primary: str = DEFAULT_PRIMARY_MODEL,
    model_fallback: str = DEFAULT_FALLBACK_MODEL,
    max_primary_attempts: int = DEFAULT_MAX_PRIMARY_ATTEMPTS,
    max_fallback_attempts: int = DEFAULT_MAX_FALLBACK_ATTEMPTS,
    per_call_timeout_sec: float = DEFAULT_PER_CALL_TIMEOUT_SEC,
    global_deadline_sec: float = DEFAULT_GLOBAL_DEADLINE_SEC,
) -> LlmGeneratedPlan:
    """Evidence Pack から LLM でプランを生成し、validator を通った時点で返す。

    validator 失敗時は issue を prompt に注入して retry。
    primary 3 回で通らなければ fallback model で 1 回。
    それでも通らなければ LlmGenerationError。

    通信エラーが続いた場合は LlmTransportError。
    最後に validation も到達しなければ validation 失敗優先で分類（validator に到達できたら
    それ以降は transport failure を単独理由にしない）。
    """
    if client is None:
        from openai import OpenAI

        client = OpenAI()

    deadline = time.monotonic() + global_deadline_sec
    system_prompt = build_system_prompt()
    previous_issues: list[ValidationIssue] = []
    last_transport_error: Exception | None = None
    reached_validation_at_least_once = False
    attempts = 0

    plan_configs = [
        (model_primary, max_primary_attempts),
        (model_fallback, max_fallback_attempts),
    ]

    for model, max_attempts in plan_configs:
        for _ in range(max_attempts):
            remaining = deadline - time.monotonic()
            if remaining <= _MIN_USEFUL_TIMEOUT_SEC:
                raise DeadlineExceededError(
                    f"global deadline ({global_deadline_sec}s) exhausted "
                    f"before attempt {attempts + 1} (remaining={remaining:.2f}s)"
                )

            # 各 attempt の timeout は「per_call」と「残 deadline」の小さい方に制限。
            # これで global deadline を絶対に超えない。
            effective_timeout = min(per_call_timeout_sec, remaining)

            attempts += 1
            user_prompt = build_user_prompt(pack, previous_issues=previous_issues)
            _ = count_prompt_tokens(system_prompt, user_prompt, model=model)  # warn log

            try:
                completion = client.chat.completions.parse(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    response_format=LlmGeneratedPlan,
                    timeout=effective_timeout,
                )
            except Exception as e:
                kind = _classify_openai_exception(e)
                if kind == "bad_request":
                    # schema 不整合など。retry しても直らないので即 raise
                    logger.error(
                        "LLM attempt %d non-retryable error: %s: %s",
                        attempts,
                        type(e).__name__,
                        e,
                    )
                    raise LlmBadRequestError(e) from e
                # transport / unknown は retry 対象
                last_transport_error = e
                logger.warning(
                    "LLM attempt %d transport error (%s): %s: %s",
                    attempts,
                    kind,
                    type(e).__name__,
                    e,
                )
                continue

            choice = completion.choices[0]
            if getattr(choice.message, "refusal", None):
                # safety refusal は retry 対象外
                raise LlmRefusalError(str(choice.message.refusal))

            parsed: LlmGeneratedPlan = choice.message.parsed
            issues = validate_llm_output(parsed, pack)
            reached_validation_at_least_once = True
            if not issues:
                logger.info(
                    "LLM generation succeeded at attempt %d (model=%s)",
                    attempts,
                    model,
                )
                return parsed

            logger.info(
                "LLM attempt %d (model=%s) produced %d validation issues, retrying",
                attempts,
                model,
                len(issues),
            )
            previous_issues = issues

    # 全 attempts 失敗。分類:
    # - validation に 1 度も到達できなかった → LlmTransportError（通信層が壊れてる）
    # - validation には到達したが最後まで issue が残った → LlmGenerationError（ハルシネーション持続）
    if not reached_validation_at_least_once:
        assert last_transport_error is not None
        raise LlmTransportError(last_transport_error, attempts)
    # previous_issues は validation 到達した時点で set されている（保険で空配列 fallback）
    raise LlmGenerationError(previous_issues, attempts)
