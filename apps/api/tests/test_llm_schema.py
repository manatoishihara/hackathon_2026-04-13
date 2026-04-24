"""`apps/api/src/llm/schema.py` のテスト（Phase 1.3d Branch A）。

LlmGeneratedPlan / LlmPlanItem の Pydantic 定義が OpenAI Structured Output の strict 要件
（全フィールド required + additionalProperties: false）を満たすことを確認する。
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from src.llm.schema import (
    LlmGeneratedPlan,
    LlmPlanItem,
    LlmTransitRef,
)


def _valid_activity_kwargs() -> dict:
    return dict(
        order_index=0,
        item_type="activity",
        title="箱根神社参拝",
        description="平和の鳥居で有名な古社、湖上の鳥居で写真撮影",
        start_time="2026-06-01T10:00:00+09:00",
        end_time="2026-06-01T12:00:00+09:00",
        place_id="ChIJ_hakone_jinja",
        cost_jpy=0,
        cost_confidence="verified",
        transit_ref=None,
    )


def _valid_transit_kwargs() -> dict:
    return dict(
        order_index=0,
        item_type="transit",
        title="新宿駅 → 箱根湯本駅",
        description="小田急線 特急ロマンスカー",
        start_time="2026-06-01T09:00:00+09:00",
        end_time="2026-06-01T10:25:00+09:00",
        place_id=None,
        cost_jpy=2470,
        cost_confidence="verified",
        transit_ref={
            "from_place_id": "ChIJ_shinjuku",
            "to_place_id": "ChIJ_hakone_yumoto",
            "departure_time": "09:00",
        },
    )


def test_llm_plan_item_activity():
    item = LlmPlanItem(**_valid_activity_kwargs())
    assert item.item_type == "activity"
    assert item.place_id == "ChIJ_hakone_jinja"
    assert item.transit_ref is None


def test_llm_plan_item_transit_with_ref():
    item = LlmPlanItem(**_valid_transit_kwargs())
    assert item.item_type == "transit"
    assert item.place_id is None
    assert item.transit_ref.from_place_id == "ChIJ_shinjuku"


def test_llm_generated_plan_with_multiple_items():
    plan = LlmGeneratedPlan(
        items=[LlmPlanItem(**_valid_activity_kwargs()), LlmPlanItem(**_valid_transit_kwargs())]
    )
    assert len(plan.items) == 2


def test_llm_plan_item_rejects_unknown_field():
    """extra='forbid' で未知フィールド拒否（strict 対応の additionalProperties: false 担保）"""
    kwargs = _valid_activity_kwargs()
    kwargs["extra_field"] = "hack"
    with pytest.raises(ValidationError):
        LlmPlanItem(**kwargs)


def test_llm_plan_item_rejects_invalid_item_type():
    kwargs = _valid_activity_kwargs()
    kwargs["item_type"] = "breakfast"
    with pytest.raises(ValidationError):
        LlmPlanItem(**kwargs)


def test_llm_plan_item_rejects_invalid_cost_confidence():
    kwargs = _valid_activity_kwargs()
    kwargs["cost_confidence"] = "maybe"
    with pytest.raises(ValidationError):
        LlmPlanItem(**kwargs)


def test_llm_plan_item_rejects_description_over_150_chars():
    kwargs = _valid_activity_kwargs()
    kwargs["description"] = "あ" * 151
    with pytest.raises(ValidationError):
        LlmPlanItem(**kwargs)


def test_llm_plan_item_description_can_be_null():
    kwargs = _valid_activity_kwargs()
    kwargs["description"] = None
    item = LlmPlanItem(**kwargs)
    assert item.description is None


def test_transit_ref_rejects_invalid_departure_time():
    with pytest.raises(ValidationError):
        LlmTransitRef(
            from_place_id="A",
            to_place_id="B",
            departure_time="9:00",  # HH:mm フォーマット違反（1 桁）
        )


def test_transit_ref_accepts_valid_hhmm():
    ref = LlmTransitRef(
        from_place_id="A",
        to_place_id="B",
        departure_time="09:00",
    )
    assert ref.departure_time == "09:00"


def test_model_json_schema_for_llm_generated_plan_includes_required_items():
    """OpenAI Structured Output strict 要件: 全フィールドが required に入っていること。"""
    schema = LlmGeneratedPlan.model_json_schema()
    # items が required
    assert "items" in schema.get("required", [])
    # additionalProperties は false （extra='forbid' による）
    assert schema.get("additionalProperties") is False


def test_model_json_schema_for_llm_plan_item_all_required_even_nullable():
    """nullable フィールドも required 配列に含まれること（OpenAI strict 準拠）。"""
    # $defs 経由で LlmPlanItem の schema を確認
    root_schema = LlmGeneratedPlan.model_json_schema()
    defs = root_schema.get("$defs", {})
    item_schema = defs.get("LlmPlanItem")
    assert item_schema is not None
    required = set(item_schema.get("required", []))
    # 全フィールドが required
    expected_fields = {
        "order_index", "item_type", "title", "description",
        "start_time", "end_time", "place_id", "cost_jpy",
        "cost_confidence", "transit_ref",
    }
    assert expected_fields.issubset(required)
    assert item_schema.get("additionalProperties") is False
