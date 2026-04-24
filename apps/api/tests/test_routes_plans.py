"""POST /api/plans/generate のユニットテスト（mocked auth + cache + validator + LLM + storage）。

Phase 1.3d で最終化: lock 取得 / LLM 生成 / finalize_plan RPC を Mock で検証する。
実 OpenAI / 実 Supabase は integration テスト（下段）で 1 本だけ確認する。
"""

from __future__ import annotations

import os
from datetime import date
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from src.app import create_app
from src.evidence.pack import (
    BudgetBreakdownJPY,
    BudgetConstraints,
    EvidencePack,
    PlacePoint,
    QueryContext,
    QueryContextParticipant,
    TemporalConstraints,
)
from src.schemas import BudgetBreakdown


@pytest.fixture
def client():
    app = create_app()
    return app.test_client()


def _pack(place_ids: list[str]) -> EvidencePack:
    return EvidencePack(
        query_context=QueryContext(
            region="箱根",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 2),
            departure_point="新宿",
            start_mode="auto",
            mode_payload=None,
            participants=[QueryContextParticipant(name="太郎", wishes="", tags=[])],
        ),
        places=[
            PlacePoint(
                place_id=pid,
                name=f"p-{pid}",
                category=[],
                lat=35.0,
                lng=139.0,
                address="addr",
                opening_hours=[],
                price_level=None,
                rating=None,
                user_ratings_total=None,
            )
            for pid in place_ids
        ],
        transit_matrix=[],
        budget_constraints=BudgetConstraints(
            total_jpy_per_person=30000,
            breakdown_percent=BudgetBreakdown(lodging=40, meal=30, activity=20, transit=10),
            breakdown_jpy=BudgetBreakdownJPY(lodging=12000, meal=9000, activity=6000, transit=3000),
        ),
        temporal_constraints=TemporalConstraints(
            start_datetime="2026-06-01T09:00:00+09:00",
            end_datetime="2026-06-02T20:00:00+09:00",
            total_days=2,
        ),
    )


def _mock_auth(session_id: str = "owner-xyz"):
    user = MagicMock(id=session_id)
    user_resp = MagicMock(user=user)
    instance = MagicMock()
    instance.auth.get_user.return_value = user_resp
    return instance


def _edge(a: str, b: str, mode: str = "train") -> dict:
    return {
        "from_place_id": a,
        "to_place_id": b,
        "mode": mode,
        "route_summary": "JR",
        "duration_min": 30,
        "fare_jpy": 500,
        "candidate_departures": ["09:00"],
    }


def _valid_body(
    pack_id: str | None = None,
    edges: list[dict] | None = None,
    plan_id: str | None = None,
) -> dict:
    return {
        "plan_id": plan_id or str(uuid4()),
        "evidence_pack_id": pack_id or str(uuid4()),
        "transit_matrix": edges if edges is not None else [_edge("A", "B"), _edge("B", "A")],
    }


# ==============================
# 認証
# ==============================


def test_missing_auth_returns_401(client):
    res = client.post("/api/plans/generate", json=_valid_body())
    assert res.status_code == 401


@patch("src.auth.get_supabase_client")
def test_invalid_jwt_returns_401(mock_auth_factory, client):
    instance = MagicMock()
    instance.auth.get_user.side_effect = Exception("expired")
    mock_auth_factory.return_value = instance
    res = client.post(
        "/api/plans/generate",
        json=_valid_body(),
        headers={"Authorization": "Bearer bad"},
    )
    assert res.status_code == 401


# ==============================
# 入力検証
# ==============================


@patch("src.auth.get_supabase_client")
def test_non_json_body_returns_400(mock_auth_factory, client):
    mock_auth_factory.return_value = _mock_auth()
    res = client.post(
        "/api/plans/generate",
        data="not json",
        content_type="text/plain",
        headers={"Authorization": "Bearer ok"},
    )
    assert res.status_code == 400


