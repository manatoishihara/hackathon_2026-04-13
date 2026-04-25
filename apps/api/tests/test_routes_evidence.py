"""`/api/evidence/places` エンドポイントのユニットテスト（mocked 認証 + builder + cache）と
integration テスト（live Supabase + live Places）。
"""

from __future__ import annotations

import os
from datetime import date
from unittest.mock import MagicMock, patch

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


def _valid_request_body() -> dict:
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


def _mock_supabase_user(session_id: str = "session-abc"):
    """`get_supabase_client().auth.get_user(jwt)` の戻り値として user を返すモック factory。"""
    user = MagicMock(id=session_id)
    user_resp = MagicMock(user=user)
    instance = MagicMock()
    instance.auth.get_user.return_value = user_resp
    return instance


def _sample_pack_with_places() -> EvidencePack:
    return EvidencePack(
        query_context=QueryContext(
            region="箱根",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 2),
            departure_point="新宿駅",
            start_mode="auto",
            mode_payload=None,
            participants=[QueryContextParticipant(name="太郎", wishes="w", tags=[])],
        ),
        places=[
            PlacePoint(
                place_id="p1",
                name="箱根神社",
                category=["tourist_attraction"],
                lat=35.204,
                lng=139.025,
                address="神奈川県箱根町",
                opening_hours=[],
                price_level=None,
                rating=None,
                user_ratings_total=None,
            ),
            PlacePoint(
                place_id="p2",
                name="箱根湯本駅",
                category=["transit_station"],
                lat=35.232,
                lng=139.108,
                address="神奈川県箱根町",
                opening_hours=[],
                price_level=None,
                rating=None,
                user_ratings_total=None,
            ),
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


# ==============================
# 認証系
# ==============================


def test_missing_auth_returns_401(client):
    res = client.post("/api/evidence/places", json=_valid_request_body())
    assert res.status_code == 401


@patch("src.auth.get_supabase_client")
def test_invalid_jwt_returns_401(mock_factory, client):
    instance = MagicMock()
    instance.auth.get_user.side_effect = Exception("expired")
    mock_factory.return_value = instance

    res = client.post(
        "/api/evidence/places",
        json=_valid_request_body(),
        headers={"Authorization": "Bearer bad"},
    )
    assert res.status_code == 401


# ==============================
# 入力検証
# ==============================


@patch("src.auth.get_supabase_client")
def test_non_json_body_returns_400(mock_auth_factory, client):
    mock_auth_factory.return_value = _mock_supabase_user()
    res = client.post(
        "/api/evidence/places",
        data="not json",
        content_type="text/plain",
        headers={"Authorization": "Bearer ok"},
    )
    assert res.status_code == 400
    assert "JSON object" in res.get_json()["error"]


@patch("src.auth.get_supabase_client")
def test_non_object_json_returns_400(mock_auth_factory, client):
    mock_auth_factory.return_value = _mock_supabase_user()
    res = client.post(
        "/api/evidence/places",
        json=["not", "a", "dict"],
        headers={"Authorization": "Bearer ok"},
    )
    assert res.status_code == 400


@patch("src.auth.get_supabase_client")
def test_validation_error_returns_400(mock_auth_factory, client):
    mock_auth_factory.return_value = _mock_supabase_user()
    body = _valid_request_body()
    body["budget_breakdown"]["lodging"] = -1  # 制約違反
    res = client.post(
        "/api/evidence/places",
        json=body,
        headers={"Authorization": "Bearer ok"},
    )
    assert res.status_code == 400
    assert "validation failed" in res.get_json()["error"]


# ==============================
# 成功系（builder + cache をモック）
# ==============================


@patch("src.routes.evidence_routes.store_pack")
@patch("src.routes.evidence_routes.build_evidence_pack")
@patch("src.auth.get_supabase_client")
def test_happy_path_returns_evidence_pack_id_and_places_subset(
    mock_auth_factory, mock_build, mock_store, client
):
    mock_auth_factory.return_value = _mock_supabase_user(session_id="owner-xyz")
    mock_build.return_value = _sample_pack_with_places()
    mock_store.return_value = "pack-id-42"

    res = client.post(
        "/api/evidence/places",
        json=_valid_request_body(),
        headers={"Authorization": "Bearer ok"},
    )
    assert res.status_code == 200
    body = res.get_json()
    assert body["evidence_pack_id"] == "pack-id-42"
    assert len(body["places"]) == 2
    assert body["places"][0] == {
        "place_id": "p1",
        "name": "箱根神社",
        "lat": 35.204,
        "lng": 139.025,
    }
    # store_pack は owner_session_id を伝えた形で呼ばれている
    _, kwargs = mock_store.call_args
    assert kwargs["owner_session_id"] == "owner-xyz"


@patch("src.routes.evidence_routes.store_pack")
@patch("src.routes.evidence_routes.build_evidence_pack")
@patch("src.auth.get_supabase_client")
def test_cache_failure_returns_500(mock_auth_factory, mock_build, mock_store, client):
    from src.evidence.cache import CacheError

    mock_auth_factory.return_value = _mock_supabase_user()
    mock_build.return_value = _sample_pack_with_places()
    mock_store.side_effect = CacheError("supabase down")

    res = client.post(
        "/api/evidence/places",
        json=_valid_request_body(),
        headers={"Authorization": "Bearer ok"},
    )
    assert res.status_code == 500
    assert "cache" in res.get_json()["error"].lower()


# ==============================
# Phase 2.1: 出発モード切替の異常系（Codex Major 4 対応）
# ==============================


@patch("src.auth.get_supabase_client")
def test_anchor_mode_with_empty_ids_returns_400(mock_auth_factory, client):
    """anchor_place_ids 空配列は 400（schema validate 段階）。"""
    mock_auth_factory.return_value = _mock_supabase_user()
    body = _valid_request_body()
    body["start_mode"] = "anchor"
    body["mode_payload"] = {"anchor_place_ids": []}
    res = client.post(
        "/api/evidence/places", json=body, headers={"Authorization": "Bearer ok"}
    )
    assert res.status_code == 400
    assert "validation failed" in res.get_json()["error"]


@patch("src.auth.get_supabase_client")
def test_anchor_mode_with_too_many_ids_returns_400(mock_auth_factory, client):
    """anchor_place_ids 4 件以上は 400（max_length=3）。"""
    mock_auth_factory.return_value = _mock_supabase_user()
    body = _valid_request_body()
    body["start_mode"] = "anchor"
    body["mode_payload"] = {"anchor_place_ids": ["a", "b", "c", "d"]}
    res = client.post(
        "/api/evidence/places", json=body, headers={"Authorization": "Bearer ok"}
    )
    assert res.status_code == 400


@patch("src.auth.get_supabase_client")
def test_theme_mode_with_unknown_theme_returns_400(mock_auth_factory, client):
    """theme が ThemeKey enum 6 値以外なら 400。"""
    mock_auth_factory.return_value = _mock_supabase_user()
    body = _valid_request_body()
    body["start_mode"] = "theme"
    body["mode_payload"] = {"theme": "not_a_real_theme"}
    res = client.post(
        "/api/evidence/places", json=body, headers={"Authorization": "Bearer ok"}
    )
    assert res.status_code == 400


@patch("src.auth.get_supabase_client")
def test_theme_mode_with_null_payload_returns_400(mock_auth_factory, client):
    """theme モードで mode_payload=null は 400。"""
    mock_auth_factory.return_value = _mock_supabase_user()
    body = _valid_request_body()
    body["start_mode"] = "theme"
    body["mode_payload"] = None
    res = client.post(
        "/api/evidence/places", json=body, headers={"Authorization": "Bearer ok"}
    )
    assert res.status_code == 400


@patch("src.auth.get_supabase_client")
def test_auto_mode_with_non_null_payload_returns_400(mock_auth_factory, client):
    """auto モードで mode_payload が non-null は 400（form 整合の早期発見）。"""
    mock_auth_factory.return_value = _mock_supabase_user()
    body = _valid_request_body()
    body["start_mode"] = "auto"
    body["mode_payload"] = {"theme": "onsen"}
    res = client.post(
        "/api/evidence/places", json=body, headers={"Authorization": "Bearer ok"}
    )
    assert res.status_code == 400


@patch("src.routes.evidence_routes.build_evidence_pack")
@patch("src.auth.get_supabase_client")
def test_anchor_not_found_returns_400_with_missing_ids(
    mock_auth_factory, mock_build, client
):
    """anchor が 404 (Place Details に存在しない) → user 入力ミス相当で 400 + missing IDs。"""
    from src.evidence.builder import AnchorFetchError

    mock_auth_factory.return_value = _mock_supabase_user()
    mock_build.side_effect = AnchorFetchError(missing_ids=["bad_anchor_1", "bad_anchor_2"])

    body = _valid_request_body()
    body["start_mode"] = "anchor"
    body["mode_payload"] = {"anchor_place_ids": ["bad_anchor_1", "bad_anchor_2"]}
    res = client.post(
        "/api/evidence/places", json=body, headers={"Authorization": "Bearer ok"}
    )
    assert res.status_code == 400
    body_json = res.get_json()
    assert "anchor" in body_json["error"].lower()
    assert set(body_json["missing_anchor_ids"]) == {"bad_anchor_1", "bad_anchor_2"}


@patch("src.routes.evidence_routes.build_evidence_pack")
@patch("src.auth.get_supabase_client")
def test_anchor_upstream_error_returns_502(mock_auth_factory, mock_build, client):
    """Codex 再レビュー Major 1: Places API インフラ障害は 5xx (502) で区別。
    400 に潰すと運用監視（5xx 率）が誤って薄まる。"""
    from src.evidence.builder import AnchorFetchUpstreamError
    from src.evidence.places import PlacesError

    mock_auth_factory.return_value = _mock_supabase_user()
    mock_build.side_effect = AnchorFetchUpstreamError(
        place_id="ChIJ_anchor", cause=PlacesError("503 service unavailable")
    )

    body = _valid_request_body()
    body["start_mode"] = "anchor"
    body["mode_payload"] = {"anchor_place_ids": ["ChIJ_anchor"]}
    res = client.post(
        "/api/evidence/places", json=body, headers={"Authorization": "Bearer ok"}
    )
    assert res.status_code == 502
    assert "upstream" in res.get_json()["error"].lower()


# ==============================
# エラーハンドラ回帰（404 / 405 が 500 に潰されないこと）
# ==============================


def test_unknown_path_returns_404(client):
    """Flask 標準の 404 が errorhandler(Exception) に潰されず、404 のまま返る。"""
    res = client.get("/no-such-path")
    assert res.status_code == 404
    assert res.get_json() is not None  # JSON で返る


def test_method_not_allowed_returns_405(client):
    """/api/evidence/places は POST のみ。GET は 405。"""
    res = client.get("/api/evidence/places")
    assert res.status_code == 405


# ==============================
# Integration（live Supabase + live Places, anon サインイン経由）
# ==============================


def _has_full_stack() -> bool:
    return all(
        os.environ.get(k) for k in ("GOOGLE_MAPS_API_KEY", "NEXT_PUBLIC_SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY")
    ) and len(os.environ.get("GOOGLE_MAPS_API_KEY", "")) > 20


@pytest.mark.integration
@pytest.mark.skipif(not _has_full_stack(), reason="full stack env keys not set")
def test_integration_end_to_end_places_endpoint(client):
    """匿名サインイン → /api/evidence/places → Supabase 保存までを検証。

    コスト: Places 検索 5 回分（$0.1 未満）。

    ユーザは本テスト実行前に evidence_pack_sessions テーブルを Supabase で作成済みである必要がある。
    """
    from supabase import create_client

    # 1. 匿名サインインして JWT を取得（フロント相当）
    anon_client = create_client(
        os.environ["NEXT_PUBLIC_SUPABASE_URL"],
        os.environ["NEXT_PUBLIC_SUPABASE_ANON_KEY"],
    )
    sign_in = anon_client.auth.sign_in_anonymously()
    jwt_token = sign_in.session.access_token
    user_id = sign_in.user.id

    try:
        # 2. /api/evidence/places にリクエスト
        res = client.post(
            "/api/evidence/places",
            json=_valid_request_body(),
            headers={"Authorization": f"Bearer {jwt_token}"},
        )
        assert res.status_code == 200, f"got {res.status_code}: {res.get_data(as_text=True)}"
        body = res.get_json()
        assert body["evidence_pack_id"]
        assert isinstance(body["places"], list)
        # 箱根で 1 件以上は取れるはず
        assert len(body["places"]) > 0

        # 3. cache から load して owner 照合
        from src.evidence.cache import load_pack

        loaded = load_pack(body["evidence_pack_id"], owner_session_id=user_id)
        assert loaded is not None
        assert loaded.query_context.region == "箱根"
    finally:
        # 4. Cleanup: 作成した匿名ユーザを削除
        from src.supabase_client import get_supabase_client

        admin_client = get_supabase_client()
        try:
            admin_client.auth.admin.delete_user(user_id)
        except Exception:
            pass
