"""外部 API ヘルスチェックのテスト。

- デフォルトで実行されるのはモックベースのユニットテスト
- `pytest -m integration` で実行される integration テストは、.env に実キーが
  入っているときだけ走る（placeholder のときは skip）
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from src.external.health import (
    ALL_CHECKS,
    HealthResult,
    check_google_geocoding,
    check_google_places,
    check_google_routes,
    check_openai,
    run_all,
)

# ==============================
# Unit tests（モック）
# ==============================


def test_missing_env_returns_ok_false(monkeypatch):
    for var in ("GOOGLE_MAPS_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    for name, fn in ALL_CHECKS.items():
        result = fn()
        assert result.ok is False, f"{name}: expected ok=False with no key"
        assert result.error is not None and "unset" in result.error


@patch("src.external.health.requests.post")
def test_google_places_success(mock_post):
    mock_post.return_value = MagicMock(ok=True, status_code=200)
    r = check_google_places(api_key="fake-key")
    assert r.ok is True
    assert r.status_code == 200
    # 送信 URL とヘッダの形を検証
    args, kwargs = mock_post.call_args
    assert args[0] == "https://places.googleapis.com/v1/places:searchText"
    assert kwargs["headers"]["X-Goog-Api-Key"] == "fake-key"
    assert "X-Goog-FieldMask" in kwargs["headers"]


@patch("src.external.health.requests.post")
def test_google_places_failure(mock_post):
    mock_post.return_value = MagicMock(ok=False, status_code=403, text="forbidden")
    r = check_google_places(api_key="fake-key")
    assert r.ok is False
    assert r.status_code == 403
    assert r.error is not None


@patch("src.external.health.requests.post")
def test_google_routes_success(mock_post):
    mock_post.return_value = MagicMock(ok=True, status_code=200)
    r = check_google_routes(api_key="fake-key")
    assert r.ok is True
    args, kwargs = mock_post.call_args
    assert args[0] == "https://routes.googleapis.com/directions/v2:computeRoutes"
    assert kwargs["json"]["travelMode"] == "TRANSIT"


@patch("src.external.health.requests.get")
def test_google_geocoding_success(mock_get):
    mock_response = MagicMock(ok=True, status_code=200)
    mock_response.json.return_value = {"status": "OK", "results": []}
    mock_get.return_value = mock_response
    r = check_google_geocoding(api_key="fake-key")
    assert r.ok is True


@patch("src.external.health.requests.get")
def test_google_geocoding_api_status_error(mock_get):
    """HTTP 200 でも body の status が ERROR なら ok=False を返す。"""
    mock_response = MagicMock(ok=True, status_code=200)
    mock_response.json.return_value = {"status": "REQUEST_DENIED"}
    mock_get.return_value = mock_response
    r = check_google_geocoding(api_key="fake-key")
    assert r.ok is False
    assert r.error is not None and "REQUEST_DENIED" in r.error


@patch("src.external.health.requests.post")
def test_network_exception_is_captured(mock_post):
    """ネットワーク例外は HealthResult に畳み込み、raise しない。"""
    import requests as _req

    mock_post.side_effect = _req.ConnectionError("boom")
    r = check_google_places(api_key="fake-key")
    assert r.ok is False
    assert r.error is not None and "ConnectionError" in r.error


@patch("src.external.health.OpenAI")
def test_openai_success(mock_openai_cls):
    instance = MagicMock()
    instance.models.list.return_value = iter([MagicMock(id="gpt-4o")])
    mock_openai_cls.return_value = instance
    r = check_openai(api_key="sk-fake")
    assert r.ok is True


@patch("src.external.health.OpenAI")
def test_openai_failure(mock_openai_cls):
    mock_openai_cls.side_effect = Exception("invalid api key")
    r = check_openai(api_key="sk-fake")
    assert r.ok is False
    assert r.error is not None and "invalid api key" in r.error


def test_run_all_returns_all_services(monkeypatch):
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    results = run_all()
    assert set(results.keys()) == {"google_places", "google_routes", "google_geocoding", "openai"}
    assert all(isinstance(r, HealthResult) for r in results.values())


# ==============================
# Integration tests（ライブ API）
# ==============================


def _real_key(var: str, min_len: int, prefix: str | None = None) -> bool:
    val = os.environ.get(var, "")
    if len(val) < min_len:
        return False
    if prefix and not val.startswith(prefix):
        return False
    return True


@pytest.mark.integration
@pytest.mark.skipif(not _real_key("GOOGLE_MAPS_API_KEY", 20, "AIza"), reason="GOOGLE_MAPS_API_KEY not set")
def test_integration_google_places():
    r = check_google_places()
    assert r.ok, f"places check failed: status={r.status_code}, error={r.error}"


@pytest.mark.integration
@pytest.mark.skipif(not _real_key("GOOGLE_MAPS_API_KEY", 20, "AIza"), reason="GOOGLE_MAPS_API_KEY not set")
def test_integration_google_routes():
    r = check_google_routes()
    assert r.ok, f"routes check failed: status={r.status_code}, error={r.error}"


@pytest.mark.integration
@pytest.mark.skipif(not _real_key("GOOGLE_MAPS_API_KEY", 20, "AIza"), reason="GOOGLE_MAPS_API_KEY not set")
def test_integration_google_geocoding():
    r = check_google_geocoding()
    assert r.ok, f"geocoding check failed: status={r.status_code}, error={r.error}"


@pytest.mark.integration
@pytest.mark.skipif(not _real_key("OPENAI_API_KEY", 20, "sk-"), reason="OPENAI_API_KEY not set")
def test_integration_openai():
    r = check_openai()
    assert r.ok, f"openai check failed: error={r.error}"
