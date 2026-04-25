"""LLM が生成する Plan の Pydantic スキーマ（Phase 1.3d）。

OpenAI Structured Output (`client.chat.completions.parse(response_format=LlmGeneratedPlan)`)
に直接渡す。strict 要件を満たすため:
- 全フィールドが required（optional は `type | None` で表現、default なしで明示必須）
- `model_config = ConfigDict(extra="forbid")` で `additionalProperties: false`
- nullable は `type | None` → anyOf: [type, null] に自動展開

**注**: このスキーマは evidence-pack.md の「出力 JSON Schema」節と 1:1 対応。変更時は正典も更新すること。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _LlmBase(BaseModel):
    """LLM 出力用の共通ベース（strict 要件: additionalProperties: false）。"""

    model_config = ConfigDict(extra="forbid")


class LlmTransitRef(_LlmBase):
    """transit item が参照する transit_matrix の edge（from/to + 出発時刻）。"""

    from_place_id: str = Field(min_length=1)
    to_place_id: str = Field(min_length=1)
    departure_time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


class LlmPlanItem(_LlmBase):
    """LLM が生成する 1 アイテム。

    item_type ごとの必須項目は validator で検証（schema 定義だけでは表現できないため）:
    - activity / meal / lodging → place_id 必須、transit_ref は null
    - transit → transit_ref 必須、place_id は null 可
    """

    order_index: int = Field(ge=0)
    item_type: Literal["activity", "meal", "transit", "lodging"]
    title: str = Field(min_length=1, max_length=120)
    description: str | None = Field(max_length=150)
    start_time: str = Field(description="ISO 8601、JST オフセット付き")
    end_time: str = Field(description="ISO 8601、JST オフセット付き")
    place_id: str | None
    cost_jpy: int | None = Field(ge=0)
    cost_confidence: Literal["verified", "estimated", "unknown"]
    transit_ref: LlmTransitRef | None


class LlmGeneratedPlan(_LlmBase):
    """`client.chat.completions.parse(response_format=LlmGeneratedPlan)` で受け取るルート。"""

    items: list[LlmPlanItem]


# ==============================
# v2 (Structured Plan Assembly, LCaMO 論文応用、Phase 1.3e)
# ==============================
# LLM の役割を「slot_id と place_id の割当 + 選定理由」のみに縮小。
# start_time / end_time / transit_ref / cost_jpy はサーバ側の assembler が決定論的に埋める。
# 論文: 石原・中村 2026「LLM-guided Causal Multi-objective Optimizer」
# 詳細: tasks/plans/2026-04-25-structured-plan-assembly.md


class LlmSlotAssignment(_LlmBase):
    """LLM が 1 slot に割り当てる place 情報（LlmGeneratedPlanV2 の要素）。

    slot_id は assembly.SLOT_CATALOG のキーに限定される（prompt で提示、LLM は列挙型として選択）。
    place_id は pack.places に含まれる id のみ有効。非存在は assembler が構造エラーとして raise。
    """

    slot_id: str = Field(min_length=1, max_length=40)
    place_id: str = Field(min_length=1)
    rationale: str = Field(
        min_length=10,
        max_length=80,
        description="20〜60 文字推奨、参加者希望との接続を示す短文",
    )


class LlmGeneratedPlanV2(_LlmBase):
    """v2 LLM 出力ルート（Structured Plan Assembly）。

    `items` のような時刻・transit・cost を LLM に吐かせない。全ては slot 割当から
    assembler が決定論的に組み立てる。
    """

    slots: list[LlmSlotAssignment]