@patch("src.auth.get_supabase_client")
def test_non_object_json_body_returns_400(mock_auth_factory, client):
    mock_auth_factory.return_value = _mock_auth()
    res = client.post(
        "/api/plans/generate",
        json=["not", "a", "dict"],
        headers={"Authorization": "Bearer ok"},
    )
    assert res.status_code == 400


@patch("src.auth.get_supabase_client")
def test_invalid_pack_uuid_returns_400(mock_auth_factory, client):
    mock_auth_factory.return_value = _mock_auth()
    body = _valid_body(pack_id="not-a-uuid")
    res = client.post(
        "/api/plans/generate",
        json=body,
        headers={"Authorization": "Bearer ok"},
    )
    assert res.status_code == 400


@patch("src.auth.get_supabase_client")
def test_invalid_plan_uuid_returns_400(mock_auth_factory, client):
    mock_auth_factory.return_value = _mock_auth()
    body = _valid_body(plan_id="not-a-uuid")
    res = client.post(
        "/api/plans/generate",
        json=body,
        headers={"Authorization": "Bearer ok"},
    )
    assert res.status_code == 400


@patch("src.auth.get_supabase_client")
def test_too_many_edges_returns_400(mock_auth_factory, client):
    """Pydantic max_length=200 の静的 hard cap で弾かれる（先パース段階）。"""
    mock_auth_factory.return_value = _mock_auth()
    body = _valid_body(edges=[_edge("A", "B") for _ in range(201)])
    res = client.post(
        "/api/plans/generate",
        json=body,
        headers={"Authorization": "Bearer ok"},
    )
    assert res.status_code == 400


@patch("src.auth.get_supabase_client")
def test_validation_error_returns_400(mock_auth_factory, client):
    mock_auth_factory.return_value = _mock_auth()
    body = _valid_body()
    body["transit_matrix"][0]["candidate_departures"] = ["25:00"]  # HH:mm 違反
    res = client.post(
        "/api/plans/generate",
        json=body,
        headers={"Authorization": "Bearer ok"},
    )
    assert res.status_code == 400
    assert "validation" in res.get_json()["error"].lower()


# ==============================
# キャッシュ取得
# ==============================


@patch("src.routes.plan_routes.load_pack")
@patch("src.auth.get_supabase_client")
def test_expired_or_unknown_pack_returns_404(mock_auth_factory, mock_load, client):
    mock_auth_factory.return_value = _mock_auth()
    mock_load.return_value = None
    res = client.post(
        "/api/plans/generate",
        json=_valid_body(),
        headers={"Authorization": "Bearer ok"},
    )
    assert res.status_code == 404


@patch("src.routes.plan_routes.load_pack")
@patch("src.auth.get_supabase_client")
def test_pack_is_loaded_with_owner_session_id(mock_auth_factory, mock_load, client):
    pack_id = str(uuid4())
    mock_auth_factory.return_value = _mock_auth(session_id="owner-zzz")
    mock_load.return_value = _pack(["A", "B"])
    client.post(
        "/api/plans/generate",
        json=_valid_body(pack_id),
        headers={"Authorization": "Bearer ok"},
    )
    args, kwargs = mock_load.call_args
    assert args[0] == pack_id
    assert kwargs["owner_session_id"] == "owner-zzz"


@patch("src.routes.plan_routes.load_pack")
@patch("src.auth.get_supabase_client")
def test_load_pack_db_error_returns_500(mock_auth_factory, mock_load, client):
    """load_pack が raise した場合は 500 に畳み込まれる。"""
    mock_auth_factory.return_value = _mock_auth()
    mock_load.side_effect = RuntimeError("supabase is down")
    res = client.post(
        "/api/plans/generate",
        json=_valid_body(),
        headers={"Authorization": "Bearer ok"},
    )
    assert res.status_code == 500


# ==============================
# Validator 結合
# ==============================


@patch("src.routes.plan_routes.load_pack")
@patch("src.auth.get_supabase_client")
def test_unknown_place_id_in_transit_returns_400(mock_auth_factory, mock_load, client):
    mock_auth_factory.return_value = _mock_auth()
    mock_load.return_value = _pack(["A", "B"])
    body = _valid_body(edges=[_edge("A", "C")])
    res = client.post(
        "/api/plans/generate",
        json=body,
        headers={"Authorization": "Bearer ok"},
    )
    assert res.status_code == 400


