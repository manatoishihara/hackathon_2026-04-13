"""共有プランのインメモリ TTL キャッシュ。

succeeded プランは内容が変わらないため、TTL 60 秒のキャッシュで
同一 token への集中アクセス時も DB クエリを最小限に抑える。

スレッドセーフ: threading.Lock で排他。gunicorn --workers 1 構成では
プロセス間共有は不要だが、将来 gthread worker に移行した際も安全に動く。
"""

from __future__ import annotations

import threading
import time
from typing import Any

_TTL_SEC = 60
_cache: dict[str, tuple[Any, float]] = {}
_lock = threading.Lock()


def get_cached_shared_plan(token: str) -> Any | None:
    """キャッシュヒットなら dict を返す。未命中・期限切れは None。"""
    with _lock:
        entry = _cache.get(token)
        if entry is None:
            return None
        data, expires_at = entry
        if time.monotonic() > expires_at:
            del _cache[token]
            return None
        return data


def set_cached_shared_plan(token: str, data: Any) -> None:
    """レスポンス dict をキャッシュに保存する。"""
    with _lock:
        _cache[token] = (data, time.monotonic() + _TTL_SEC)


def invalidate_shared_plan(token: str) -> None:
    """share_token が再生成されたときにキャッシュを無効化する。"""
    with _lock:
        _cache.pop(token, None)
