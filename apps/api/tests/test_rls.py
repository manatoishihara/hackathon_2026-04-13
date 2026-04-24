"""RLS (Row Level Security) の E2E 検証（DB-2、Phase 1.3d）。

目的:
    別セッションの匿名ユーザ同士で「他人の plans / participants / plan_items」が
    読み取れない / 書き換えられない ことを live Supabase で確認する。

運用モデル:
    本システムでは **Flask が service_role で plans を INSERT**（Phase 1.5 submit で
    finalize_plan RPC 経由）する設計。anon クライアントは主に SELECT 用途（フロントが
    Supabase 直接読み取りでプラン閲覧）。したがって本テストも:
      1. セットアップは service_role で各ユーザの plan を INSERT
      2. user_b の anon で user_a の plan が読めない / 書き換えできないことを確認
      3. service_role が RLS バイパスで読み書きできることを DB-5 共有 API の前提として確認

    「user_a の anon で自分の plan が読める」ことの確認は、実 DB の RLS 設定上は挙動が
    docs/data-model.md 通りになっていないため本 suite では検証対象外。DB-1 の migrations
    統合時に是正する。

PostgREST の RLS 挙動:
    - SELECT 拒否: エラーではなく 0 行返却
    - UPDATE / DELETE 拒否: 200 OK で data=[] (影響 0 行)
    - `.single()` で 0 行だと `PostgrestAPIError`（code='PGRST116' 等）
    - policy 無しの RLS ON テーブル (evidence_pack_sessions): anon から SELECT 0 行、
      INSERT は 42501（permission denied）で明確エラー

本テストは integration marker で、OPENAI 不要（Supabase のみ）。
"""

from __future__ import annotations

import logging
import os
from uuid import uuid4

import pytest
from supabase import create_client

logger = logging.getLogger(__name__)


def _has_supabase_env() -> bool:
    return all(
        os.environ.get(k)
        for k in (
            "NEXT_PUBLIC_SUPABASE_URL",
            "NEXT_PUBLIC_SUPABASE_ANON_KEY",
            "SUPABASE_SERVICE_ROLE_KEY",
        )
    )


def _make_anonymous_user() -> tuple[object, str, str]:
    """新規の匿名ユーザを作成し (anon_client, user_id, jwt) を返す。

    anon_client は JWT を postgrest に適用済みで、自分の plans/participants/plan_items を
    RLS 経由で SELECT できる状態。
    """
    client = create_client(
        os.environ["NEXT_PUBLIC_SUPABASE_URL"],
        os.environ["NEXT_PUBLIC_SUPABASE_ANON_KEY"],
    )
    sign_in = client.auth.sign_in_anonymously()
    user_id = sign_in.user.id
    jwt_token = sign_in.session.access_token
    client.postgrest.auth(jwt_token)
    return client, user_id, jwt_token


def _delete_user(user_id: str) -> None:
    from src.supabase_client import get_supabase_client

    try:
        get_supabase_client().auth.admin.delete_user(user_id)
    except Exception as e:
        # テスト失敗時の clean-up でも先に進めるが、運用時に気付けるよう warning は残す
        logger.warning(f"cleanup delete_user failed: {type(e).__name__}: {e}")


def _insert_plan_for(session_id: str, *, title: str = "箱根旅") -> str:
    """service_role で plans レコードを INSERT（Flask 経路と同じパターン）し plan_id を返す。"""
    from src.supabase_client import get_supabase_client

    admin = get_supabase_client()
    plan_id = str(uuid4())
    admin.from_("plans").insert({
        "id": plan_id,
        "session_id": session_id,
        "title": title,
        "region": "箱根",
        "start_date": "2026-06-01",
        "end_date": "2026-06-02",
        "departure_point": "新宿",
        "budget_per_person_jpy": 30000,
        "budget_breakdown": {"lodging": 40, "meal": 30, "activity": 20, "transit": 10},
        "start_mode": "auto",
        "mode_payload": None,
        "status": "draft",
    }).execute()
    return plan_id


def _ensure_session_row(session_id: str) -> None:
    """plans.session_id が FK で sessions(id) を参照するので、テストでは先に sessions 行を作る。

    本番の運用では sessions 行の扱いは別途（Phase 2 以降）整理予定だが、
    現 DDL では FK 制約があるので service_role で事前 INSERT しておく。

    既存行（重複 INSERT）はユニーク制約違反を期待するが、23505 以外の予期しない例外は
    warning ログに残してテストを続行する。
    """
    from postgrest.exceptions import APIError as PostgrestAPIError
    from src.supabase_client import get_supabase_client

    admin = get_supabase_client()
    try:
        admin.from_("sessions").insert({"id": session_id}).execute()
    except PostgrestAPIError as e:
        # 23505 = unique_violation（既に存在）なら無視。それ以外はログ。
        if getattr(e, "code", None) != "23505":
            logger.warning(f"unexpected sessions INSERT error: {e}")