# ==============================
# 成功パス（通常 / debug）
# ==============================


# ==============================
# Lock 取得
# ==============================


def _dummy_llm_plan():
    from src.llm.schema import LlmGeneratedPlan, LlmPlanItem

    return LlmGeneratedPlan(
        items=[
            LlmPlanItem(
                order_index=0,
                item_type="activity",
                title="観光",
                description=None,
                start_time="2026-06-01T10:00:00+09:00",
                end_time="2026-06-01T12:00:00+09:00",
                place_id="A",
                cost_jpy=1000,
                cost_confidence="verified",
                transit_ref=None,
            )
        ]
    )


@patch("src.routes.plan_routes.call_finalize_plan")
@patch("src.routes.plan_routes.mark_plan_failed")
@patch("src.routes.plan_routes._generate_plan_llm")
@patch("src.routes.plan_routes.try_lock_plan_for_generation")
@patch("src.routes.plan_routes.load_pack")
@patch("src.auth.get_supabase_client")
def test_happy_path_returns_plan_id(
    mock_auth_factory, mock_load, mock_lock, mock_llm, mock_mark_failed,
    mock_finalize, client
):
    """LLM 成功 → finalize_plan RPC → { plan_id: UUID } 返却。"""
    mock_auth_factory.return_value = _mock_auth()
    mock_load.return_value = _pack(["A", "B"])
    mock_lock.return_value = "acquired"
    mock_llm.return_value = _dummy_llm_plan()

    plan_id = str(uuid4())
    res = client.post(
        "/api/plans/generate",
        json=_valid_body(plan_id=plan_id),
        headers={"Authorization": "Bearer ok"},
    )
    assert res.status_code == 200
    assert res.get_json() == {"plan_id": plan_id}
    # 保存 RPC が呼ばれた
    mock_finalize.assert_called_once()
    # status=failed は呼ばれない
    mock_mark_failed.assert_not_called()


@patch("src.routes.plan_routes.try_lock_plan_for_generation")
@patch("src.routes.plan_routes.load_pack")
@patch("src.auth.get_supabase_client")
def test_lock_not_found_returns_404(mock_auth_factory, mock_load, mock_lock, client):
    mock_auth_factory.return_value = _mock_auth()
    mock_load.return_value = _pack(["A", "B"])
    mock_lock.return_value = "not_found"

    res = client.post(
        "/api/plans/generate",
        json=_valid_body(),
        headers={"Authorization": "Bearer ok"},
    )
    assert res.status_code == 404


@patch("src.routes.plan_routes.try_lock_plan_for_generation")
@patch("src.routes.plan_routes.load_pack")
@patch("src.auth.get_supabase_client")
def test_lock_already_generating_returns_409(
    mock_auth_factory, mock_load, mock_lock, client
):
    mock_auth_factory.return_value = _mock_auth()
    mock_load.return_value = _pack(["A", "B"])
    mock_lock.return_value = "already_generating"

    res = client.post(
        "/api/plans/generate",
        json=_valid_body(),
        headers={"Authorization": "Bearer ok"},
    )
    assert res.status_code == 409


@patch("src.routes.plan_routes.try_lock_plan_for_generation")
@patch("src.routes.plan_routes.load_pack")
@patch("src.auth.get_supabase_client")
def test_lock_already_succeeded_returns_409(
    mock_auth_factory, mock_load, mock_lock, client
):
    mock_auth_factory.return_value = _mock_auth()
    mock_load.return_value = _pack(["A", "B"])
    mock_lock.return_value = "already_succeeded"

    res = client.post(
        "/api/plans/generate",
        json=_valid_body(),
        headers={"Authorization": "Bearer ok"},
    )
    assert res.status_code == 409


