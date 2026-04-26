"""share_routes のユニットテスト。

DB-4: POST /api/plans/<plan_id>/share
DB-5: GET /api/plans/shared/<token>
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from src.app import create_app
from src.cache.plan_cache import _cache, _lock


# ==============================
# Fixtures
# ==============================

@pytest.fixture
def app():
    return create_app()


@pytest.fixture
def client(app):
    return app.test_client()


def _mock_auth(session_id: str) -> MagicMock:
    """require_session が通る Supabase クライアントモックを返す。"""
    user = MagicMock(id=session_id)
    user_resp = MagicMock(user=user)
    instance = MagicMock()
    instance.auth.get_user.return_value = user_resp
    return instance


# ==============================
# DB-4: POST /api/plans/<plan_id>/share
# ==============================

class TestCreateShareToken:

    def test_returns_share_token_for_succeeded_plan(self, client):
        plan_id = str(uuid4())
        session_id = str(uuid4())
        token = "abc123token"

        mock_client = _mock_auth(session_id)
        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {"id": plan_id, "status": "succeeded", "share_token": token}
        ]

        with patch("src.auth.get_supabase_client", return_value=mock_client), \
             patch("src.routes.share_routes.get_supabase_client", return_value=mock_client):
            resp = client.post(
                f"/api/plans/{plan_id}/share",
                headers={"Authorization": "Bearer dummy-jwt"},
            )

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["share_token"] == token
        assert token in data["share_url"]

    def test_generates_new_token_when_none_exists(self, client):
        plan_id = str(uuid4())
        session_id = str(uuid4())

        mock_client = _mock_auth(session_id)
        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {"id": plan_id, "status": "succeeded", "share_token": None}
        ]

        with patch("src.auth.get_supabase_client", return_value=mock_client), \
             patch("src.routes.share_routes.get_supabase_client", return_value=mock_client):
            resp = client.post(
                f"/api/plans/{plan_id}/share",
                headers={"Authorization": "Bearer dummy-jwt"},
            )

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["share_token"]
        assert len(data["share_token"]) > 0

    def test_returns_404_when_plan_not_found(self, client):
        plan_id = str(uuid4())
        session_id = str(uuid4())

        mock_client = _mock_auth(session_id)
        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = []

        with patch("src.auth.get_supabase_client", return_value=mock_client), \
             patch("src.routes.share_routes.get_supabase_client", return_value=mock_client):
            resp = client.post(
                f"/api/plans/{plan_id}/share",
                headers={"Authorization": "Bearer dummy-jwt"},
            )

        assert resp.status_code == 404

    def test_returns_409_when_plan_not_succeeded(self, client):
        plan_id = str(uuid4())
        session_id = str(uuid4())

        for status in ["draft", "generating", "failed"]:
            mock_client = _mock_auth(session_id)
            mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
                {"id": plan_id, "status": status, "share_token": None}
            ]

            with patch("src.auth.get_supabase_client", return_value=mock_client), \
                 patch("src.routes.share_routes.get_supabase_client", return_value=mock_client):
                resp = client.post(
                    f"/api/plans/{plan_id}/share",
                    headers={"Authorization": "Bearer dummy-jwt"},
                )

            assert resp.status_code == 409, f"expected 409 for status={status}"

    def test_share_url_uses_site_base_url_env(self, client, monkeypatch):
        plan_id = str(uuid4())
        session_id = str(uuid4())
        token = "tok123"
        monkeypatch.setenv("SITE_BASE_URL", "https://example.com")

        mock_client = _mock_auth(session_id)
        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {"id": plan_id, "status": "succeeded", "share_token": token}
        ]

        with patch("src.auth.get_supabase_client", return_value=mock_client), \
             patch("src.routes.share_routes.get_supabase_client", return_value=mock_client):
            resp = client.post(
                f"/api/plans/{plan_id}/share",
                headers={"Authorization": "Bearer dummy-jwt"},
            )

        assert resp.status_code == 200
        assert resp.get_json()["share_url"].startswith("https://example.com")


# ==============================
# DB-5: GET /api/plans/shared/<token>
# ==============================

_MOCK_RPC_PAYLOAD = {
    "plan": {
        "id": str(uuid4()),
        "title": "箱根 1 泊",
        "region": "箱根",
        "start_date": "2026-06-01",
        "end_date": "2026-06-02",
        "departure_point": "新宿",
        "budget_per_person_jpy": 50000,
        "budget_breakdown": {"lodging": 40, "meal": 30, "activity": 20, "transit": 10},
        "start_mode": "auto",
        "mode_payload": None,
        "status": "succeeded",
        "created_at": "2026-06-01T00:00:00+00:00",
        "updated_at": "2026-06-01T00:00:00+00:00",
    },
    "participants": [
        {
            "id": str(uuid4()),
            "display_name": "太郎",
            "avatar_color": "#042C53",
            "wishes_text": "温泉",
            "tags": ["温泉"],
            "order_index": 0,
        }
    ],
    "plan_items": [],
}


class TestGetSharedPlan:

    def setup_method(self):
        # テスト間でキャッシュをクリア
        with _lock:
            _cache.clear()

    def test_returns_plan_for_valid_token(self, client):
        token = "validtoken123"

        mock_client = MagicMock()
        mock_client.rpc.return_value.execute.return_value.data = _MOCK_RPC_PAYLOAD

        with patch("src.routes.share_routes.get_supabase_client", return_value=mock_client):
            resp = client.get(f"/api/plans/shared/{token}")

        assert resp.status_code == 200
        data = resp.get_json()
        assert "plan" in data
        assert "participants" in data
        assert "plan_items" in data

    def test_returns_404_for_unknown_token(self, client):
        mock_client = MagicMock()
        mock_client.rpc.return_value.execute.return_value.data = None

        with patch("src.routes.share_routes.get_supabase_client", return_value=mock_client):
            resp = client.get("/api/plans/shared/unknowntoken")

        assert resp.status_code == 404

    def test_cache_hit_skips_rpc(self, client):
        token = "cachedtoken"

        # 1 回目: RPC 呼び出し
        mock_client = MagicMock()
        mock_client.rpc.return_value.execute.return_value.data = _MOCK_RPC_PAYLOAD

        with patch("src.routes.share_routes.get_supabase_client", return_value=mock_client):
            resp1 = client.get(f"/api/plans/shared/{token}")
        assert resp1.status_code == 200
        assert resp1.headers.get("X-Cache") == "MISS"

        # 2 回目: キャッシュヒット（RPC 呼ばれない）
        with patch("src.routes.share_routes.get_supabase_client", return_value=mock_client):
            resp2 = client.get(f"/api/plans/shared/{token}")
        assert resp2.status_code == 200
        assert resp2.headers.get("X-Cache") == "HIT"
        mock_client.rpc.assert_called_once()  # 1 回のみ

    def test_cache_control_header_present(self, client):
        mock_client = MagicMock()
        mock_client.rpc.return_value.execute.return_value.data = _MOCK_RPC_PAYLOAD

        with patch("src.routes.share_routes.get_supabase_client", return_value=mock_client):
            resp = client.get("/api/plans/shared/sometoken")

        assert "max-age=60" in resp.headers.get("Cache-Control", "")

    def test_session_id_not_leaked_in_response(self, client):
        mock_client = MagicMock()
        payload = dict(_MOCK_RPC_PAYLOAD)
        payload["plan"] = dict(_MOCK_RPC_PAYLOAD["plan"])
        mock_client.rpc.return_value.execute.return_value.data = payload

        with patch("src.routes.share_routes.get_supabase_client", return_value=mock_client):
            resp = client.get("/api/plans/shared/leaktoken")

        assert resp.status_code == 200
        data = resp.get_json()
        assert "session_id" not in data.get("plan", {})
        assert "share_token" not in data.get("plan", {})

    def test_returns_503_on_rpc_exception(self, client):
        mock_client = MagicMock()
        mock_client.rpc.return_value.execute.side_effect = Exception("DB down")

        with patch("src.routes.share_routes.get_supabase_client", return_value=mock_client):
            resp = client.get("/api/plans/shared/errortoken")

        assert resp.status_code == 503
