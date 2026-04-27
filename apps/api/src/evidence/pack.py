"""Evidence Pack 用の Pydantic モデル（サーバー専用、DB には保存しない）。

docs/evidence-pack.md の「データ構造」セクションと 1:1 で対応する。

**フロント公開範囲**: `EvidencePack` 型そのものはサーバー専用で shared-types には
含めない。フロントは以下だけを API 経由でやりとりする:
- `/api/evidence/places` のレスポンス: `evidence_pack_id` + `places` の部分集合
  （place_id / name / lat / lng など DirectionsService 呼び出しに必要な最小限、
  Phase 1.3 で型を shared-types に追加する）
- `/api/plans/generate` のリクエスト: `evidence_pack_id` + `TransitEdge` 配列

**⚠️ Phase 1.2 時点では未防御**: 本ファイルの Pydantic Field 制約は
「値域・文字長・HH:mm」は守るが、フロント改ざん経由の `place_id` 所属検証は
Phase 1.3 の Transit Validator（別モジュール）で実装予定。現状は builder が
transit_matrix=[] で返すので攻撃面は表に出ていない。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..schemas import BudgetBreakdown, StartMode, TransitMode

_HHMM_PATTERN = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class _PackBase(BaseModel):
    """Evidence Pack 用の共通ベース。未知フィールドを拒否する。"""

    model_config = ConfigDict(extra="forbid")


# ==============================
# 入力となる QueryContext
# ==============================


class QueryContextParticipant(_PackBase):
    """LLM プロンプト用にスリムにした参加者表現。"""

    name: str
    wishes: str
    tags: list[str]


class QueryContext(_PackBase):
    region: str
    start_date: date
    end_date: date
    departure_point: str
    start_mode: StartMode
    mode_payload: dict[str, Any] | None = None
    # Phase 2 polish (2026-04-27): 移動手段指定を Pack 経由で LLM プロンプトに届ける。
    # default 'all_modes' で後方互換（既存 Pack fixtures が transport_mode 未指定でも壊れない）。
    transport_mode: Literal["all_modes", "public_transit_only"] = "all_modes"
    participants: list[QueryContextParticipant]


# ==============================
# 候補スポット・経路
# ==============================


class OpeningHoursSlot(_PackBase):
    """営業時間 1 枠（曜日 + 開店 / 閉店時刻）。Phase 1.3d で導入。

    1 日に複数枠ある店（ランチ + ディナー）は同じ day_of_week で複数 slot を持つ。
    day_of_week は Python の datetime.weekday() と互換: 月=0 〜 日=6。
    24 時間営業は open_hhmm="00:00" + close_hhmm="23:59" で表現（日跨ぎを許容しない設計）。
    """

    day_of_week: Literal[0, 1, 2, 3, 4, 5, 6]
    open_hhmm: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    close_hhmm: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


class PlacePoint(_PackBase):
    place_id: str
    name: str
    category: list[str]
    lat: float
    lng: float
    address: str
    opening_hours: list[OpeningHoursSlot]
    """正規化済みの営業時間枠。Google の weekdayDescriptions を `parse_weekday_descriptions` で
    構造化したもの（Phase 1.3d で構造化、旧 list[str] から置換）。"""
    opening_hours_unknown_days: list[int] = Field(default_factory=list)
    """parse できなかった曜日（月=0〜日=6）。validator はここに含まれる曜日の営業時間検証を
    スキップする。"11時〜店主の気分" 等の非定型フォーマットが typically 該当。"""
    price_level: Literal[1, 2, 3, 4] | None
    rating: float | None
    user_ratings_total: int | None
    relevance_tags: list[str] = Field(default_factory=list)
    """参加者の希望とのマッチ度ラベル。Phase 1.3 で埋める（現状は常に空）。"""


class TransitEdge(_PackBase):
    """2 スポット間の経路情報。**有向エッジ**（A→B と B→A は別レコード）。

    フロント改ざん・DoS を防ぐため全フィールドに厳しめの制約をかけている。
    サーバー側 validator（Phase 1.3）では加えて `from_place_id` / `to_place_id`
    が EvidencePack.places に含まれることを検証する。
    """

    from_place_id: str = Field(min_length=1, max_length=255)
    to_place_id: str = Field(min_length=1, max_length=255)
    mode: TransitMode
    route_summary: str = Field(min_length=1, max_length=120)
    duration_min: int = Field(ge=0, le=1440)  # 24h 上限
    fare_jpy: int | None = Field(default=None, ge=0, le=500_000)
    candidate_departures: list[str] = Field(min_length=1, max_length=10)
    """出発時刻候補（HH:mm 形式、1〜10 個）。Phase 1.2 では 1 要素、Phase 1.3 で複数化。"""

    @field_validator("candidate_departures")
    @classmethod
    def _validate_hhmm_list(cls, v: list[str]) -> list[str]:
        for dep in v:
            if not _HHMM_PATTERN.match(dep):
                raise ValueError(f"candidate_departures の要素が HH:mm 形式ではない: {dep!r}")
        return v


# ==============================
# 予算・時間の展開結果
# ==============================


class BudgetBreakdownJPY(_PackBase):
    lodging: int
    meal: int
    activity: int
    transit: int


class BudgetConstraints(_PackBase):
    total_jpy_per_person: int
    breakdown_percent: BudgetBreakdown
    breakdown_jpy: BudgetBreakdownJPY


class TemporalConstraints(_PackBase):
    start_datetime: datetime
    end_datetime: datetime
    total_days: int
    check_in_earliest: str = "15:00"
    check_out_latest: str = "10:00"


class LodgingOption(_PackBase):
    """宿泊候補（楽天トラベル API から取得）。"""

    place_id: str
    name: str
    price_jpy_per_night: int
    lat: float | None = None
    lng: float | None = None
    url: str | None = None


# ==============================
# 最終出力
# ==============================


class EvidencePack(_PackBase):
    query_context: QueryContext
    places: list[PlacePoint]
    transit_matrix: list[TransitEdge]
    lodging_options: list[LodgingOption] | None = None
    budget_constraints: BudgetConstraints
    temporal_constraints: TemporalConstraints