@patch("src.routes.plan_routes.try_lock_plan_for_generation")
@patch("src.routes.plan_routes.load_pack")
@patch("src.auth.get_supabase_client")
def test_lock_transport_error_returns_504(
    mock_auth_factory, mock_load, mock_lock, client
):
    from src.plans.storage import RpcTransportError

    mock_auth_factory.return_value = _mock_auth()
    mock_load.return_value = _pack(["A", "B"])
    mock_lock.side_effect = RpcTransportError("lock transport failed")

    res = client.post(
        "/api/plans/generate",
        json=_valid_body(),
        headers={"Authorization": "Bearer ok"},
    )
    assert res.status_code == 504


# ==============================
# LLM 生成
# ==============================


@patch("src.routes.plan_routes.mark_plan_failed")
@patch("src.routes.plan_routes._generate_plan_llm")
@patch("src.routes.plan_routes.try_lock_plan_for_generation")
@patch("src.routes.plan_routes.load_pack")
@patch("src.auth.get_supabase_client")
def test_llm_generation_error_returns_422(
    mock_auth_factory, mock_load, mock_lock, mock_llm, mock_mark_failed, client
):
    from src.llm.generator import LlmGenerationError

    mock_auth_factory.return_value = _mock_auth()
    mock_load.return_value = _pack(["A", "B"])
    mock_lock.return_value = "acquired"
    mock_llm.side_effect = LlmGenerationError(issues=[], attempts=4)

    res = client.post(
        "/api/plans/generate",
        json=_valid_body(),
        headers={"Authorization": "Bearer ok"},
    )
    assert res.status_code == 422
    mock_mark_failed.assert_called_once()


@patch("src.routes.plan_routes.mark_plan_failed")
@patch("src.routes.plan_routes._generate_plan_llm")
@patch("src.routes.plan_routes.try_lock_plan_for_generation")
@patch("src.routes.plan_routes.load_pack")
@patch("src.auth.get_supabase_client")
def test_llm_transport_error_returns_502(
    mock_auth_factory, mock_load, mock_lock, mock_llm, mock_mark_failed, client
):
    from src.llm.generator import LlmTransportError

    mock_auth_factory.return_value = _mock_auth()
    mock_load.return_value = _pack(["A", "B"])
    mock_lock.return_value = "acquired"
    mock_llm.side_effect = LlmTransportError(TimeoutError("t"), attempts=4)

    res = client.post(
        "/api/plans/generate",
        json=_valid_body(),
        headers={"Authorization": "Bearer ok"},
    )
    assert res.status_code == 502
    mock_mark_failed.assert_called_once()


@patch("src.routes.plan_routes.mark_plan_failed")
@patch("src.routes.plan_routes._generate_plan_llm")
@patch("src.routes.plan_routes.try_lock_plan_for_generation")
@patch("src.routes.plan_routes.load_pack")
@patch("src.auth.get_supabase_client")
def test_llm_refusal_returns_422(
    mock_auth_factory, mock_load, mock_lock, mock_llm, mock_mark_failed, client
):
    from src.llm.generator import LlmRefusalError

    mock_auth_factory.return_value = _mock_auth()
    mock_load.return_value = _pack(["A", "B"])
    mock_lock.return_value = "acquired"
    mock_llm.side_effect = LlmRefusalError("safety")

    res = client.post(
        "/api/plans/generate",
        json=_valid_body(),
        headers={"Authorization": "Bearer ok"},
    )
    assert res.status_code == 422
    mock_mark_failed.assert_called_once()


@patch("src.routes.plan_routes.mark_plan_failed")
@patch("src.routes.plan_routes._generate_plan_llm")
@patch("src.routes.plan_routes.try_lock_plan_for_generation")
@patch("src.routes.plan_routes.load_pack")
@patch("src.auth.get_supabase_client")
def test_llm_deadline_exceeded_returns_504(
    mock_auth_factory, mock_load, mock_lock, mock_llm, mock_mark_failed, client
):
    from src.llm.generator import DeadlineExceededError

    mock_auth_factory.return_value = _mock_auth()
    mock_load.return_value = _pack(["A", "B"])
    mock_lock.return_value = "acquired"
    mock_llm.side_effect = DeadlineExceededError("timeout")

    res = client.post(
        "/api/plans/generate",
        json=_valid_body(),
        headers={"Authorization": "Bearer ok"},
    )
    assert res.status_code == 504
    mock_mark_failed.assert_called_once()


