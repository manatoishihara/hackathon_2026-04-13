"""Pydantic v2 スキーマ（正典: docs/data-model.md）。

packages/shared-types/src/index.ts と 1:1 対応。変更手順は同ファイルの冒頭コメント参照。
フィールドの整合性は tests/test_schema_parity.py で自動検証している。
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_HHMM_PATTERN = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

# ==============================
# 列挙型
# ==============================

StartMode = Literal["auto", "anchor", "theme"]
ItemType = Literal["activity", "meal", "transit", "lodging"]
CostConfidence = Literal["verified", "estimated", "unknown"]
TransitMode = Literal["train", "bus", "walk", "car"]
PlanStatus = Literal["draft", "generating", "succeeded", "failed"]
# Phase 2 polish (2026-04-27): 移動手段指定の Literal 型。
# **deprecated since 2026-04-27**: 本番 Run 13 で「公共交通機関のみ」モードが
# `NoFeasibleTransitError` を誘発、UX 上もタクシー前提でこの toggle 自体に意味がないと判断。
# `GeneratePlanRequest.transport_mode` の deprecated field の type 注釈用にのみ残置。
# 内部処理（builder / pack / prompt）からは配線を完全削除済み。
# 次回 cleanup release で field と Literal 型を一緒に削除する想定。
TransportMode = Literal["all_modes", "public_transit_only"]

# Phase 2.1: ThemeKey は themes.py で単一情報源として定義（Codex Minor 5）。
# Pydantic からは re-export して参照経路の後方互換を保つ。
from ..themes import ThemeKey  # noqa: E402,F401


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
    status: PlanStatus
    share_token: str | None
    created_at: datetime
    updated_at: datetime


# Phase 2.1: 出発モード切替 / mode_payload narrow 用 helper モデル。
# Plan.mode_payload は dict[str, Any] | None のままだが、フォーム/API 入力時には
# start_mode 値に応じて以下のどちらかとして validate する。
# Place ID は Google Places の不透明文字列。実例は `ChIJFc0R0G-jGWARNMTt10zT2GY` 等
# だが将来の subtype でハイフン以外の記号が入る可能性もあるので、文字種は厳格にせず
# 長さだけ縛って DoS 級の悪入力を弾く（Codex Critical 1 対応）。
PlaceIdStr = Annotated[str, Field(min_length=1, max_length=255)]


class AnchorModePayload(_StrictBase):
    """anchor モード: 必ず含めたい place_id を 1〜3 件指定。"""

    anchor_place_ids: list[PlaceIdStr] = Field(min_length=1, max_length=3)


class ThemeModePayload(_StrictBase):
    """theme モード: 6 種から 1 つ選択。"""

    theme: ThemeKey


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
    # Phase 3 polish 第 9 段 (2026-04-28): Google Places priceRange を JPY に正規化したもの
    # ({"start": int, "end": int})。TS の `{ start: number; end: number }` 互換 dict 形式
    # で送る (Python 内部 PlacePoint は tuple[int, int] | None で持つが、JSON シリアライズ
    # で list になるため API 境界では dict に変換)。
    price_range_jpy: dict[str, int] | None = None
    # Phase 3 polish 第 9 段: 楽天トラベル等の外部詳細ページ URL。lodging で楽天が
    # 返したらここに入る。Google Places の場合は None (Maps URL は別経路で組み立てる)。
    external_url: str | None = None
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
    # Phase 2 polish (2026-04-27): **deprecated**。旧 client 互換のため受信は許容するが
    # 内部で無視される。本番 Run 13 で「公共交通機関のみ」モードが NoFeasibleTransitError を
    # 誘発したため A 案で撤回（タクシー前提で toggle の意味がない）。default は None にし、
    # 旧値（"all_modes" / "public_transit_only"）を送ってきた client も `extra="forbid"` で
    # 400 reject されないようにする。次回 cleanup release で field 自体を削除予定。
    transport_mode: TransportMode | None = Field(
        default=None,
        deprecated=True,
        description="Deprecated since 2026-04-27. Field is accepted for backward compatibility but ignored.",
    )
    participants: list[ParticipantInput]

    @model_validator(mode="after")
    def _validate_mode_payload_against_start_mode(self) -> "GeneratePlanRequest":
        """Phase 2.1 (Codex Critical 1): start_mode と mode_payload の整合を検証。

        - auto: mode_payload は None（追加情報なし）
        - anchor: AnchorModePayload で validate（anchor_place_ids 1〜3 件、各 1〜255 文字）
        - theme: ThemeModePayload で validate（theme は ThemeKey の 6 値のいずれか）
        不整合は ValidationError で 400 を返す。フロントから来る dict[str, Any] を
        helper モデルで強く narrow して DoS 級悪入力（巨大 list / 異常値）を弾く。
        """
        if self.start_mode == "auto":
            if self.mode_payload is not None:
                raise ValueError(
                    "start_mode='auto' のとき mode_payload は null でなければなりません"
                )
        elif self.start_mode == "anchor":
            if not isinstance(self.mode_payload, dict):
                raise ValueError(
                    "start_mode='anchor' のとき mode_payload (dict) が必須です"
                )
            AnchorModePayload.model_validate(self.mode_payload)
        elif self.start_mode == "theme":
            if not isinstance(self.mode_payload, dict):
                raise ValueError(
                    "start_mode='theme' のとき mode_payload (dict) が必須です"
                )
            ThemeModePayload.model_validate(self.mode_payload)
        return self


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
    """POST /api/plans/generate リクエスト（Phase 1.3c で実型化、1.3c+ で plan_id 追加）。

    - plan_id: フロント（/plan/new submit 時）が crypto.randomUUID() で発行し、
      同時に plans テーブルに INSERT 済みの UUID。1.3d で owner 検証（plans.session_id
      と g.owner_session_id の一致）と plan_items 保存先の特定に使う。
    - evidence_pack_id: evidence_pack_sessions.id の UUID。str ではなく UUID 型で
      先パース段階で形式違反を弾く（DoS + 改ざん対策）。`model_dump(mode="json")` で
      文字列にシリアライズされるので TS 側の `string` 契約と整合する。
    - transit_matrix: required（default なし）。max_length=200 の静的 hard cap で
      巨大ペイロードを先パース段階で弾く。文脈依存の検証（place_id 所属 /
      自己ループ / 距離 / 矛盾重複）は evidence.validator.validate_client_transit_matrix で。
    """

    plan_id: UUID
    evidence_pack_id: UUID
    transit_matrix: list[ClientTransitEdge] = Field(max_length=200)


# ==============================
# Phase 1.9 共有 API（DB-4 / DB-5）
# ==============================


class ShareResponse(_StrictBase):
    """POST /api/plans/:id/share レスポンス（DB-4）。

    既存 share_token があれば再生成せず同一値を返す（実装側でハンドリング）。
    share_url はサーバーで組み立てて返す（フロントで base URL を hard-code させない）。
    """

    share_token: str
    share_url: str


class SharedPlanSummary(_StrictBase):
    """GET /api/plans/shared/:token のレスポンス plan 部分（DB-5）。

    Plan から session_id と share_token を除外した公開版（TS 側 `Omit<Plan, "session_id" | "share_token">`）。
    識別子漏洩を防ぐため、別クラスとして明示的にフィールドを列挙する。
    """

    id: str
    title: str
    region: str
    start_date: date
    end_date: date
    departure_point: str
    budget_per_person_jpy: int
    budget_breakdown: BudgetBreakdown
    start_mode: StartMode
    mode_payload: dict[str, Any] | None
    status: PlanStatus
    created_at: datetime
    updated_at: datetime


class SharedParticipant(_StrictBase):
    """GET /api/plans/shared/:token の participants 要素（DB-5）。

    Participant から plan_id を除外した公開版（TS 側 `Omit<Participant, "plan_id">`）。
    """

    id: str
    display_name: str
    avatar_color: str
    wishes_text: str
    tags: list[str]
    order_index: int


class SharedPlanItem(_StrictBase):
    """GET /api/plans/shared/:token の plan_items 要素（DB-5）。

    PlanItem から plan_id を除外した公開版（TS 側 `Omit<PlanItem, "plan_id">`）。
    """

    id: str
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


class SharedPlanResponse(_StrictBase):
    """GET /api/plans/shared/:token レスポンス全体（DB-5）。"""

    plan: SharedPlanSummary
    participants: list[SharedParticipant]
    plan_items: list[SharedPlanItem]


__all__ = [
    # enums
    "StartMode",
    "ItemType",
    "CostConfidence",
    "TransitMode",
    "TransportMode",
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
    # share api (Phase 1.9 DB-4 / DB-5)
    "ShareResponse",
    "SharedPlanSummary",
    "SharedParticipant",
    "SharedPlanItem",
    "SharedPlanResponse",
]
