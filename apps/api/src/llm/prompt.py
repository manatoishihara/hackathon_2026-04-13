"""LLM プロンプトの builder（Phase 1.3d、Branch A）。

- `build_system_prompt(version)`: prompts/<version>/system.md を読み取り、そのまま返す
- `build_user_prompt(pack, previous_issues, version)`: prompts/<version>/user_template.md の
  placeholder を JSON で埋めて返す。previous_issues は issue list を JSON 化して LLM に
  自己訂正させる
- `count_prompt_tokens(system, user)`: tiktoken で gpt-4o のエンコーダを使ってトークン数を数える
- `load_prompt_version()`: 環境変数 PROMPT_VERSION、なければ v1.0.0

prompt のテキスト自体は `prompts/<version>/system.md` / `user_template.md` にある。diff レビュー
しやすいよう Python リテラルに埋め込まず外部ファイルにしている（将来の A/B テストにも有利）。
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, is_dataclass
from pathlib import Path

import tiktoken

from ..evidence.pack import EvidencePack, PlacePoint
from .validator import ValidationIssue

logger = logging.getLogger(__name__)

PROMPT_VERSION_DEFAULT = "v1.0.0"
_PROMPTS_ROOT = Path(__file__).parent / "prompts"
_TOKEN_WARNING_THRESHOLD = 12_000


def load_prompt_version() -> str:
    """環境変数 PROMPT_VERSION、なければ v1.0.0。"""
    return os.environ.get("PROMPT_VERSION", PROMPT_VERSION_DEFAULT)


def build_system_prompt(*, version: str | None = None) -> str:
    version = version or load_prompt_version()
    path = _PROMPTS_ROOT / version / "system.md"
    if not path.exists():
        raise FileNotFoundError(f"system prompt not found: {path}")
    return path.read_text(encoding="utf-8")


def build_user_prompt(
    pack: EvidencePack,
    *,
    previous_issues: list[ValidationIssue] | None = None,
    version: str | None = None,
) -> str:
    version = version or load_prompt_version()
    template_path = _PROMPTS_ROOT / version / "user_template.md"
    if not template_path.exists():
        raise FileNotFoundError(f"user prompt template not found: {template_path}")

    template = template_path.read_text(encoding="utf-8")
    ctx_json = _to_json(pack.query_context.model_dump(mode="json"))
    places_json = _to_json([_place_for_llm(p) for p in pack.places])
    transit_json = _to_json([edge.model_dump(mode="json") for edge in pack.transit_matrix])
    budget_json = _to_json(pack.budget_constraints.model_dump(mode="json"))
    temporal_json = _to_json(pack.temporal_constraints.model_dump(mode="json"))
    issues_json = _to_json([_issue_to_dict(i) for i in (previous_issues or [])])

    return template.format(
        query_context_json=ctx_json,
        evidence_pack_places_json=places_json,
        transit_matrix_json=transit_json,
        budget_constraints_json=budget_json,
        temporal_constraints_json=temporal_json,
        previous_issues_json=issues_json,
    )


def count_prompt_tokens(system: str, user: str, *, model: str = "gpt-4o") -> int:
    """system + user の概算トークン数を返し、閾値超過時に警告ログを出す。

    OpenAI の chat completion トークン計算には messages フォーマット化のオーバーヘッド
    (数 token) が加わるが、ここでは concat して概算する（コスト管理用のラフな指標）。
    """
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")
    total = len(encoding.encode(system)) + len(encoding.encode(user))
    if total > _TOKEN_WARNING_THRESHOLD:
        logger.warning(
            "LLM prompt token count (%d) exceeds threshold (%d)",
            total,
            _TOKEN_WARNING_THRESHOLD,
        )
    return total


# ==============================
# Private helpers
# ==============================


def _to_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=_default)


def _default(obj: object):
    if is_dataclass(obj) and not isinstance(obj, type):
        return asdict(obj)
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    raise TypeError(f"non-serializable: {type(obj).__name__}")


def _place_for_llm(place: PlacePoint) -> dict:
    """LLM プロンプト用に PlacePoint から冗長フィールドを落とす。

    address / user_ratings_total はプランニングに不要、トークン節約のため除外。
    """
    return {
        "place_id": place.place_id,
        "name": place.name,
        "category": place.category,
        "lat": place.lat,
        "lng": place.lng,
        "opening_hours": [s.model_dump() for s in place.opening_hours],
        "opening_hours_unknown_days": place.opening_hours_unknown_days,
        "price_level": place.price_level,
        "rating": place.rating,
        "relevance_tags": place.relevance_tags,
    }


def _issue_to_dict(issue: ValidationIssue) -> dict:
    return {
        "kind": issue.kind.value,
        "message": issue.message,
        "item_index": issue.item_index,
    }