@patch("src.routes.plan_routes.mark_plan_failed")
@patch("src.routes.plan_routes._generate_plan_llm")
@patch("src.routes.plan_routes.try_lock_plan_for_generation")
@patch("src.routes.plan_routes.load_pack")
@patch("src.auth.get_supabase_client")
def test_llm_bad_request_returns_500(
    mock_auth_factory, mock_load, mock_lock, mock_llm, mock_mark_failed, client
):
    """LlmBadRequestError（schema 不整合など、実装バグ）→ 500 + status=failed。"""
    from src.llm.generator import LlmBadRequestError

    mock_auth_factory.return_value = _mock_auth()
    mock_load.return_value = _pack(["A", "B"])
    mock_lock.return_value = "acquired"
    mock_llm.side_effect = LlmBadRequestError(RuntimeError("schema mismatch"))

    res = client.post(
        "/api/plans/generate",
        json=_valid_body(),
        headers={"Authorization": "Bearer ok"},
    )
    assert res.status_code == 500
    mock_mark_failed.assert_called_once()


@patch("src.routes.plan_routes.mark_plan_failed")
@patch("src.routes.plan_routes._generate_plan_llm")
@patch("src.routes.plan_routes.try_lock_plan_for_generation")
@patch("src.routes.plan_routes.load_pack")
@patch("src.auth.get_supabase_client")
def test_unexpected_exception_after_lock_marks_failed_and_returns_500(
    mock_auth_factory, mock_load, mock_lock, mock_llm, mock_mark_failed, client
):
    """lock 取得後の想定外例外（LLM 例外階層外）も status=failed に倒して stuck 防止。"""
    mock_auth_factory.return_value = _mock_auth()
    mock_load.return_value = _pack(["A", "B"])
    mock_lock.return_value = "acquired"
    # LLM 例外階層でない RuntimeError を raise
    mock_llm.side_effect = RuntimeError("unexpected bug")

    res = client.post(
        "/api/plans/generate",
        json=_valid_body(),
        headers={"Authorization": "Bearer ok"},
    )
    assert res.status_code == 500
    mock_mark_failed.assert_called_once()


# ==============================
# finalize_plan 保存
# ==============================


@patch("src.routes.plan_routes.mark_plan_failed")
@patch("src.routes.plan_routes.call_finalize_plan")
@patch("src.routes.plan_routes._generate_plan_llm")
@patch("src.routes.plan_routes.try_lock_plan_for_generation")
@patch("src.routes.plan_routes.load_pack")
@patch("src.auth.get_supabase_client")
def test_finalize_transport_error_returns_504_without_marking_failed(
    mock_auth_factory, mock_load, mock_lock, mock_llm, mock_finalize,
    mock_mark_failed, client
):
    """RpcTransportError: commit 済か未実行か不明なので mark_failed しない（DB-3 cleanup に委任）。"""
    from src.plans.storage import RpcTransportError

    mock_auth_factory.return_value = _mock_auth()
    mock_load.return_value = _pack(["A", "B"])
    mock_lock.return_value = "acquired"
    mock_llm.return_value = _dummy_llm_plan()
    mock_finalize.side_effect = RpcTransportError("network blip")

    res = client.post(
        "/api/plans/generate",
        json=_valid_body(),
        headers={"Authorization": "Bearer ok"},
    )
    assert res.status_code == 504
    mock_mark_failed.assert_not_called()


