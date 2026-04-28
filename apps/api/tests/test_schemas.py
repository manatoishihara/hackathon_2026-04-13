"""Pydantic モデルの振る舞いテスト。

- 正常構造の構築
- バリデーションエラー（範囲外 / 未知フィールド / 必須未指定）
- JSON ラウンドトリップ
"""

from __future__ import annotations

from datetime import date, datetime

import pytest
from pydantic import ValidationError

from src.schemas import (
    BudgetBreakdown,
    Evidence,
    GeneratePlanRequest,
    Location,
    ParticipantInput,
    Plan,
    PlanItem,
    TransitToNext,
)

# ==============================
# BudgetBreakdown
# ==============================


def test_budget_breakdown_rejects_out_of_range():
    with pytest.raises(ValidationError):
        BudgetBreakdown(lodging=-1, meal=30, activity=20, transit=51)
    with pytest.raises(ValidationError):
        BudgetBreakdown(lodging=101, meal=0, activity=0, transit=0)


def test_budget_breakdown_accepts_valid():
    b = BudgetBreakdown(lodging=40, meal=30, activity=20, transit=10)
    assert b.lodging + b.meal + b.activity + b.transit == 100


def test_budget_breakdown_rejects_unknown_field():
    with pytest.raises(ValidationError):
        BudgetBreakdown(lodging=40, meal=30, activity=20, transit=10, extra=99)  # type: ignore[call-arg]


# ==============================
# Evidence
# ==============================


def test_evidence_optional_fields_default_none():
    ev = Evidence(sources=["Google Places"])
    assert ev.opening_hours is None
    assert ev.rating is None
    assert ev.price_level is None
    assert ev.verified_at is None


def test_evidence_price_level_out_of_range_rejected():
    with pytest.raises(ValidationError):
        Evidence(sources=[], price_level=5)
    with pytest.raises(ValidationError):
        Evidence(sources=[], price_level=0)


# ==============================
# Plan / PlanItem
# ==============================


def _valid_budget() -> BudgetBreakdown:
    return BudgetBreakdown(lodging=40, meal=30, activity=20, transit=10)


def _valid_plan_kwargs() -> dict:
    return dict(
        id="00000000-0000-0000-0000-000000000001",
        session_id="00000000-0000-0000-0000-000000000002",
        title="箱根温泉旅",
        region="神奈川",
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 2),
        departure_point="新宿駅",
        budget_per_person_jpy=30000,
        budget_breakdown=_valid_budget(),
        start_mode="auto",
        mode_payload=None,
        status="draft",
        share_token=None,
        created_at=datetime(2026, 5, 1, 12, 0, 0),
        updated_at=datetime(2026, 5, 1, 12, 0, 0),
    )


def test_plan_accepts_valid():
    plan = Plan(**_valid_plan_kwargs())
    assert plan.title == "箱根温泉旅"
    assert plan.start_mode == "auto"


def test_plan_rejects_invalid_start_mode():
    kwargs = _valid_plan_kwargs()
    kwargs["start_mode"] = "cruise"
    with pytest.raises(ValidationError):
        Plan(**kwargs)


def test_plan_json_roundtrip():
    plan = Plan(**_valid_plan_kwargs())
    data = plan.model_dump(mode="json")
    restored = Plan.model_validate(data)
    assert restored == plan


def test_plan_item_nested_location_and_evidence():
    item = PlanItem(
        id="00000000-0000-0000-0000-000000000101",
        plan_id="00000000-0000-0000-0000-000000000001",
        order_index=0,
        item_type="activity",
        title="箱根神社参拝",
        description=None,
        start_time=datetime(2026, 6, 1, 10, 0),
        end_time=datetime(2026, 6, 1, 11, 0),
        location=Location(
            place_id="abc123",
            place_name="箱根神社",
            lat=35.20,
            lng=139.02,
            address="神奈川県足柄下郡箱根町元箱根80-1",
        ),
        cost_jpy=0,
        cost_confidence="verified",
        evidence=Evidence(sources=["Google Places"]),
        transit_to_next=TransitToNext(
            mode="walk",
            route="徒歩",
            departure_time="11:10",
            duration_min=15,
            fare_jpy=0,
            polyline=None,
        ),
        notes=None,
        created_at=datetime(2026, 5, 1, 12, 0),
        updated_at=datetime(2026, 5, 1, 12, 0),
    )
    assert item.item_type == "activity"
    assert item.transit_to_next and item.transit_to_next.mode == "walk"


