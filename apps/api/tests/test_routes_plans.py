"""POST /api/plans/generate のユニットテスト（mocked auth + cache + validator）。

Phase 1.3c では LLM 未接続。通常レスポンスは `{ plan_id: null }`。
`?debug=1` のときのみ `{ plan_id: null, evidence_pack: {...} }` を返す。
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


@patch("src.routes.plan_routes.load_pack")
@patch("src.auth.get_supabase_client")
def test_happy_path_default_returns_only_plan_id_null(
    mock_auth_factory, mock_load, client
):
    mock_auth_factory.return_value = _mock_auth()
    mock_load.return_value = _pack(["A", "B"])
    res = client.post(
        "/api/plans/generate",
        json=_valid_body(),
        headers={"Authorization": "Bearer ok"},
    )
    assert res.status_code == 200
    body = res.get_json()
    assert body == {"plan_id": None}


@patch("src.routes.plan_routes.load_pack")
@patch("src.auth.get_supabase_client")
def test_happy_path_debug_mode_returns_merged_pack(
    mock_auth_factory, mock_load, client
):
    mock_auth_factory.return_value = _mock_auth()
    mock_load.return_value = _pack(["A", "B"])
    res = client.post(
        "/api/plans/generate?debug=1",
        json=_valid_body(edges=[_edge("A", "B"), _edge("B", "A")]),
        headers={"Authorization": "Bearer ok"},
    )
    assert res.status_code == 200
    payload = res.get_json()
    assert payload["plan_id"] is None
    pack = payload["evidence_pack"]
    assert len(pack["transit_matrix"]) == 2
    keys = {(e["from_place_id"], e["to_place_id"]) for e in pack["transit_matrix"]}
    assert keys == {("A", "B"), ("B", "A")}
    assert {p["place_id"] for p in pack["places"]} == {"A", "B"}


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


@pytest.mark.integration
@pytest.mark.skipif(not _has_full_stack(), reason="full stack env keys not set")
def test_integration_evidence_to_generate_round_trip(client):
    """1.3a で取得した evidence_pack_id に対して 1.3c (?debug=1) を叩き、merged pack が返ることを確認。

    transit_matrix はフロント SDK を使わず、1.3a の places から手動で 14km 以内のペアを
    選んで 2 件組む（skip で距離以外の不具合を隠さないため、見つからない場合は assert fail）。
    """
    from math import asin, cos, radians, sin, sqrt

    from supabase import create_client

    anon_client = create_client(
        os.environ["NEXT_PUBLIC_SUPABASE_URL"],
        os.environ["NEXT_PUBLIC_SUPABASE_ANON_KEY"],
    )
    sign_in = anon_client.auth.sign_in_anonymously()
    jwt_token = sign_in.session.access_token
    user_id = sign_in.user.id

    try:
        res = client.post(
            "/api/evidence/places",
            json=_places_request_body(),
            headers={"Authorization": f"Bearer {jwt_token}"},
        )
        assert res.status_code == 200, res.get_data(as_text=True)
        places_body = res.get_json()
        pack_id = places_body["evidence_pack_id"]
        assert len(places_body["places"]) >= 2

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
                if _km(p, q) <= 14.0:  # 15km 上限の内側にマージン
                    chosen_pair = (p, q)
                    break
            if chosen_pair:
                break
        assert chosen_pair is not None, (
            "Integration test requires at least one pair within 14km in 箱根 area; "
            "Places search returned only distant spots."
        )
        a = chosen_pair[0]["place_id"]
        b = chosen_pair[1]["place_id"]

        body = {
            "evidence_pack_id": pack_id,
            "transit_matrix": [_edge(a, b), _edge(b, a)],
        }
        res2 = client.post(
            "/api/plans/generate?debug=1",
            json=body,
            headers={"Authorization": f"Bearer {jwt_token}"},
        )
        assert res2.status_code == 200, res2.get_data(as_text=True)
        payload = res2.get_json()
        assert payload["plan_id"] is None
        assert len(payload["evidence_pack"]["transit_matrix"]) == 2
        keys = {
            (e["from_place_id"], e["to_place_id"])
            for e in payload["evidence_pack"]["transit_matrix"]
        }
        assert keys == {(a, b), (b, a)}
    finally:
        from src.supabase_client import get_supabase_client

        admin_client = get_supabase_client()
        try:
            admin_client.auth.admin.delete_user(user_id)
        except Exception:
            pass
