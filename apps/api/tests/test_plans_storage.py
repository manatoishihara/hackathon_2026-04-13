"""`apps/api/src/plans/storage.py` のテスト（Phase 1.3d Branch B）。

Supabase クライアントをモックして、3 つの薄い RPC ラッパが正しく呼び分けられることを確認する。
実 DB に触らないのでコスト ゼロ、CI 内で実行可。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.plans.storage import (
    RpcTransportError,
    call_finalize_plan,
    mark_plan_failed,
    try_lock_plan_for_generation,
)


def _make_rpc_mock(return_data):
    """`client.rpc(name, params).execute()` の戻りが `.data = return_data` になる mock。"""
    execute_mock = MagicMock()
    execute_mock.data = return_data

    rpc_builder = MagicMock()
    rpc_builder.execute.return_value = execute_mock

    client = MagicMock()
    client.rpc.return_value = rpc_builder
    return client, rpc_builder


# ==============================
# try_lock_plan_for_generation
# ==============================


@patch("src.plans.storage.get_supabase_client")
def test_try_lock_acquired(mock_factory):
    client, rpc_builder = _make_rpc_mock("acquired")
    mock_factory.return_value = client

    result = try_lock_plan_for_generation("plan-1", "owner-1")
    assert result == "acquired"
    client.rpc.assert_called_once_with(
        "acquire_plan_generation_lock",
        {"p_plan_id": "plan-1", "p_session_id": "owner-1"},
    )


@patch("src.plans.storage.get_supabase_client")
def test_try_lock_not_found(mock_factory):
    client, _ = _make_rpc_mock("not_found")
    mock_factory.return_value = client
    assert try_lock_plan_for_generation("plan-x", "owner-1") == "not_found"


@patch("src.plans.storage.get_supabase_client")
def test_try_lock_already_generating(mock_factory):
    client, _ = _make_rpc_mock("already_generating")
    mock_factory.return_value = client
    assert try_lock_plan_for_generation("plan-1", "owner-1") == "already_generating"


@patch("src.plans.storage.get_supabase_client")
def test_try_lock_already_succeeded(mock_factory):
    client, _ = _make_rpc_mock("already_succeeded")
    mock_factory.return_value = client
    assert try_lock_plan_for_generation("plan-1", "owner-1") == "already_succeeded"


@patch("src.plans.storage.get_supabase_client")
def test_try_lock_unexpected_result_raises(mock_factory):
    client, _ = _make_rpc_mock("gibberish")
    mock_factory.return_value = client
    with pytest.raises(ValueError):
        try_lock_plan_for_generation("plan-1", "owner-1")


@patch("src.plans.storage.get_supabase_client")
def test_try_lock_rpc_raises_wrapped_as_transport_error(mock_factory):
    client = MagicMock()
    client.rpc.side_effect = ConnectionError("network down")
    mock_factory.return_value = client
    with pytest.raises(RpcTransportError):
        try_lock_plan_for_generation("plan-1", "owner-1")


# ==============================
# call_finalize_plan
# ==============================


@patch("src.plans.storage.get_supabase_client")
def test_call_finalize_plan_success(mock_factory):
    client, _ = _make_rpc_mock(None)
    mock_factory.return_value = client

    items = [{"order_index": 0, "item_type": "activity"}]
    call_finalize_plan("plan-1", "owner-1", items)

    client.rpc.assert_called_once_with(
        "finalize_plan",
        {"p_plan_id": "plan-1", "p_session_id": "owner-1", "p_items": items},
    )


@patch("src.plans.storage.get_supabase_client")
def test_call_finalize_plan_transport_error_wrapped(mock_factory):
    client = MagicMock()
    client.rpc.side_effect = TimeoutError("request timed out")
    mock_factory.return_value = client

    with pytest.raises(RpcTransportError):
        call_finalize_plan("plan-1", "owner-1", [])


@patch("src.plans.storage.get_supabase_client")
def test_call_finalize_plan_api_error_propagates_as_is(mock_factory):
    """PostgREST / Postgres 側の明示的例外（owner mismatch 等）はそのまま伝播して
    呼び出し側で 500 に畳まれる（RpcTransportError には wrap しない）。
    """

    class FakeApiError(Exception):
        pass

    client = MagicMock()
    client.rpc.side_effect = FakeApiError("plan not in generating state")
    mock_factory.return_value = client

    with pytest.raises(FakeApiError):
        call_finalize_plan("plan-1", "owner-1", [])


# ==============================
# mark_plan_failed
# ==============================


@patch("src.plans.storage.get_supabase_client")
def test_mark_plan_failed_success(mock_factory):
    client, _ = _make_rpc_mock(None)
    mock_factory.return_value = client

    mark_plan_failed("plan-1", "owner-1")
    client.rpc.assert_called_once_with(
        "mark_plan_failed", {"p_plan_id": "plan-1", "p_session_id": "owner-1"}
    )


@patch("src.plans.storage.get_supabase_client")
def test_mark_plan_failed_transport_exception_swallowed(mock_factory, caplog):
    """呼び出し側は既にエラー応答を返す段階なので、通信系例外はログだけで握りつぶす。"""
    client = MagicMock()
    client.rpc.side_effect = ConnectionError("down")
    mock_factory.return_value = client

    mark_plan_failed("plan-1", "owner-1")
    assert any("mark_plan_failed" in r.message for r in caplog.records)


@patch("src.plans.storage.get_supabase_client")
def test_mark_plan_failed_httpx_timeout_swallowed(mock_factory, caplog):
    """httpx の TimeoutException も wrap 対象（supabase-py 実経路の例外）。"""
    import httpx

    client = MagicMock()
    client.rpc.side_effect = httpx.ConnectTimeout("connect timeout")
    mock_factory.return_value = client

    mark_plan_failed("plan-1", "owner-1")
    assert any("mark_plan_failed" in r.message for r in caplog.records)


@patch("src.plans.storage.get_supabase_client")
def test_mark_plan_failed_implementation_bug_propagates(mock_factory):
    """実装バグ（AttributeError 等）は握りつぶさない（デバッグ性維持）。"""
    client = MagicMock()
    client.rpc.side_effect = AttributeError("buggy mock")
    mock_factory.return_value = client

    with pytest.raises(AttributeError):
        mark_plan_failed("plan-1", "owner-1")


@patch("src.plans.storage.get_supabase_client")
def test_call_finalize_plan_httpx_timeout_wrapped(mock_factory):
    """supabase-py が httpx 経由なので httpx の例外も RpcTransportError に wrap。"""
    import httpx

    client = MagicMock()
    client.rpc.side_effect = httpx.ReadTimeout("read timeout")
    mock_factory.return_value = client

    with pytest.raises(RpcTransportError):
        call_finalize_plan("plan-1", "owner-1", [])


@patch("src.plans.storage.get_supabase_client")
def test_try_lock_httpx_transport_error_wrapped(mock_factory):
    import httpx

    client = MagicMock()
    client.rpc.side_effect = httpx.ConnectError("connect failed")
    mock_factory.return_value = client

    with pytest.raises(RpcTransportError):
        try_lock_plan_for_generation("plan-1", "owner-1")