# ==============================
# GeneratePlanRequest
# ==============================


# ==============================
# Phase 2.1: GeneratePlanRequest の start_mode × mode_payload 整合検証
# ==============================


def _base_request_kwargs():
    return dict(
        title="箱根温泉旅",
        region="神奈川",
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 2),
        departure_point="新宿駅",
        budget_per_person_jpy=30000,
        budget_breakdown=_valid_budget(),
        participants=[
            ParticipantInput(
                display_name="太郎",
                avatar_color="#D97757",
                wishes_text="温泉でゆっくり",
                tags=["温泉"],
                order_index=0,
            ),
        ],
    )


def test_request_auto_mode_with_null_payload_ok():
    req = GeneratePlanRequest(**_base_request_kwargs(), start_mode="auto", mode_payload=None)
    assert req.start_mode == "auto"


def test_request_auto_mode_with_non_null_payload_rejected():
    """auto モードで mode_payload が non-null なら拒否（user 入力のずれを早期発見）。"""
    with pytest.raises(ValidationError):
        GeneratePlanRequest(
            **_base_request_kwargs(), start_mode="auto", mode_payload={"theme": "onsen"}
        )


def test_request_anchor_mode_with_valid_payload_ok():
    req = GeneratePlanRequest(
        **_base_request_kwargs(),
        start_mode="anchor",
        mode_payload={"anchor_place_ids": ["ChIJ_anchor1", "ChIJ_anchor2"]},
    )
    assert req.start_mode == "anchor"


def test_request_anchor_mode_null_payload_rejected():
    with pytest.raises(ValidationError):
        GeneratePlanRequest(
            **_base_request_kwargs(), start_mode="anchor", mode_payload=None
        )


def test_request_anchor_mode_empty_ids_rejected():
    """anchor_place_ids 空配列は min_length 違反。"""
    with pytest.raises(ValidationError):
        GeneratePlanRequest(
            **_base_request_kwargs(),
            start_mode="anchor",
            mode_payload={"anchor_place_ids": []},
        )


def test_request_anchor_mode_too_many_ids_rejected():
    """anchor_place_ids 4 件以上は max_length=3 違反。"""
    with pytest.raises(ValidationError):
        GeneratePlanRequest(
            **_base_request_kwargs(),
            start_mode="anchor",
            mode_payload={"anchor_place_ids": ["a", "b", "c", "d"]},
        )


def test_request_anchor_mode_id_too_long_rejected():
    """anchor_place_ids の各要素は max_length=255。"""
    with pytest.raises(ValidationError):
        GeneratePlanRequest(
            **_base_request_kwargs(),
            start_mode="anchor",
            mode_payload={"anchor_place_ids": ["a" * 300]},
        )


def test_request_anchor_mode_empty_id_rejected():
    """anchor_place_ids の各要素は非空。"""
    with pytest.raises(ValidationError):
        GeneratePlanRequest(
            **_base_request_kwargs(),
            start_mode="anchor",
            mode_payload={"anchor_place_ids": [""]},
        )


def test_request_anchor_mode_unknown_field_rejected():
    """anchor mode で payload に未知のフィールドが混入したら拒否（_StrictBase の forbid 経由）。"""
    with pytest.raises(ValidationError):
        GeneratePlanRequest(
            **_base_request_kwargs(),
            start_mode="anchor",
            mode_payload={"anchor_place_ids": ["a"], "extra": True},
        )


