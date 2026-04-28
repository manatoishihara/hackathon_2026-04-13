"""Supabase サーバクライアント。

service_role キーを使うため RLS をバイパスする。

## コネクションプール
supabase-py v2 は内部で httpx.Client を使う。`create_client()` を毎回呼ぶと
httpx.Client が都度生成されて TCP 接続の再利用ができない。
モジュールレベルのシングルトンにすることでプロセス内の接続を再利用し、
接続確立コストとレイテンシを削減する（gunicorn worker 1 個 = プロセス 1 個で有効）。

## Read/Write 分離
現状は Supabase Free プランのため Read Replica が利用不可。
アプリコード上は get_supabase_client()（service_role）を書き込みと
RLS バイパスが必要な読み取りの両方に使う統一方針とする。
Pro プランへ移行する際は SUPABASE_READ_REPLICA_URL を追加して
get_supabase_reader_client() を別エンドポイントに向ければよい。
"""

from __future__ import annotations

import os
import threading

from supabase import Client, create_client

_client: Client | None = None
_client_lock = threading.Lock()


def get_supabase_client() -> Client:
    """Supabase service_role クライアントをシングルトンで返す。

    初回呼び出し時のみ create_client() を実行し、以降は同一インスタンスを返す。
    double-checked locking で複数スレッドからの同時初期化を防ぐ。

    Raises:
        RuntimeError: 必須環境変数が未設定のとき。
    """
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = _build_client()
    return _client


def _build_client() -> Client:
    url = os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise RuntimeError(
            "Supabase env vars が未設定です。"
            ".env.local に NEXT_PUBLIC_SUPABASE_URL と SUPABASE_SERVICE_ROLE_KEY を設定してください。"
        )
    return create_client(url, key)


def _reset_client() -> None:
    """テスト用: シングルトンをリセットして次回呼び出し時に再生成させる。"""
    global _client
    with _client_lock:
        _client = None
