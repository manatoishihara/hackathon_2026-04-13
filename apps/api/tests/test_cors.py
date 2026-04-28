"""CORS 設定の振る舞いを検証する（Phase 1.10 デプロイ準備）。

設計:
    Vercel (フロント) → Render (バック) は cross-origin。
    `Authorization: Bearer <JWT>` を付ける `fetch` 呼び出しはプリフライト OPTIONS
    が走るため、Flask 側で:
      - 許可された Origin に対し `Access-Control-Allow-Origin: <origin>` を返す
      - `Authorization` / `Content-Type` を `Allow-Headers` に含める
      - `POST` / `GET` / `OPTIONS` を `Allow-Methods` に含める

Origins は `CORS_ALLOWED_ORIGINS` 環境変数（カンマ区切り）から決定。未設定時は
ローカル開発用の `http://localhost:3000` のみ許可する。
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture
def fresh_app(monkeypatch):
    """env を弄った状態でアプリを生成する。create_app の都度生成で env が反映される前提。"""
    def _build(allowed: str | None = None):
        if allowed is None:
            monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)
        else:
            monkeypatch.setenv("CORS_ALLOWED_ORIGINS", allowed)
        from src.app import create_app
        return create_app()

    return _build


def test_cors_default_allows_localhost_3000(fresh_app):
    """env 未設定時のデフォルトで http://localhost:3000 が allowed。"""
    app = fresh_app()
    client = app.test_client()
    res = client.get("/healthz", headers={"Origin": "http://localhost:3000"})
    assert res.status_code == 200
    # Flask-CORS は許可された origin をエコーバックする（"*" ではなく具体値）
    assert res.headers.get("Access-Control-Allow-Origin") == "http://localhost:3000"


def test_cors_default_blocks_unknown_origin(fresh_app):
    """env 未設定時、見知らぬ origin は ACAO ヘッダなし（ブラウザが弾く）。"""
    app = fresh_app()
    client = app.test_client()
    res = client.get("/healthz", headers={"Origin": "https://evil.example.com"})
    assert res.status_code == 200
    assert res.headers.get("Access-Control-Allow-Origin") is None


def test_cors_env_overrides_default(fresh_app):
    """CORS_ALLOWED_ORIGINS をセットすればその origin が通る。"""
    app = fresh_app("https://routeful.vercel.app")
    client = app.test_client()
    res = client.get("/healthz", headers={"Origin": "https://routeful.vercel.app"})
    assert res.status_code == 200
    assert res.headers.get("Access-Control-Allow-Origin") == "https://routeful.vercel.app"


def test_cors_env_supports_multiple_comma_separated(fresh_app):
    """複数 origin をカンマ区切りで指定できる（Vercel preview + 本番など）。"""
    app = fresh_app(
        "https://routeful.vercel.app,https://preview-abc.vercel.app,http://localhost:3000"
    )
    client = app.test_client()
    for origin in (
        "https://routeful.vercel.app",
        "https://preview-abc.vercel.app",
        "http://localhost:3000",
    ):
        res = client.get("/healthz", headers={"Origin": origin})
        assert res.headers.get("Access-Control-Allow-Origin") == origin, origin


def test_cors_preflight_options_returns_2xx(fresh_app):
    """プリフライト OPTIONS が 200 or 204 で返る（Allow-Headers / Methods 込み）。"""
    app = fresh_app()
    client = app.test_client()
    res = client.options(
        "/api/plans/generate",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization,Content-Type",
        },
    )
    assert res.status_code in (200, 204)
    assert res.headers.get("Access-Control-Allow-Origin") == "http://localhost:3000"
    allow_headers = (res.headers.get("Access-Control-Allow-Headers") or "").lower()
    assert "authorization" in allow_headers
    assert "content-type" in allow_headers
    allow_methods = (res.headers.get("Access-Control-Allow-Methods") or "").upper()
    assert "POST" in allow_methods


def test_cors_actual_post_response_has_acao(fresh_app):
    """実 POST のレスポンスにも ACAO が乗る（プリフライトだけでなく実本体）。

    auth 必須 endpoint なので 401 が返るが、CORS ヘッダは付くべき。
    """
    app = fresh_app()
    client = app.test_client()
    res = client.post(
        "/api/plans/generate",
        json={"plan_id": "x", "evidence_pack_id": "y", "transit_matrix": []},
        headers={"Origin": "http://localhost:3000"},
    )
    # auth ヘッダなしなので 401、ただし CORS ヘッダは付く
    assert res.status_code == 401
    assert res.headers.get("Access-Control-Allow-Origin") == "http://localhost:3000"