def test_request_theme_mode_with_valid_theme_ok():
    req = GeneratePlanRequest(
        **_base_request_kwargs(), start_mode="theme", mode_payload={"theme": "onsen"}
    )
    assert req.start_mode == "theme"


def test_request_theme_mode_unknown_theme_rejected():
    with pytest.raises(ValidationError):
        GeneratePlanRequest(
            **_base_request_kwargs(), start_mode="theme", mode_payload={"theme": "unknown_theme"}
        )


def test_request_theme_mode_null_payload_rejected():
    with pytest.raises(ValidationError):
        GeneratePlanRequest(
            **_base_request_kwargs(), start_mode="theme", mode_payload=None
        )


def test_request_anchor_payload_for_theme_mode_rejected():
    """start_mode と mode_payload の形が不一致の場合（anchor キーで theme を呼ぶ等）→ 拒否。"""
    with pytest.raises(ValidationError):
        GeneratePlanRequest(
            **_base_request_kwargs(),
            start_mode="theme",
            mode_payload={"anchor_place_ids": ["a"]},  # anchor の形
        )


def test_generate_plan_request_accepts_multiple_participants():
    req = GeneratePlanRequest(
        title="箱根温泉旅",
        region="神奈川",
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 2),
        departure_point="新宿駅",
        budget_per_person_jpy=30000,
        budget_breakdown=_valid_budget(),
        start_mode="auto",
        mode_payload=None,
        participants=[
            ParticipantInput(
                display_name=f"メンバー{i}",
                avatar_color="#D97757",
                wishes_text="ゆったり過ごしたい",
                tags=["温泉", "和食"],
                order_index=i,
            )
            for i in range(3)
        ],
    )
    assert len(req.participants) == 3


# ==============================
# Phase 2 polish (2026-04-27, A 案撤回): transport_mode の deprecated 受信互換
# ==============================
# 本番 Run 13 で「公共交通機関のみ」モードが NoFeasibleTransitError を誘発したため
# transport_mode toggle 自体を撤回。frontend (TS) は field を完全削除し、新 client は
# 送信しないが、開きっぱなしタブの旧 client が引き続き送ってきても 400 で reject しない
# よう、Pydantic 側は default=None の deprecated field として残置している。
# 本セクションの 2 件で「受信は許容、内部処理は無視」の振る舞いを担保する。


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_generate_plan_request_default_transport_mode_is_none():
    """transport_mode 省略時の default は None（旧 client の互換用 placeholder）。"""
    req = GeneratePlanRequest(
        **_base_request_kwargs(), start_mode="auto", mode_payload=None
    )
    assert req.transport_mode is None


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_generate_plan_request_accepts_deprecated_transport_mode():
    """旧 client が transport_mode='all_modes' / 'public_transit_only' を送ってきても
    ValidationError なく parse 成功（受信 OK、内部処理は QueryContext へ伝播しない）。"""
    for legacy_value in ("all_modes", "public_transit_only"):
        req = GeneratePlanRequest(
            **_base_request_kwargs(),
            start_mode="auto",
            mode_payload=None,
            transport_mode=legacy_value,
        )
        # 受信値はそのまま field に保持されるが、内部 (builder._build_query_context) は
        # この値を使わない。pack/prompt 配線は完全削除済み。
        assert req.transport_mode == legacy_value


def test_generate_plan_request_rejects_unknown_transport_mode():
    """deprecated でも Literal 型の値域は維持する（未知値はバリデーションで弾く）。

    deprecated field でも Pydantic はバリデーションを通す。`req.transport_mode` への
    属性アクセスは行わないので DeprecationWarning は出ない。
    """
    with pytest.raises(ValidationError):
        GeneratePlanRequest(
            **_base_request_kwargs(),
            start_mode="auto",
            mode_payload=None,
            transport_mode="walk_only",  # type: ignore[arg-type]
        )