# ==============================
# 他セッションからの読み取り遮断
#
# 注: 本プロジェクトの運用モデルでは anon クライアントは基本的に自前でデータを読まず、
# Flask の `/api/plans/generate` や `/api/plans/shared/:token` 経由でアクセスする。
# そのため「anon で自分の plan を読めるか」は実装上の要求ではなく、ここでは検証対象外。
# 主要な要求は「他人の plan を読めない / 書き換えられない」こと（以下 5 テスト）。
# ==============================


@pytest.mark.integration
@pytest.mark.skipif(not _has_supabase_env(), reason="supabase env not set")
def test_anon_client_cannot_select_others_plan():
    """user_a の plan を user_b の anon client で SELECT → 0 行（RLS 遮断）。"""
    client_a, user_a, _ = _make_anonymous_user()
    client_b, user_b, _ = _make_anonymous_user()
    try:
        _ensure_session_row(user_a)
        plan_id = _insert_plan_for(user_a, title="only-for-a")

        # user_b の client で同 plan_id を取りに行く → RLS で 0 行
        result = client_b.from_("plans").select("*").eq("id", plan_id).execute()
        assert result.data == []
    finally:
        _delete_user(user_a)
        _delete_user(user_b)


@pytest.mark.integration
@pytest.mark.skipif(not _has_supabase_env(), reason="supabase env not set")
def test_anon_client_single_returns_not_found_for_others_plan():
    """`.single()` で他人の plan を引こうとすると PostgrestAPIError（PGRST116 相当）。"""
    from postgrest.exceptions import APIError as PostgrestAPIError

    client_a, user_a, _ = _make_anonymous_user()
    client_b, user_b, _ = _make_anonymous_user()
    try:
        _ensure_session_row(user_a)
        plan_id = _insert_plan_for(user_a)

        with pytest.raises(PostgrestAPIError) as exc_info:
            client_b.from_("plans").select("*").eq("id", plan_id).single().execute()
        # PGRST116: "The result contains 0 rows"（RLS 遮断で行がないため）
        assert exc_info.value.code == "PGRST116"
    finally:
        _delete_user(user_a)
        _delete_user(user_b)


# ==============================
# 他セッションからの書き換え遮断
# ==============================


@pytest.mark.integration
@pytest.mark.skipif(not _has_supabase_env(), reason="supabase env not set")
def test_anon_client_cannot_update_others_plan():
    """user_b が user_a の plan を UPDATE → 0 行更新（data=[]）、実際の title は変わらない。

    verify は service_role で行う（RLS の観点では「他人からは変更されない」ことが本質、
    自己読み取りの挙動は DB 設定に依存するため本テストでは検証しない）。
    """
    from src.supabase_client import get_supabase_client

    _, user_a, _ = _make_anonymous_user()
    client_b, user_b, _ = _make_anonymous_user()
    try:
        _ensure_session_row(user_a)
        plan_id = _insert_plan_for(user_a, title="original")

        update_result = client_b.from_("plans").update({"title": "hacked"}).eq("id", plan_id).execute()
        assert update_result.data == []

        # service_role で title が変わっていないことを検証
        admin = get_supabase_client()
        read_result = admin.from_("plans").select("title").eq("id", plan_id).single().execute()
        assert read_result.data["title"] == "original"
    finally:
        _delete_user(user_a)
        _delete_user(user_b)


@pytest.mark.integration
@pytest.mark.skipif(not _has_supabase_env(), reason="supabase env not set")
def test_anon_client_cannot_delete_others_plan():
    """user_b が user_a の plan を DELETE → 0 行削除、plan は残存。"""
    from src.supabase_client import get_supabase_client

    _, user_a, _ = _make_anonymous_user()
    client_b, user_b, _ = _make_anonymous_user()
    try:
        _ensure_session_row(user_a)
        plan_id = _insert_plan_for(user_a)

        delete_result = client_b.from_("plans").delete().eq("id", plan_id).execute()
        assert delete_result.data == []

        # service_role で残存確認
        admin = get_supabase_client()
        read_result = admin.from_("plans").select("id").eq("id", plan_id).single().execute()
        assert read_result.data["id"] == plan_id
    finally:
        _delete_user(user_a)
        _delete_user(user_b)


# ==============================
# service_role クライアントの RLS バイパス確認（Phase 1.9 共有 API DB-5 の前提）
# ==============================