@patch("src.routes.plan_routes.mark_plan_failed")
@patch("src.routes.plan_routes.call_finalize_plan")
@patch("src.routes.plan_routes._generate_plan_llm")
@patch("src.routes.plan_routes.try_lock_plan_for_generation")
@patch("src.routes.plan_routes.load_pack")
@patch("src.auth.get_supabase_client")
def test_finalize_generic_error_returns_500_and_marks_failed(
    mock_auth_factory, mock_load, mock_lock, mock_llm, mock_finalize,
    mock_mark_failed, client
):
    """RPC 内で明示的例外 → status を failed にして 500。"""
    mock_auth_factory.return_value = _mock_auth()
    mock_load.return_value = _pack(["A", "B"])
    mock_lock.return_value = "acquired"
    mock_llm.return_value = _dummy_llm_plan()
    mock_finalize.side_effect = RuntimeError("owner mismatch")

    res = client.post(
        "/api/plans/generate",
        json=_valid_body(),
        headers={"Authorization": "Bearer ok"},
    )
    assert res.status_code == 500
    mock_mark_failed.assert_called_once()


# ==============================
# メソッド制約 / MAX_CONTENT_LENGTH
# ==============================


def test_get_returns_405(client):
    res = client.get("/api/plans/generate")
    assert res.status_code == 405


def test_max_content_length_is_configured(client):
    """MAX_CONTENT_LENGTH=256KB がアプリ設定にあること（setdefault で None 上書きされないことを回帰チェック）。"""
    app = create_app()
    assert app.config["MAX_CONTENT_LENGTH"] == 256 * 1024


@patch("src.auth.get_supabase_client")
def test_over_max_content_length_returns_413(mock_auth_factory, client):
    """256KB を超えるボディは Flask が body 読み込み段階で 413 を返す。

    auth は mock で通し、MAX_CONTENT_LENGTH の境界を単独で検証する。
    実運用では auth が先行する場合もあるが、いずれにせよ body は parse されないので
    DoS 対策としては十分。
    """
    mock_auth_factory.return_value = _mock_auth()
    huge_payload = "x" * (256 * 1024 + 100)
    res = client.post(
        "/api/plans/generate",
        data=huge_payload,
        content_type="application/json",
        headers={"Authorization": "Bearer ok"},
    )
    assert res.status_code == 413


# ==============================
# Integration（live Supabase + live Places, anon サインイン経由）
# ==============================


def _has_full_stack() -> bool:
    return all(
        os.environ.get(k)
        for k in (
            "GOOGLE_MAPS_API_KEY",
            "NEXT_PUBLIC_SUPABASE_URL",
            "NEXT_PUBLIC_SUPABASE_ANON_KEY",
            "SUPABASE_SERVICE_ROLE_KEY",
        )
    ) and len(os.environ.get("GOOGLE_MAPS_API_KEY", "")) > 20


def _places_request_body() -> dict:
    return {
        "title": "箱根温泉旅",
        "region": "箱根",
        "start_date": "2026-06-01",
        "end_date": "2026-06-02",
        "departure_point": "新宿駅",
        "budget_per_person_jpy": 30000,
        "budget_breakdown": {"lodging": 40, "meal": 30, "activity": 20, "transit": 10},
        "start_mode": "auto",
        "mode_payload": None,
        "participants": [
            {
                "display_name": "太郎",
                "avatar_color": "#D97757",
                "wishes_text": "ゆったり温泉",
                "tags": ["温泉"],
                "order_index": 0,
            },
        ],
    }


def _has_full_stack_with_openai() -> bool:
    return _has_full_stack() and bool(os.environ.get("OPENAI_API_KEY"))


