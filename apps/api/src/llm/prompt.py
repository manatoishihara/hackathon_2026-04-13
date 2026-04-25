"""LLM プロンプトの builder（Phase 1.3d、Branch A）。

- `build_system_prompt(version)`: prompts/<version>/system.md を読み取り、そのまま返す
- `build_user_prompt(pack, previous_issues, version)`: prompts/<version>/user_template.md の
  placeholder を JSON で埋めて返す。previous_issues は issue list を JSON 化して LLM に
  自己訂正させる
- `count_prompt_tokens(system, user)`: tiktoken で gpt-4o のエンコーダを使ってトークン数を数える
- `load_prompt_version()`: 環境変数 PROMPT_VERSION、なければ v2.0.0
  （Phase 1.3e で実証された hallucination 0% / success 100% の構造化版。
   v1.0.0 は legacy 検証用に残しているのみ）

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

from ..evidence.pack import EvidencePack, PlacePoint, TransitEdge
from ..themes import get_label as _theme_label
from .validator import ValidationIssue

logger = logging.getLogger(__name__)

PROMPT_VERSION_DEFAULT = "v2.0.0"
_PROMPTS_ROOT = Path(__file__).parent / "prompts"
_TOKEN_WARNING_THRESHOLD = 12_000

# Phase 2.1: theme key → 日本語ラベルは src/themes.py の THEME_REGISTRY を参照
# （Codex Minor 5）。`_theme_label(theme)` で str | None を取得。


def load_prompt_version() -> str:
    """環境変数 PROMPT_VERSION、なければ v2.0.0（Phase 1.3e で実証された構造化版）。"""
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
    """v1 / v2 共通の user prompt builder。

    v2 template は `{slot_catalog_json}` を追加で使い、`{temporal_constraints_json}` は
    使わない（slot_catalog に包含）。format の未使用引数は無視されるので、常に全引数を渡す。
    """
    # assembly は v1 路でも利用（スロット情報は v1 LLM には見せないが、引数は無視される）
    from .assembly import (
        compute_eligible_slot_ids_for_place,
        generate_slot_catalog,
    )

    version = version or load_prompt_version()
    template_path = _PROMPTS_ROOT / version / "user_template.md"
    if not template_path.exists():
        raise FileNotFoundError(f"user prompt template not found: {template_path}")

    template = template_path.read_text(encoding="utf-8")
    ctx_json = _to_json(pack.query_context.model_dump(mode="json"))
    catalog = generate_slot_catalog(pack.temporal_constraints.total_days)
    if version.startswith("v2"):
        # v2: 各 place に eligible_for_slots を付与（Phase 1.3e (iv) per-slot tailored）。
        # LLM は eligible_for_slots に含まれる slot_id にのみ place を割当てるよう誘導。
        base_date = pack.temporal_constraints.start_datetime.date()
        places_json = _to_json(
            [
                {
                    **_place_for_llm(p),
                    "eligible_for_slots": compute_eligible_slot_ids_for_place(
                        p, slot_catalog=catalog, base_date=base_date
                    ),
                }
                for p in pack.places
            ]
        )
    else:
        places_json = _to_json([_place_for_llm(p) for p in pack.places])
    if version.startswith("v2"):
        # v2 (LCaMO 応用): LLM は transit_matrix を「到達可能ペア」としてしか使わない。
        # mode / route_summary / duration_min / fare_jpy / candidate_departures は
        # assembler が元の TransitEdge から決定論で埋めるため、LLM 表現に含めるのは無駄。
        # 75 edge × ~30 tokens 削減で約 -2k tokens の効果（@tasks/lessons.md 2026-04-25）。
        transit_json = _to_json([_edge_for_llm_v2(edge) for edge in pack.transit_matrix])
    else:
        # v1 は LLM が transit_ref.departure_time を直接生成するため full edge 必須
        transit_json = _to_json(
            [edge.model_dump(mode="json") for edge in pack.transit_matrix]
        )
    budget_json = _to_json(pack.budget_constraints.model_dump(mode="json"))
    temporal_json = _to_json(pack.temporal_constraints.model_dump(mode="json"))
    issues_json = _to_json([_issue_to_dict(i) for i in (previous_issues or [])])
    slot_catalog_json = _to_json(catalog)
    mode_context_md = _build_mode_context_md(pack.query_context)

    return template.format(
        query_context_json=ctx_json,
        evidence_pack_places_json=places_json,
        transit_matrix_json=transit_json,
        budget_constraints_json=budget_json,
        temporal_constraints_json=temporal_json,
        previous_issues_json=issues_json,
        slot_catalog_json=slot_catalog_json,
        mode_context_md=mode_context_md,
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

    除外:
      - address / user_ratings_total: プランニングに不要
      - lat / lng: LLM が直接使わない（空間判断は transit_matrix で間接参照）
      - relevance_tags: Phase 1.3 時点で空配列運用、冗長
    これでトークン数を約 20〜30% 圧縮できる想定（@tasks/lessons.md 2026-04-25）。
    """
    return {
        "place_id": place.place_id,
        "name": place.name,
        "category": place.category,
        "opening_hours": [s.model_dump() for s in place.opening_hours],
        "opening_hours_unknown_days": place.opening_hours_unknown_days,
        "price_level": place.price_level,
        "rating": place.rating,
    }


def _edge_for_llm_v2(edge: TransitEdge) -> dict:
    """v2 用に TransitEdge を `{from, to}` 2 フィールドに縮小（LCaMO 介入カタログ縮小）。"""
    return {"from": edge.from_place_id, "to": edge.to_place_id}


def _build_mode_context_md(query_context) -> str:
    """Phase 2.1: start_mode に応じた追加指示を Markdown 文字列で返す。

    - auto: 空文字（mode_context セクションは空）
    - anchor: 必須 place_id を箇条書きし、必ず slot に割当てる旨明示
    - theme: 日本語テーマ label と bias 指示を 1 行で
    payload が壊れてる場合は安全側に倒して空文字を返す。
    """
    mode = query_context.start_mode
    payload = query_context.mode_payload
    if mode == "anchor":
        if not isinstance(payload, dict):
            return ""
        ids = payload.get("anchor_place_ids")
        if not isinstance(ids, list) or not ids:
            return ""
        bullets = "\n".join(f"- {pid}" for pid in ids if isinstance(pid, str))
        if not bullets:
            return ""
        return (
            "アンカー（必須スポット）: 以下の place_id を**必ず**いずれかの slot に割当てよ。"
            "他の slot は通常通り選定。\n" + bullets
        )
    if mode == "theme":
        if not isinstance(payload, dict):
            return ""
        theme = payload.get("theme")
        if not isinstance(theme, str):
            return ""
        label = _theme_label(theme) or theme
        return (
            f"テーマ: {label}。slot 構成と place 選定をこのテーマ寄りに bias せよ。"
            "ただし参加者の wishes / tags が衝突する場合は参加者希望を優先する。"
        )
    return ""


def _issue_to_dict(issue: ValidationIssue) -> dict:
    return {
        "kind": issue.kind.value,
        "message": issue.message,
        "item_index": issue.item_index,
    }
