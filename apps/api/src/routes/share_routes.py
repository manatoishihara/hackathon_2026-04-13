"""`/api/plans/:id/share` および `/api/plans/shared/:token` エンドポイント。

DB-4: POST /api/plans/<plan_id>/share
  - 認証必須（require_session）
  - plan の所有者 + status=succeeded のみ許可
  - share_token を生成（既存があれば再利用）
  - ShareResponse { share_token, share_url } を返す

DB-5: GET /api/plans/shared/<token>
  - 認証不要（share_token が唯一の認可材料）
  - get_shared_plan RPC（service_role）で 1 ラウンドトリップ取得
  - インメモリ TTL キャッシュで連続アクセス時の DB 負荷を削減
  - Cache-Control: public, max-age=60 でブラウザ・CDN もキャッシュ
  - レート制限: 60 回/分/IP（Flask-Limiter）
"""

from __future__ import annotations

import os
import secrets

from flask import Blueprint, current_app, g, jsonify, make_response, request
from pydantic import ValidationError

from ..auth import require_session
from ..cache.plan_cache import get_cached_shared_plan, invalidate_shared_plan, set_cached_shared_plan
from ..extensions import limiter
from ..schemas import (
    ShareResponse,
    SharedParticipant,
    SharedPlanItem,
    SharedPlanResponse,
    SharedPlanSummary,
)
from ..supabase_client import get_supabase_client

bp = Blueprint("share_routes", __name__, url_prefix="/api/plans")


# ==============================
# DB-4: share_token 生成
# ==============================

@bp.post("/<plan_id>/share")
@require_session
def create_share_token(plan_id: str):
    """プランの share_token を生成して返す。

    - status = 'succeeded' のプランのみ共有可能
    - 既存 token があれば再生成せず同一値を返す（冪等）
    - SITE_BASE_URL env から share_url を組み立てる
    """
    owner = g.owner_session_id
    client = get_supabase_client()

    result = (
        client.table("plans")
        .select("id,status,share_token")
        .eq("id", plan_id)
        .eq("session_id", owner)
        .limit(1)
        .execute()
    )
    rows = getattr(result, "data", None) or []
    if not rows:
        return jsonify({"error": "plan not found"}), 404

    plan = rows[0]

    if plan["status"] != "succeeded":
        return jsonify({
            "error": f"plan is not ready for sharing (status: {plan['status']})"
        }), 409

    token = plan.get("share_token")
    if not token:
        token = secrets.token_urlsafe(16)
        client.table("plans").update({"share_token": token}).eq("id", plan_id).eq("session_id", owner).execute()
        # 既存キャッシュが古い token に紐付いている場合は無効化（再生成時は古い token を無効化）
        if plan.get("share_token"):
            invalidate_shared_plan(plan["share_token"])

    site_base = os.environ.get("SITE_BASE_URL", "http://localhost:3000")
    share_url = f"{site_base}/plan/shared/{token}"

    resp = ShareResponse(share_token=token, share_url=share_url)
    return jsonify(resp.model_dump(mode="json")), 200


# ==============================
# DB-5: 共有プラン閲覧
# ==============================

@bp.get("/shared/<token>")
@limiter.limit("60 per minute")
def get_shared_plan(token: str):
    """share_token 経由でプランを公開取得する（認証不要）。

    セキュリティ:
      - share_token IS NOT NULL は RPC SQL 内にハードコード済み
      - Flask からリクエストパラメータで条件を変えることは不可能
      - service_role クライアントで RLS をバイパスするが、RPC のクエリ条件が保護を担保
    """
    # 1. インメモリキャッシュ確認
    cached = get_cached_shared_plan(token)
    if cached is not None:
        resp = make_response(jsonify(cached), 200)
        resp.headers["Cache-Control"] = "public, max-age=60, stale-while-revalidate=300"
        resp.headers["X-Cache"] = "HIT"
        return resp

    # 2. get_shared_plan RPC（plan + participants + plan_items を 1 ラウンドトリップ）
    client = get_supabase_client()
    try:
        result = client.rpc("get_shared_plan", {"p_token": token}).execute()
        raw = getattr(result, "data", None)
    except Exception as e:
        current_app.logger.error(f"get_shared_plan rpc failed: {e}")
        return jsonify({"error": "service temporarily unavailable"}), 503

    if raw is None:
        return jsonify({"error": "shared plan not found"}), 404

    # 3. Pydantic で整形（session_id / share_token / plan_id を除外）
    try:
        payload = _build_response(raw).model_dump(mode="json")
    except (ValidationError, Exception) as e:
        current_app.logger.error(f"get_shared_plan serialization failed: {e}")
        return jsonify({"error": "failed to process plan data"}), 500

    # 4. キャッシュ保存
    set_cached_shared_plan(token, payload)

    resp = make_response(jsonify(payload), 200)
    resp.headers["Cache-Control"] = "public, max-age=60, stale-while-revalidate=300"
    resp.headers["X-Cache"] = "MISS"
    return resp


# ==============================
# Private helpers
# ==============================

def _build_response(raw: dict) -> SharedPlanResponse:
    """RPC 生レスポンスを SharedPlanResponse Pydantic モデルに変換する。

    plan_items: DB は place_id/place_name/lat/lng/address をフラットカラムで持つ。
    SharedPlanItem は location: Location（ネスト）なので手動で組み立てる。
    """
    plan = SharedPlanSummary.model_validate(raw["plan"])

    participants = [
        SharedParticipant.model_validate(p) for p in (raw.get("participants") or [])
    ]

    plan_items = [
        SharedPlanItem.model_validate(_flatten_to_item(i))
        for i in (raw.get("plan_items") or [])
    ]

    return SharedPlanResponse(plan=plan, participants=participants, plan_items=plan_items)


def _flatten_to_item(row: dict) -> dict:
    """plan_items の DB フラットカラムを SharedPlanItem スキーマ形式に変換する。"""
    return {
        "id":              row["id"],
        "order_index":     row["order_index"],
        "item_type":       row["item_type"],
        "title":           row["title"],
        "description":     row.get("description"),
        "start_time":      row["start_time"],
        "end_time":        row["end_time"],
        "location": {
            "place_id":   row.get("place_id"),
            "place_name": row.get("place_name"),
            "lat":        row.get("lat"),
            "lng":        row.get("lng"),
            "address":    row.get("address"),
        },
        "cost_jpy":        row.get("cost_jpy"),
        "cost_confidence": row.get("cost_confidence"),
        "evidence":        row["evidence"],
        "transit_to_next": row.get("transit_to_next"),
        "notes":           row.get("notes"),
        "created_at":      row["created_at"],
        "updated_at":      row["updated_at"],
    }