@pytest.mark.integration
@pytest.mark.skipif(
    not _has_full_stack_with_openai(),
    reason="full stack env keys (incl. OPENAI_API_KEY) not set",
)
def test_integration_end_to_end_plan_generation(client):
    """/api/evidence/places → plans INSERT → /api/plans/generate でプラン生成完了 → DB に plan_items 保存。

    前提条件:
      - Supabase Extensions で pg_cron 有効化済
      - `supabase/migrations/20260424_04_plan_generation_rpcs.sql` を適用済
      - OPENAI_API_KEY が設定されていて課金可能な状態（1 回の呼び出しは $0.10-0.30）

    transit_matrix はフロント SDK を使わず、1.3a の places から 14km 以内のペアを手動選定。
    14km 以内のペアが見つからない場合は assert fail（距離以外の不具合を skip で隠さない）。
    """
    from math import asin, cos, radians, sin, sqrt
    from uuid import uuid4

    from supabase import create_client

    anon_client = create_client(
        os.environ["NEXT_PUBLIC_SUPABASE_URL"],
        os.environ["NEXT_PUBLIC_SUPABASE_ANON_KEY"],
    )
    sign_in = anon_client.auth.sign_in_anonymously()
    jwt_token = sign_in.session.access_token
    user_id = sign_in.user.id

    # フロント発行の plan_id
    plan_id = str(uuid4())

    try:
        # 1. anon client で plans + participants を INSERT（フロント 1.5 の挙動を再現）
        _ = anon_client.postgrest.auth(jwt_token)  # anon client に JWT を設定
        req_body = _places_request_body()
        plan_row_resp = anon_client.from_("plans").insert({
            "id": plan_id,
            "session_id": user_id,
            "title": req_body["title"],
            "region": req_body["region"],
            "start_date": req_body["start_date"],
            "end_date": req_body["end_date"],
            "departure_point": req_body["departure_point"],
            "budget_per_person_jpy": req_body["budget_per_person_jpy"],
            "budget_breakdown": req_body["budget_breakdown"],
            "start_mode": req_body["start_mode"],
            "mode_payload": req_body["mode_payload"],
            "status": "draft",
        }).execute()
        assert plan_row_resp.data, "plan INSERT failed"
        anon_client.from_("participants").insert([
            {"plan_id": plan_id, **p} for p in req_body["participants"]
        ]).execute()

        # 2. /api/evidence/places
        res = client.post(
            "/api/evidence/places",
            json=req_body,
            headers={"Authorization": f"Bearer {jwt_token}"},
        )
        assert res.status_code == 200, res.get_data(as_text=True)
        places_body = res.get_json()
        evidence_pack_id = places_body["evidence_pack_id"]
        assert len(places_body["places"]) >= 2

        # 3. 14km 以内のペアを能動選定
        def _km(p: dict, q: dict) -> float:
            R = 6371.0
            dlat = radians(q["lat"] - p["lat"])
            dlng = radians(q["lng"] - p["lng"])
            h = (
                sin(dlat / 2) ** 2
                + cos(radians(p["lat"]))
                * cos(radians(q["lat"]))
                * sin(dlng / 2) ** 2
            )
            return 2 * R * asin(sqrt(h))

        chosen_pair = None
        for i, p in enumerate(places_body["places"]):
            for q in places_body["places"][i + 1 :]:
                if _km(p, q) <= 14.0:
                    chosen_pair = (p, q)
                    break
            if chosen_pair:
                break
        assert chosen_pair is not None, (
            "Integration test requires at least one pair within 14km in 箱根 area"
        )
        a = chosen_pair[0]["place_id"]
        b = chosen_pair[1]["place_id"]

        # 4. /api/plans/generate（実 OpenAI 呼び出し）
        body = {
            "plan_id": plan_id,
            "evidence_pack_id": evidence_pack_id,
            "transit_matrix": [_edge(a, b), _edge(b, a)],
        }
        res2 = client.post(
            "/api/plans/generate",
            json=body,
            headers={"Authorization": f"Bearer {jwt_token}"},
        )
        assert res2.status_code == 200, res2.get_data(as_text=True)
        payload = res2.get_json()
        assert payload["plan_id"] == plan_id

        # 5. plan_items が保存されていること
        items_resp = anon_client.from_("plan_items").select("*").eq("plan_id", plan_id).execute()
        assert len(items_resp.data) > 0, "plan_items must be inserted after successful generation"

        # 6. plans.status が 'succeeded' に遷移
        plan_after = anon_client.from_("plans").select("status").eq("id", plan_id).single().execute()
        assert plan_after.data["status"] == "succeeded"
    finally:
        from src.supabase_client import get_supabase_client

        admin_client = get_supabase_client()
        try:
            admin_client.auth.admin.delete_user(user_id)
        except Exception:
            pass


