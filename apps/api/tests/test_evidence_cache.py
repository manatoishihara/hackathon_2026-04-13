"""evidence/cache.py の store_pack / load_pack のユニットテスト（mocked Supabase）と
integration テスト。"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.evidence.cache import CacheError, load_pack, store_pack
from src.evidence.pack import (
    BudgetBreakdownJPY,
    BudgetConstraints,
    EvidencePack,
    QueryContext,
    QueryContextParticipant,
    TemporalConstraints,
)
from src.schemas import BudgetBreakdown


def _sample_pack() -> EvidencePack:
    return EvidencePack(
        query_context=QueryContext(
            region="箱根",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 2),
            departure_point="新宿駅",
            start_mode="auto",
            mode_payload=None,
            participants=[
                QueryContextParticipant(name="太郎", wishes="温泉", tags=["温泉"])
            ],
        ),
        places=[],
        transit_matrix=[],
        budget_constraints=BudgetConstraints(
            total_jpy_per_person=30000,
            breakdown_percent=BudgetBreakdown(lodging=40, meal=30, activity=20, transit=10),
            breakdown_jpy=BudgetBreakdownJPY(lodging=12000, meal=9000, activity=6000, transit=3000),
        ),
        temporal_constraints=TemporalConstraints(
            start_datetime=datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc),
            end_datetime=datetime(2026, 6, 2, 20, 0, tzinfo=timezone.utc),
            total_days=2,
        ),
    )


def _chain_mock() -> tuple[MagicMock, MagicMock]:
    """chainable な Supabase クライアントのモックを作る。

    戻り値: (mock_client, mock_table) — table().select() 等は全て自分自身を返し、
    execute() だけ別のモックとして差し替えできる構造。
    """
    mock_client = MagicMock()
    mock_table = MagicMock()
    mock_client.table.return_value = mock_table
    # select/insert/delete/eq/lt/limit はチェイン可
    for method in ("select", "insert", "delete", "eq", "lt", "limit"):
        getattr(mock_table, method).return_value = mock_table
    return mock_client, mock_table


# ==============================
# store_pack
# ==============================


@patch("src.evidence.cache.get_supabase_client")
def test_store_pack_inserts_and_returns_id(mock_factory):
    client, table = _chain_mock()
    mock_factory.return_value = client

    # cleanup は成功、insert で id を返す
    table.execute.side_effect = [
        MagicMock(data=[]),  # cleanup (delete)
        MagicMock(data=[{"id": "new-id-123"}]),  # insert
    ]

    pack_id = store_pack(_sample_pack(), owner_session_id="owner-1")
    assert pack_id == "new-id-123"


@patch("src.evidence.cache.get_supabase_client")
def test_store_pack_cleanup_failure_is_swallowed(mock_factory):
    client, table = _chain_mock()
    mock_factory.return_value = client

    table.execute.side_effect = [
        Exception("cleanup boom"),  # cleanup raises
        MagicMock(data=[{"id": "still-ok"}]),  # insert succeeds
    ]

    pack_id = store_pack(_sample_pack(), owner_session_id="owner-1")
    assert pack_id == "still-ok"


@patch("src.evidence.cache.sleep", lambda _: None)  # retry の待ち時間を 0 に
@patch("src.evidence.cache.get_supabase_client")
def test_store_pack_retries_on_insert_failure(mock_factory):
    client, table = _chain_mock()
    mock_factory.return_value = client

    table.execute.side_effect = [
        MagicMock(data=[]),  # cleanup
        Exception("network blip 1"),  # insert attempt 1
        Exception("network blip 2"),  # insert attempt 2
        MagicMock(data=[{"id": "recovered"}]),  # insert attempt 3 (success)
    ]

    pack_id = store_pack(_sample_pack(), owner_session_id="owner-1")
    assert pack_id == "recovered"


@patch("src.evidence.cache.sleep", lambda _: None)
@patch("src.evidence.cache.get_supabase_client")
def test_store_pack_raises_after_max_retries(mock_factory):
    client, table = _chain_mock()
    mock_factory.return_value = client

    table.execute.side_effect = [
        MagicMock(data=[]),  # cleanup
        Exception("persistent failure"),  # attempt 1
        Exception("persistent failure"),  # attempt 2
        Exception("persistent failure"),  # attempt 3
    ]

    with pytest.raises(CacheError, match="failed after 3 attempts"):
        store_pack(_sample_pack(), owner_session_id="owner-1")


# ==============================
# load_pack
# ==============================


@patch("src.evidence.cache.get_supabase_client")
def test_load_pack_returns_pack_when_owner_matches_and_not_expired(mock_factory):
    client, table = _chain_mock()
    mock_factory.return_value = client

    future = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    pack = _sample_pack()
    table.execute.return_value = MagicMock(
        data=[
            {
                "owner_session_id": "owner-1",
                "pack": pack.model_dump(mode="json"),
                "expires_at": future,
            }
        ]
    )

    result = load_pack("some-id", owner_session_id="owner-1")
    assert result is not None
    assert result.query_context.region == "箱根"


@patch("src.evidence.cache.get_supabase_client")
def test_load_pack_returns_none_when_not_found(mock_factory):
    client, table = _chain_mock()
    mock_factory.return_value = client

    table.execute.return_value = MagicMock(data=[])
    assert load_pack("missing-id", owner_session_id="owner-1") is None


@patch("src.evidence.cache.get_supabase_client")
def test_load_pack_returns_none_when_owner_mismatches(mock_factory):
    client, table = _chain_mock()
    mock_factory.return_value = client

    future = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    pack = _sample_pack()
    table.execute.return_value = MagicMock(
        data=[
            {
                "owner_session_id": "other-owner",
                "pack": pack.model_dump(mode="json"),
                "expires_at": future,
            }
        ]
    )

    assert load_pack("some-id", owner_session_id="owner-1") is None


@patch("src.evidence.cache.get_supabase_client")
def test_load_pack_returns_none_when_expired(mock_factory):
    client, table = _chain_mock()
    mock_factory.return_value = client

    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    pack = _sample_pack()
    table.execute.return_value = MagicMock(
        data=[
            {
                "owner_session_id": "owner-1",
                "pack": pack.model_dump(mode="json"),
                "expires_at": past,
            }
        ]
    )

    assert load_pack("some-id", owner_session_id="owner-1") is None


@patch("src.evidence.cache.get_supabase_client")
def test_load_pack_returns_none_when_pack_data_not_dict(mock_factory):
    client, table = _chain_mock()
    mock_factory.return_value = client

    future = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    table.execute.return_value = MagicMock(
        data=[
            {
                "owner_session_id": "owner-1",
                "pack": "not a dict",  # 破損データ
                "expires_at": future,
            }
        ]
    )

    assert load_pack("some-id", owner_session_id="owner-1") is None


@patch("src.evidence.cache.get_supabase_client")
def test_load_pack_returns_none_when_pack_dict_fails_validation(mock_factory):
    """pack が dict だが EvidencePack スキーマに合わない（Pydantic ValidationError）場合も None。"""
    client, table = _chain_mock()
    mock_factory.return_value = client

    future = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    table.execute.return_value = MagicMock(
        data=[
            {
                "owner_session_id": "owner-1",
                "pack": {"unexpected_field": "garbage"},  # dict だが EvidencePack 非互換
                "expires_at": future,
            }
        ]
    )

    assert load_pack("some-id", owner_session_id="owner-1") is None


@patch("src.evidence.cache.get_supabase_client")
def test_load_pack_returns_none_when_expires_at_is_null(mock_factory):
    """expires_at が欠損（None）している破損レコードでも AttributeError を raise しない。"""
    client, table = _chain_mock()
    mock_factory.return_value = client

    pack = _sample_pack()
    table.execute.return_value = MagicMock(
        data=[
            {
                "owner_session_id": "owner-1",
                "pack": pack.model_dump(mode="json"),
                "expires_at": None,
            }
        ]
    )

    assert load_pack("some-id", owner_session_id="owner-1") is None


@patch("src.evidence.cache.get_supabase_client")
def test_load_pack_returns_none_when_expires_at_is_malformed(mock_factory):
    client, table = _chain_mock()
    mock_factory.return_value = client

    pack = _sample_pack()
    table.execute.return_value = MagicMock(
        data=[
            {
                "owner_session_id": "owner-1",
                "pack": pack.model_dump(mode="json"),
                "expires_at": "not-an-iso-timestamp",
            }
        ]
    )

    assert load_pack("some-id", owner_session_id="owner-1") is None


@patch("src.evidence.cache.get_supabase_client")
def test_load_pack_returns_none_when_expires_at_is_naive(mock_factory):
    """tz 情報なし ISO 文字列（例: '2099-01-01T00:00:00'）は破損扱いで None。"""
    client, table = _chain_mock()
    mock_factory.return_value = client

    pack = _sample_pack()
    table.execute.return_value = MagicMock(
        data=[
            {
                "owner_session_id": "owner-1",
                "pack": pack.model_dump(mode="json"),
                "expires_at": "2099-01-01T00:00:00",  # tz 無し
            }
        ]
    )

    assert load_pack("some-id", owner_session_id="owner-1") is None


# ==============================
# Integration（ライブ Supabase）
# ==============================


def _live_supabase_ready() -> bool:
    url = os.environ.get("NEXT_PUBLIC_SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    return bool(url) and bool(key) and len(key) > 100


@pytest.mark.integration
@pytest.mark.skipif(not _live_supabase_ready(), reason="Supabase service_role key not set")
def test_integration_store_then_load_roundtrip():
    pack = _sample_pack()
    owner = "00000000-0000-4000-8000-000000000001"

    pack_id = store_pack(pack, owner_session_id=owner, ttl_minutes=1)
    loaded = load_pack(pack_id, owner_session_id=owner)
    assert loaded is not None
    assert loaded.query_context.region == pack.query_context.region

    # 所有者不一致は None
    mismatched = load_pack(pack_id, owner_session_id="00000000-0000-4000-8000-000000000002")
    assert mismatched is None


@pytest.mark.integration
@pytest.mark.skipif(not _live_supabase_ready(), reason="Supabase service_role key not set")
def test_integration_opportunistic_cleanup_removes_expired():
    """過去の expires_at を持つレコードを仕込んで、store_pack が削除することを確認。"""
    from src.supabase_client import get_supabase_client

    client = get_supabase_client()
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    owner = "00000000-0000-4000-8000-000000000003"
    # 期限切れレコードを事前に入れる
    existing = client.table("evidence_pack_sessions").insert({
        "owner_session_id": owner,
        "pack": _sample_pack().model_dump(mode="json"),
        "expires_at": past,
    }).execute()
    expired_id = existing.data[0]["id"]

    # 別 owner で store_pack を実行 → cleanup で expired_id が消えるはず
    store_pack(_sample_pack(), owner_session_id="00000000-0000-4000-8000-000000000004", ttl_minutes=1)

    # expired_id を検索して残っていないことを確認
    check = (
        client.table("evidence_pack_sessions")
        .select("id")
        .eq("id", expired_id)
        .limit(1)
        .execute()
    )
    assert not check.data, f"expired record {expired_id} should have been cleaned up"
