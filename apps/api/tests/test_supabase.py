import pytest

from src.supabase_client import get_supabase_client


def test_raises_when_env_vars_missing(monkeypatch):
    monkeypatch.delenv("NEXT_PUBLIC_SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)

    with pytest.raises(RuntimeError, match="Supabase env vars が未設定"):
        get_supabase_client()


def test_raises_when_only_url_set(monkeypatch):
    monkeypatch.setenv("NEXT_PUBLIC_SUPABASE_URL", "https://fake.supabase.co")
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)

    with pytest.raises(RuntimeError, match="Supabase env vars が未設定"):
        get_supabase_client()


def test_returns_client_when_env_vars_set(monkeypatch):
    monkeypatch.setenv("NEXT_PUBLIC_SUPABASE_URL", "https://fake.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "fake-service-role-key")

    client = get_supabase_client()
    assert client is not None
    # supabase-py v2 のクライアント形状を最小限チェック
    assert hasattr(client, "auth")
    assert hasattr(client, "table")
