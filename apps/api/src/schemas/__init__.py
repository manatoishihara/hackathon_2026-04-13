"""Pydantic v2 スキーマ（正典: docs/data-model.md）。

packages/shared-types/src/index.ts と 1:1 対応。変更手順は同ファイルの冒頭コメント参照。
フィールドの整合性は tests/test_schema_parity.py で自動検証している。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

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
    # evidence places response
    "EvidencePlacesPlaceSummary",
    "EvidencePlacesResponse",
    # api
    "ParticipantInput",
    "GeneratePlanRequest",
    "GeneratePlanResponse",
    "RegenerateItemRequest",
    "RegenerateItemResponse",
]
