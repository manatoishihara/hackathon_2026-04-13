"""`plans` テーブル / `plan_items` テーブルへの操作を RPC 経由で行う薄いラッパ（Phase 1.3d）。

RPC 自体は `supabase/migrations/20260424_04_plan_generation_rpcs.sql` を参照。
Flask 側から見るとこのモジュールは「3 つの副作用関数」に見え、race 条件は RPC 内で
SELECT ... FOR UPDATE により直列化されているので安全。

通信失敗（ネットワークエラー / タイムアウト）は `RpcTransportError` にラップして
「commit 済か未実行か不明」のケースを呼び出し側が 504 で応答する材料にする。
supabase-py は内部で httpx を使うため、httpx の TimeoutException / TransportError も
transport error として wrap する。Postgres 側の明示的例外（owner mismatch 等）は
そのまま伝播させて呼び出し側で 500 に畳む。
"""

from __future__ import annotations

import logging
from typing import Literal

import httpx

from ..supabase_client import get_supabase_client

logger = logging.getLogger(__name__)

LockResult = Literal["acquired", "not_found", "already_generating", "already_succeeded"]
_VALID_LOCK_RESULTS: set[str] = {
    "acquired",
    "not_found",
    "already_generating",
    "already_succeeded",
}

# RPC の通信層失敗として wrap する例外型。
# supabase-py は httpx 経由なので httpx 系を、念のため builtins の
# ConnectionError / TimeoutError もカバー。
# 実装バグ（AttributeError / KeyError / TypeError 等）は wrap しない（デバッグ性維持）。
_TRANSPORT_EXCEPTIONS: tuple[type[BaseException], ...] = (
    ConnectionError,
    TimeoutError,
    httpx.TimeoutException,
    httpx.TransportError,
)


class RpcTransportError(RuntimeError):
    """RPC 呼び出しの通信層失敗（commit 済か不明）。route 側で 504 応答に使う。"""


def try_lock_plan_for_generation(
    plan_id: str, owner_session_id: str
) -> LockResult:
    """acquire_plan_generation_lock RPC を呼び、結果を返す。

    戻り値は LockResult の 4 値のいずれか。それ以外は ValueError（契約違反）。
    通信エラーは RpcTransportError に wrap する。
    """
    try:
        result = get_supabase_client().rpc(
            "acquire_plan_generation_lock",
            {"p_plan_id": plan_id, "p_session_id": owner_session_id},
        ).execute()
    except _TRANSPORT_EXCEPTIONS as e:
        raise RpcTransportError(f"acquire_plan_generation_lock transport error: {e}") from e

    data = getattr(result, "data", None)
    if data not in _VALID_LOCK_RESULTS:
        raise ValueError(
            f"unexpected acquire_plan_generation_lock result: {data!r}"
        )
    return data  # type: ignore[return-value]


def call_finalize_plan(
    plan_id: str, owner_session_id: str, items: list[dict]
) -> None:
    """finalize_plan RPC を呼ぶ。plan_items bulk INSERT + status='succeeded' の原子実行。

    通信エラーは RpcTransportError に wrap（commit 済か未実行か不明、route 側で 504）。
    PostgREST / Postgres の明示的例外はそのまま伝播（route 側で 500 + mark_plan_failed）。
    """
    try:
        get_supabase_client().rpc(
            "finalize_plan",
            {"p_plan_id": plan_id, "p_session_id": owner_session_id, "p_items": items},
        ).execute()
    except _TRANSPORT_EXCEPTIONS as e:
        raise RpcTransportError(f"finalize_plan transport error: {e}") from e


def mark_plan_failed(plan_id: str, owner_session_id: str) -> None:
    """mark_plan_failed RPC を呼ぶ。compare-and-set で generating → failed。

    呼び出し側は既にエラー応答を返す段階なので、**通信系例外** は warning ログで握り潰し、
    例外を伝播させない（UX ブロック回避）。stuck な generating は DB-3 cleanup が救済。

    実装バグ（AttributeError / TypeError 等）は握りつぶさない（デバッグ性維持）ので、
    `Exception` ではなく `_TRANSPORT_EXCEPTIONS` に限定する。
    """
    try:
        get_supabase_client().rpc(
            "mark_plan_failed",
            {"p_plan_id": plan_id, "p_session_id": owner_session_id},
        ).execute()
    except _TRANSPORT_EXCEPTIONS as e:
        logger.warning(
            f"mark_plan_failed transport error (swallowed): {type(e).__name__}: {e}"
        )
