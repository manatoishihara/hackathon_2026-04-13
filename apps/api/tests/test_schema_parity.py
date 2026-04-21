"""packages/shared-types/src/index.ts と apps/api/src/schemas の整合性検査。

TS と Pydantic は手動で同期する運用なので、フィールド名のドリフトを早期検出する
ためにここに「契約」をハードコードしておく。

- TS / Pydantic どちらを変更した場合も、このファイルの EXPECTED_FIELDS を更新する
- テストが落ちた = 片側しか更新していない → 両側を揃える
- docs/data-model.md が真実の根拠
"""

from __future__ import annotations

from src.schemas import (
    BudgetBreakdown,
    ClientTransitEdge,
    Evidence,
    EvidencePlacesPlaceSummary,
    EvidencePlacesResponse,
    GeneratePlanRequest,
    GeneratePlanResponse,
    Location,
    ParticipantInput,
    Participant,
    Plan,
    PlanItem,
    RegenerateItemRequest,
    RegenerateItemResponse,
    TransitToNext,
)

# フィールド名の期待セット。TS 側 packages/shared-types/src/index.ts と揃えること。
EXPECTED_FIELDS: dict[str, set[str]] = {
    "BudgetBreakdown": {"lodging", "meal", "activity", "transit"},
    "Plan": {
        "id",
        "session_id",
        "title",
        "region",
        "start_date",
        "end_date",
        "departure_point",
        "budget_per_person_jpy",
        "budget_breakdown",
        "start_mode",
        "mode_payload",
        "share_token",
        "created_at",
        "updated_at",
    },
    "Participant": {
        "id",
        "plan_id",
        "display_name",
        "avatar_color",
        "wishes_text",
        "tags",
        "order_index",
    },
    "Location": {"place_id", "place_name", "lat", "lng", "address"},
    "Evidence": {
        "opening_hours",
        "rating",
        "price_level",
        "verified_at",
        "sources",
    },
    "TransitToNext": {
        "mode",
        "route",
        "departure_time",
        "duration_min",
        "fare_jpy",
        "polyline",
    },
    "PlanItem": {
        "id",
        "plan_id",
        "order_index",
        "item_type",
        "title",
        "description",
        "start_time",
        "end_time",
        "location",
        "cost_jpy",
        "cost_confidence",
        "evidence",
        "transit_to_next",
        "notes",
        "created_at",
        "updated_at",
    },
    "ParticipantInput": {
        "display_name",
        "avatar_color",
        "wishes_text",
        "tags",
        "order_index",
    },
    "GeneratePlanRequest": {
        "title",
        "region",
        "start_date",
        "end_date",
        "departure_point",
        "budget_per_person_jpy",
        "budget_breakdown",
        "start_mode",
        "mode_payload",
        "participants",
    },
    "GeneratePlanResponse": {"plan_id"},
    "RegenerateItemRequest": {"constraint"},
    "RegenerateItemResponse": {"item"},
    "EvidencePlacesPlaceSummary": {"place_id", "name", "lat", "lng"},
    "EvidencePlacesResponse": {"evidence_pack_id", "places"},
    "ClientTransitEdge": {
        "from_place_id",
        "to_place_id",
        "mode",
        "route_summary",
        "duration_min",
        "fare_jpy",
        "candidate_departures",
    },
}

_MODELS = {
    "BudgetBreakdown": BudgetBreakdown,
    "Plan": Plan,
    "Participant": Participant,
    "Location": Location,
    "Evidence": Evidence,
    "TransitToNext": TransitToNext,
    "PlanItem": PlanItem,
    "ParticipantInput": ParticipantInput,
    "GeneratePlanRequest": GeneratePlanRequest,
    "GeneratePlanResponse": GeneratePlanResponse,
    "RegenerateItemRequest": RegenerateItemRequest,
    "RegenerateItemResponse": RegenerateItemResponse,
    "EvidencePlacesPlaceSummary": EvidencePlacesPlaceSummary,
    "EvidencePlacesResponse": EvidencePlacesResponse,
    "ClientTransitEdge": ClientTransitEdge,
}


def test_expected_fields_cover_all_models():
    """EXPECTED_FIELDS と _MODELS のキー集合が一致する。モデル追加忘れ検出用。"""
    assert set(EXPECTED_FIELDS.keys()) == set(_MODELS.keys())


def test_client_transit_edge_constraints_match_pack_transit_edge():
    """schemas.ClientTransitEdge と evidence.pack.TransitEdge の Field 制約が同一。

    両方が同じ無効入力セットで ValidationError を出すことを確認する。
    フィールド名だけでなく **制約の同一性**（HH:mm / 値域 / 文字長）をドリフト検出する。
    """
    from pydantic import ValidationError

    from src.evidence.pack import TransitEdge as PackTransitEdge
    from src.schemas import ClientTransitEdge

    valid_kwargs = dict(
        from_place_id="A",
        to_place_id="B",
        mode="car",
        route_summary="車で約30分",
        duration_min=30,
        fare_jpy=None,
        candidate_departures=["09:00"],
    )

    # 両方とも正常入力は受理
    PackTransitEdge(**valid_kwargs)
    ClientTransitEdge(**valid_kwargs)

    # 両方とも同じ違反で ValidationError
    violations = [
        {**valid_kwargs, "from_place_id": ""},            # min_length=1
        {**valid_kwargs, "from_place_id": "x" * 256},     # max_length=255
        {**valid_kwargs, "route_summary": ""},            # min_length=1
        {**valid_kwargs, "route_summary": "あ" * 121},    # max_length=120
        {**valid_kwargs, "duration_min": -1},             # ge=0
        {**valid_kwargs, "duration_min": 1441},           # le=1440
        {**valid_kwargs, "fare_jpy": -1},                 # ge=0
        {**valid_kwargs, "fare_jpy": 500_001},            # le=500000
        {**valid_kwargs, "candidate_departures": []},     # min_length=1
        {**valid_kwargs, "candidate_departures": [f"{h:02d}:00" for h in range(11)]},  # max_length=10
        {**valid_kwargs, "candidate_departures": ["24:00"]},  # HH:mm 範囲外
        {**valid_kwargs, "candidate_departures": ["9:00"]},   # HH:mm 形式違反
    ]
    for bad in violations:
        for Model in (PackTransitEdge, ClientTransitEdge):
            try:
                Model(**bad)
            except ValidationError:
                continue
            raise AssertionError(
                f"{Model.__name__} did not reject invalid input: {bad}"
            )


def test_pydantic_fields_match_contract():
    """各 Pydantic モデルのフィールド集合が EXPECTED_FIELDS と一致する。"""
    mismatches = []
    for name, model in _MODELS.items():
        actual = set(model.model_fields.keys())
        expected = EXPECTED_FIELDS[name]
        if actual != expected:
            missing = expected - actual
            extra = actual - expected
            mismatches.append(
                f"{name}: missing in Pydantic={sorted(missing)}, extra in Pydantic={sorted(extra)}"
            )
    assert not mismatches, "\n  " + "\n  ".join(mismatches)
