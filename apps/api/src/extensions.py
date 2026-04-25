"""Flask 拡張のシングルトン定義。

app.py と routes の両方からインポートするため循環インポートを避けるために独立モジュールに定義する。
app.py で `limiter.init_app(app)` を呼ぶことで Flask アプリに紐付ける。
"""

from __future__ import annotations

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri="memory://",        # シングルワーカー構成なのでプロセスメモリで十分
    default_limits=["200 per minute"],
)
