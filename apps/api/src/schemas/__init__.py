"""Pydantic v2 スキーマ（正典: docs/data-model.md）。

packages/shared-types/src/index.ts と 1:1 対応。変更手順は同ファイルの冒頭コメント参照。
フィールドの整合性は tests/test_schema_parity.py で自動検証している。
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

_HHMM_PATTERN = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

# ==============================
# 列挙型
# ==============================

StartMode = Literal["auto", "anchor", "theme"]
ItemType = Literal["activity", "meal", "transit", "lodging"]
CostConfidence = Literal["verified", "estimated", "unknown"]
TransitMode = Literal["train", "bus", "walk", "car"]


class _StrictBase(BaseModel):
    """未知フィールドを拒否する共通ベース。TS → Pydantic の落穂を早期検出する。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


# ==============================
# 構造体（entities）
# ==============================


class BudgetBreakdown(_StrictBase):
    lodging: int = Field(ge=0, le=100)
    meal: int = Field(ge=0, le=100)
    activity: int = Field(ge=0, le=100)
    transit: int = Field(ge=0, le=100)


class Plan(_StrictBase):
    id: str
    session_id: str
    title: str
    region: str
    start_date: date
    end_date: date
    departure_point: str
    budget_per_person_jpy: int
    budget_breakdown: BudgetBreakdown
    start_mode: StartMode
    mode_payload: dict[str, Any] | None
    share_token: str | None
    created_at: datetime
    updated_at: datetime


class Participant(_StrictBase):
    id: str
    plan_id: str
    display_name: str
    avatar_color: str
    wishes_text: str
    tags: list[str]
    order_index: int


class Location(_StrictBase):
    place_id: str | None
    place_name: str | None
    lat: float | None
    lng: float | None
    address: str | None


class Evidence(_StrictBase):
    opening_hours: str | None = None
    rating: float | None = None
    price_level: int | None = Field(default=None, ge=1, le=4)
    verified_at: datetime | None = None
    sources: list[str]


class TransitToNext(_StrictBase):
    mode: TransitMode
    route: str
    departure_time: str  # "HH:mm"
    duration_min: int
    fare_jpy: int | None
    polyline: str | None


class PlanItem(_StrictBase):
    id: str
    plan_id: str
    order_index: int
    item_type: ItemType
    title: str
    description: str | None
    start_time: datetime
    end_time: datetime
    location: Location
    cost_jpy: int | None
    cost_confidence: CostConfidence
    evidence: Evidence
    transit_to_next: TransitToNext | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


# ==============================
# API リクエスト / レスポンス
# ==============================


class ParticipantInput(_StrictBase):
    """GeneratePlanRequest.participants の要素（id / plan_id は除外）。

    TS 側は Omit<Participant, "id" | "plan_id"> なのでフィールドを明示的に並べる。
    """

    display_name: str
    avatar_color: str
    wishes_text: str
    tags: list[str]
    order_index: int


class GeneratePlanRequest(_StrictBase):
    title: str
    region: str
    start_date: date
    end_date: date
    departure_point: str
    budget_per_person_jpy: int
    budget_breakdown: BudgetBreakdown
    start_mode: StartMode
    mode_payload: dict[str, Any] | None
    participants: list[ParticipantInput]


class GeneratePlanResponse(_StrictBase):
    plan_id: str


class RegenerateItemRequest(_StrictBase):
    constraint: str | None = None


class RegenerateItemResponse(_StrictBase):
    item: PlanItem


class EvidencePlacesPlaceSummary(_StrictBase):
    """`/api/evidence/places` レスポンスの places 要素。DirectionsService 呼び出しに必要な最小セット。"""

    place_id: str
    name: str
    lat: float
    lng: float


class EvidencePlacesResponse(_StrictBase):
    """`/api/evidence/places` レスポンス全体（Phase 1.3a）。

    evidence_pack_id はサーバー短期キャッシュ (evidence_pack_sessions) の参照。
    フロントはこの id を `/api/plans/generate` で渡すことで本体を参照させる。
    """

    evidence_pack_id: str
    places: list[EvidencePlacesPlaceSummary]


class ClientTransitEdge(_StrictBase):
    """フロント Maps JS SDK で取得した transit を `/api/plans/generate` に送る時の 1 要素（Phase 1.3b）。

    `apps/api/src/evidence/pack.py` の `TransitEdge` と制約を揃える（有向エッジ、同じ
    値域・文字長・HH:mm）。pack.TransitEdge とは重複定義だが API 境界と内部構造を
    分離する目的でそれぞれ別クラスとして定義する。変更時は両方を同期する
    （`.claude/rules/data-model-sync.md` の「計画節の扱い」の運用に準ずる）。
    """

    from_place_id: str = Field(min_length=1, max_length=255)
    to_place_id: str = Field(min_length=1, max_length=255)
    mode: TransitMode
    route_summary: str = Field(min_length=1, max_length=120)
    duration_min: int = Field(ge=0, le=1440)
    fare_jpy: int | None = Field(default=None, ge=0, le=500_000)
    candidate_departures: list[str] = Field(min_length=1, max_length=10)

    @field_validator("candidate_departures")
    @classmethod
    def _validate_hhmm_list(cls, v: list[str]) -> list[str]:
        for dep in v:
            if not _HHMM_PATTERN.match(dep):
                raise ValueError(f"candidate_departures の要素が HH:mm 形式ではない: {dep!r}")
        return v


class PlanGenerationPayload(_StrictBase):
    """POST /api/plans/generate リクエスト（Phase 1.3c で実型化）。

    - evidence_pack_id: evidence_pack_sessions.id の UUID。str ではなく UUID 型で
      先パース段階で形式違反を弾く（DoS + 改ざん対策）。`model_dump(mode="json")` で
      文字列にシリアライズされるので TS 側の `string` 契約と整合する。
    - transit_matrix: required（default なし）。max_length=200 の静的 hard cap で
      巨大ペイロードを先パース段階で弾く。文脈依存の検証（place_id 所属 /
      自己ループ / 距離 / 矛盾重複）は evidence.validator.validate_client_transit_matrix で。
    """

    evidence_pack_id: UUID
    transit_matrix: list[ClientTransitEdge] = Field(max_length=200)


__all__ = [
    # enums
    "StartMode",
    "ItemType",
    "CostConfidence",
    "TransitMode",
    # entities
    "BudgetBreakdown",
    "Plan",
    "Participant",
    "Location",
    "Evidence",
    "TransitToNext",
    "PlanItem",
    # evidence places response + client transit
    "EvidencePlacesPlaceSummary",
    "EvidencePlacesResponse",
    "ClientTransitEdge",
    "PlanGenerationPayload",
    # api
    "ParticipantInput",
    "GeneratePlanRequest",
    "GeneratePlanResponse",
    "RegenerateItemRequest",
    "RegenerateItemResponse",
]