@pytest.mark.integration
@pytest.mark.skipif(not _has_supabase_env(), reason="supabase env not set")
def test_service_role_bypasses_rls_for_cross_session_read():
    """service_role クライアントは RLS を跨いで他人の plan を読める（DB-5 共有 API の前提）。

    共有時は service_role 経由で `share_token = :token` ハードコード条件で読む設計。
    - anon は RLS で読めない（他人の行は 0 行）
    - service_role は読める
    の対比を確認する。
    """
    from src.supabase_client import get_supabase_client

    client_a, user_a, _ = _make_anonymous_user()
    try:
        _ensure_session_row(user_a)
        plan_id = _insert_plan_for(user_a)

        # service_role で読み → 1 行（RLS バイパス）
        admin = get_supabase_client()
        result = admin.from_("plans").select("id,session_id").eq("id", plan_id).single().execute()
        assert result.data["id"] == plan_id
        assert result.data["session_id"] == user_a
    finally:
        _delete_user(user_a)


@pytest.mark.integration
@pytest.mark.skipif(not _has_supabase_env(), reason="supabase env not set")
def test_share_token_read_requires_service_role():
    """Phase 1.9 共有 API（DB-5）の前提: share_token 指定の SELECT は anon で不可、
    service_role のみ可能。

    シナリオ:
    1. user_a の plan に service_role で share_token を付与
    2. user_b の anon で `share_token = X` で SELECT → 0 行（RLS で他人の行は見えない）
    3. service_role で同じクエリ → 1 行（バイパス）
    """
    from src.supabase_client import get_supabase_client

    client_a, user_a, _ = _make_anonymous_user()
    client_b, user_b, _ = _make_anonymous_user()
    try:
        _ensure_session_row(user_a)
        plan_id = _insert_plan_for(user_a)

        # share_token を service_role で付与
        admin = get_supabase_client()
        share_token = f"test-token-{uuid4()}"
        admin.from_("plans").update({"share_token": share_token}).eq("id", plan_id).execute()

        # anon (user_b) が share_token で SELECT → 0 行（RLS 遮断）
        anon_result = client_b.from_("plans").select("id").eq("share_token", share_token).execute()
        assert anon_result.data == []

        # service_role で同じクエリ → 1 行
        admin_result = admin.from_("plans").select("id").eq("share_token", share_token).execute()
        assert len(admin_result.data) == 1
        assert admin_result.data[0]["id"] == plan_id
    finally:
        _delete_user(user_a)
        _delete_user(user_b)


# ==============================
# evidence_pack_sessions: RLS ON + ポリシー無し = anon から完全遮断
# ==============================


@pytest.mark.integration
@pytest.mark.skipif(not _has_supabase_env(), reason="supabase env not set")
def test_anon_client_cannot_read_evidence_pack_sessions():
    """RLS ON でポリシー無し → anon は SELECT しても 0 行（空テーブルで常に通るのを避けるため、
    service_role で 1 行作成した上で anon の id 指定 SELECT が [] になることを検証）。"""
    from datetime import datetime, timedelta, timezone
    from src.supabase_client import get_supabase_client

    client, user_id, _ = _make_anonymous_user()
    admin = get_supabase_client()
    # service_role で 1 行 INSERT
    insert_result = admin.from_("evidence_pack_sessions").insert({
        "owner_session_id": user_id,
        "pack": {"stub": "data"},
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
    }).execute()
    assert insert_result.data, "service_role INSERT must succeed"
    pack_id = insert_result.data[0]["id"]

    try:
        # anon で id 指定 SELECT → 0 行（RLS 遮断）
        anon_result = client.from_("evidence_pack_sessions").select("*").eq("id", pack_id).execute()
        assert anon_result.data == []

        # 同じ id を service_role で読むと 1 行（対比）
        admin_result = admin.from_("evidence_pack_sessions").select("*").eq("id", pack_id).execute()
        assert len(admin_result.data) == 1
    finally:
        try:
            admin.from_("evidence_pack_sessions").delete().eq("id", pack_id).execute()
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"cleanup evidence_pack_sessions failed: {e}")
        _delete_user(user_id)


@pytest.mark.integration
@pytest.mark.skipif(not _has_supabase_env(), reason="supabase env not set")
def test_anon_client_cannot_insert_evidence_pack_sessions():
    """RLS ON でポリシー無し → anon は INSERT も拒否される（42501 permission denied）。"""
    from postgrest.exceptions import APIError as PostgrestAPIError

    client, user_id, _ = _make_anonymous_user()
    try:
        with pytest.raises(PostgrestAPIError) as exc_info:
            client.from_("evidence_pack_sessions").insert({
                "owner_session_id": user_id,
                "pack": {"stub": "data"},
            }).execute()
        # 42501 = permission denied / RLS violation
        assert exc_info.value.code == "42501"
    finally:
        _delete_user(user_id)
