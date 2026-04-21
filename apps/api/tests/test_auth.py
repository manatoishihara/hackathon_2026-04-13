"""require_session デコレータのユニットテスト（mocked Supabase）。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from flask import Flask, g, jsonify

from src.auth import require_session


@pytest.fixture
def app():
    flask_app = Flask(__name__)

    @flask_app.get("/protected")
    @require_session
    def protected():
        return jsonify({"owner_session_id": g.owner_session_id}), 200

    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


def test_missing_header_returns_401(client):
    res = client.get("/protected")
    assert res.status_code == 401
    assert "Authorization" in res.get_json()["error"]


def test_non_bearer_header_returns_401(client):
    res = client.get("/protected", headers={"Authorization": "Basic foo"})
    assert res.status_code == 401


def test_empty_bearer_token_returns_401(client):
    res = client.get("/protected", headers={"Authorization": "Bearer "})
    assert res.status_code == 401


@patch("src.auth.get_supabase_client")
def test_invalid_jwt_returns_401(mock_client_factory, client):
    instance = MagicMock()
    instance.auth.get_user.side_effect = Exception("jwt expired")
    mock_client_factory.return_value = instance

    res = client.get("/protected", headers={"Authorization": "Bearer bad-jwt"})
    assert res.status_code == 401
    assert "invalid token" in res.get_json()["error"]


@patch("src.auth.get_supabase_client")
def test_valid_jwt_sets_owner_session_id(mock_client_factory, client):
    user = MagicMock(id="00000000-1111-2222-3333-444455556666")
    user_resp = MagicMock(user=user)
    instance = MagicMock()
    instance.auth.get_user.return_value = user_resp
    mock_client_factory.return_value = instance

    res = client.get("/protected", headers={"Authorization": "Bearer good-jwt"})
    assert res.status_code == 200
    assert res.get_json()["owner_session_id"] == "00000000-1111-2222-3333-444455556666"


@patch("src.auth.get_supabase_client")
def test_user_response_without_user_returns_401(mock_client_factory, client):
    """auth.get_user が user=None を返す場合も 401。"""
    instance = MagicMock()
    instance.auth.get_user.return_value = MagicMock(user=None)
    mock_client_factory.return_value = instance

    res = client.get("/protected", headers={"Authorization": "Bearer no-user"})
    assert res.status_code == 401
