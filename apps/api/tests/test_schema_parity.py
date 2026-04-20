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
    Evidence,
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
}


def test_expected_fields_cover_all_models():
    """EXPECTED_FIELDS と _MODELS のキー集合が一致する。モデル追加忘れ検出用。"""
    assert set(EXPECTED_FIELDS.keys()) == set(_MODELS.keys())


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