@pytest.mark.integration
@pytest.mark.skipif(not _has_full_stack(), reason="full stack env keys not set")
def test_integration_lock_conflict_returns_409(client):
    """既に status='generating' の plan に対して再 generate すると 409（OpenAI 不要、
    lock 経路のみを live Supabase で確認）。"""
    from uuid import uuid4
    from supabase import create_client

    anon_client = create_client(
        os.environ["NEXT_PUBLIC_SUPABASE_URL"],
        os.environ["NEXT_PUBLIC_SUPABASE_ANON_KEY"],
    )
    sign_in = anon_client.auth.sign_in_anonymously()
    jwt_token = sign_in.session.access_token
    user_id = sign_in.user.id
    anon_client.postgrest.auth(jwt_token)

    plan_id = str(uuid4())
    try:
        # 事前に plan を status='generating' で INSERT
        req_body = _places_request_body()
        anon_client.from_("plans").insert({
            "id": plan_id,
            "session_id": user_id,
            "title": req_body["title"],
            "region": req_body["region"],
            "start_date": req_body["start_date"],
            "end_date": req_body["end_date"],
            "departure_point": req_body["departure_point"],
            "budget_per_person_jpy": req_body["budget_per_person_jpy"],
            "budget_breakdown": req_body["budget_breakdown"],
            "start_mode": req_body["start_mode"],
            "mode_payload": req_body["mode_payload"],
            "status": "generating",
        }).execute()

        # /api/evidence/places でキャッシュ作成
        res = client.post(
            "/api/evidence/places",
            json=req_body,
            headers={"Authorization": f"Bearer {jwt_token}"},
        )
        assert res.status_code == 200
        evidence_pack_id = res.get_json()["evidence_pack_id"]

        # generate → lock already_generating で 409
        res2 = client.post(
            "/api/plans/generate",
            json={
                "plan_id": plan_id,
                "evidence_pack_id": evidence_pack_id,
                "transit_matrix": [],
            },
            headers={"Authorization": f"Bearer {jwt_token}"},
        )
        assert res2.status_code == 409, res2.get_data(as_text=True)
    finally:
        from src.supabase_client import get_supabase_client

        try:
            get_supabase_client().auth.admin.delete_user(user_id)
        except Exception:
            pass


@pytest.mark.integration
@pytest.mark.skipif(not _has_full_stack(), reason="full stack env keys not set")
def test_integration_invalid_transit_returns_400(client):
    """transit_matrix に pack 外の place_id → validator が 400、LLM 呼ばれない（OpenAI 不要）。"""
    from uuid import uuid4
    from supabase import create_client

    anon_client = create_client(
        os.environ["NEXT_PUBLIC_SUPABASE_URL"],
        os.environ["NEXT_PUBLIC_SUPABASE_ANON_KEY"],
    )
    sign_in = anon_client.auth.sign_in_anonymously()
    jwt_token = sign_in.session.access_token
    user_id = sign_in.user.id

    plan_id = str(uuid4())
    try:
        res = client.post(
            "/api/evidence/places",
            json=_places_request_body(),
            headers={"Authorization": f"Bearer {jwt_token}"},
        )
        assert res.status_code == 200
        evidence_pack_id = res.get_json()["evidence_pack_id"]

        # transit_matrix に pack に無い place_id を仕込む
        res2 = client.post(
            "/api/plans/generate",
            json={
                "plan_id": plan_id,
                "evidence_pack_id": evidence_pack_id,
                "transit_matrix": [
                    {
                        "from_place_id": "NOT_IN_PACK",
                        "to_place_id": "ALSO_NOT_IN_PACK",
                        "mode": "train",
                        "route_summary": "JR",
                        "duration_min": 30,
                        "fare_jpy": 500,
                        "candidate_departures": ["09:00"],
                    }
                ],
            },
            headers={"Authorization": f"Bearer {jwt_token}"},
        )
        assert res2.status_code == 400, res2.get_data(as_text=True)
    finally:
        from src.supabase_client import get_supabase_client

        try:
            get_supabase_client().auth.admin.delete_user(user_id)
        except Exception:
            pass
