"""Evidence Pack の短期キャッシュ（`evidence_pack_sessions` テーブル）。

- `store_pack`: opportunistic cleanup + insert + 失敗時 retry（2 回, jitter）
- `load_pack`: id + owner_session_id で照合 + 期限チェック。不一致・期限切れは None
- TTL デフォルト 15 分（フロント transit 取得 + LLM 生成までの余裕込み）
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from random import uniform
from time import sleep

from ..supabase_client import get_supabase_client
from .pack import EvidencePack

_TABLE = "evidence_pack_sessions"
_DEFAULT_TTL_MINUTES = 15
_MAX_RETRIES = 2
_RETRY_BASE_DELAY_SEC = 0.1
_RETRY_JITTER_SEC = 0.2


class CacheError(RuntimeError):
    """Evidence Pack のキャッシュ操作失敗。retry も駄目だった場合のみ raise される。"""


def store_pack(
    pack: EvidencePack,
    *,
    owner_session_id: str,
    ttl_minutes: int = _DEFAULT_TTL_MINUTES,
) -> str:
    """Pack を Supabase に保存し、発行された UUID を返す。

    事前に期限切れレコードを削除（opportunistic cleanup）することでテーブル
    無限増加を防ぐ。cleanup 失敗は致命的でないので飲み込む。
    insert は最大 2 回 retry（指数的 + jitter）で一時的な失敗を救う。
    """
    client = get_supabase_client()
    now = datetime.now(timezone.utc)

    try:
        client.table(_TABLE).delete().lt("expires_at", now.isoformat()).execute()
    except Exception:
        # cleanup 失敗はログだけで継続（次回以降の呼び出しで救える）
        pass

    expires_at = (now + timedelta(minutes=ttl_minutes)).isoformat()
    payload = {
        "owner_session_id": owner_session_id,
        "pack": pack.model_dump(mode="json"),
        "expires_at": expires_at,
    }

    last_error: Exception | None = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            result = client.table(_TABLE).insert(payload).execute()
            rows = getattr(result, "data", None) or []
            if rows and rows[0].get("id"):
                return rows[0]["id"]
            last_error = CacheError("insert returned no data")
        except Exception as e:
            last_error = e
        if attempt < _MAX_RETRIES:
            sleep(_RETRY_BASE_DELAY_SEC * (attempt + 1) + uniform(0, _RETRY_JITTER_SEC))

    raise CacheError(
        f"store_pack failed after {_MAX_RETRIES + 1} attempts: "
        f"{type(last_error).__name__}: {last_error}"
    )


def load_pack(pack_id: str, *, owner_session_id: str) -> EvidencePack | None:
    """所有者照合 + 期限チェック付きで Pack を取得する。

    - 該当 id 無し / 所有者不一致 / 期限切れ のいずれも None を返す
    - DB 通信エラーは呼び出し元へ raise（呼び出し側が 500 で応答）
    """
    client = get_supabase_client()
    now = datetime.now(timezone.utc)

    result = (
        client.table(_TABLE)
        .select("owner_session_id,pack,expires_at")
        .eq("id", pack_id)
        .limit(1)
        .execute()
    )
    rows = getattr(result, "data", None) or []
    if not rows:
        return None
    row = rows[0]
    if row.get("owner_session_id") != owner_session_id:
        return None

    expires_at_raw = row.get("expires_at")
    if not isinstance(expires_at_raw, str):
        return None
    try:
        # fromisoformat は +00:00 / Z どちらも受け付ける（Python 3.11+）。
        # 念のため Z 表記を明示的に +00:00 に直す
        expires_at = datetime.fromisoformat(expires_at_raw.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    # tz 情報が無い（naive）と aware な `now` と比較できず TypeError になる。
    # Supabase は必ず tz 付きで返すので naive が来たら破損扱い。
    if expires_at.tzinfo is None:
        return None
    if expires_at < now:
        return None

    pack_data = row.get("pack")
    if not isinstance(pack_data, dict):
        return None
    try:
        return EvidencePack.model_validate(pack_data)
    except Exception:
        # Pydantic ValidationError など、破損 pack は静かに None で返す（呼び出し側は
        # 404 扱いで再生成するしかない）
        return None
