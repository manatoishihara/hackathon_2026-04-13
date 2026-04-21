"""Supabase 匿名セッションの JWT を検証する Flask デコレータ。

`Authorization: Bearer <JWT>` を読み、`supabase.auth.get_user(jwt)` で
検証したうえで `flask.g.owner_session_id` に user.id をセットする。
検証失敗は 401、ヘッダ欠損も 401。
"""

from __future__ import annotations

from functools import wraps
from typing import Callable

from flask import current_app, g, jsonify, request

from .supabase_client import get_supabase_client


def require_session(view_func: Callable) -> Callable:
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "missing or malformed Authorization header"}), 401
        jwt_token = auth_header[len("Bearer "):].strip()
        if not jwt_token:
            return jsonify({"error": "missing bearer token"}), 401
        try:
            user_resp = get_supabase_client().auth.get_user(jwt_token)
        except Exception as e:
            # 認証失敗と Supabase 側インフラ障害の両方が 401 に集約されるため、
            # 運用での切り分けはログに残した型と詳細で行う
            current_app.logger.warning(
                f"require_session: auth validation failed: {type(e).__name__}: {e}"
            )
            return jsonify({"error": f"invalid token: {type(e).__name__}"}), 401

        user = getattr(user_resp, "user", None)
        if user is None or not getattr(user, "id", None):
            return jsonify({"error": "invalid token"}), 401

        g.owner_session_id = user.id
        return view_func(*args, **kwargs)

    return wrapper
