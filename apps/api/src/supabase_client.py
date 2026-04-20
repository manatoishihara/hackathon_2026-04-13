"""Supabase サーバクライアント。

service_role キーを使うため RLS をバイパスする。フロントから受け取ったユーザの
セッション JWT でスコープさせる処理は Phase 1 以降で別途用意する。
"""

from __future__ import annotations

import os

from supabase import Client, create_client


def get_supabase_client() -> Client:
    """環境変数から Supabase クライアントを生成する。

    Raises:
        RuntimeError: 必須環境変数が未設定のとき。
    """
    url = os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise RuntimeError(
            "Supabase env vars が未設定です。"
            ".env.local に NEXT_PUBLIC_SUPABASE_URL と SUPABASE_SERVICE_ROLE_KEY を設定してください。"
        )
    return create_client(url, key)
