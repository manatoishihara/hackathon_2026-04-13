"""`/api/plans/*` エンドポイント（Phase 1.3c 時点では `/generate` の骨組みのみ）。

設計:
- JWT 認証必須（`require_session`）
- 入力 `PlanGenerationPayload` を Pydantic validate
  - evidence_pack_id: UUID 型
  - transit_matrix: list[ClientTransitEdge]、max_length=200（静的 hard cap）
- `load_pack(evidence_pack_id, owner_session_id=...)` で取り出し、None は 404
  （期限切れ / 未知 / 所有者不一致を集約、情報漏えい防止）。内部ログには hash 化した
  owner prefix と pack_id の先頭 8 文字のみ残す
- `validate_client_transit_matrix` で place_id 所属 / 自己ループ / 距離 15km /
  dedupe（完全一致 drop、矛盾 reject）/ 正規化後件数上限 を検証
- 検証済み transit を base_pack に merge（transit_matrix のみ上書き）
- 通常レスポンス: `{ "plan_id": null }`
- `?debug=1` の時のみ `{ "plan_id": null, "evidence_pack": <dict> }` を返す
  （1.3d で `{ "plan_id": <UUID> }` に差し替え予定）
"""

from __future__ import annotations

import hashlib

from flask import Blueprint, current_app, g, jsonify, request
from pydantic import ValidationError

from ..auth import require_session
from ..evidence.cache import load_pack
from ..evidence.validator import (
    TransitMatrixValidationError,
    validate_client_transit_matrix,
)
from ..schemas import PlanGenerationPayload

bp = Blueprint("plan_routes", __name__, url_prefix="/api/plans")


@bp.post("/generate")
@require_session
def generate_plan():
    raw = request.get_json(silent=True)
    if not isinstance(raw, dict):
        return jsonify({"error": "request body must be a JSON object"}), 400

    try:
        payload = PlanGenerationPayload.model_validate(raw)
    except ValidationError as e:
        # include_context=False: field_validator が raise した ValueError オブジェクトを
        # ctx から外す（そのままでは JSON シリアライズできずに 500 に畳まれる）
        return jsonify({
            "error": "validation failed",
            "details": e.errors(include_context=False),
        }), 400

    pack = load_pack(str(payload.evidence_pack_id), owner_session_id=g.owner_session_id)
    if pack is None:
        # PII 対策: Supabase user.id と pack_id は生で残さず hash 付きの短縮 prefix のみ
        owner_hash = hashlib.sha256(
            g.owner_session_id.encode("utf-8")
        ).hexdigest()[:8]
        pack_prefix = str(payload.evidence_pack_id)[:8]
        current_app.logger.info(
            f"generate_plan: pack not available (pack_prefix={pack_prefix} "
            f"owner_hash={owner_hash}, reason=expired|unknown|owner-mismatch)"
        )
        return jsonify({"error": "evidence pack not found or expired"}), 404

    try:
        validated = validate_client_transit_matrix(payload.transit_matrix, pack)
    except TransitMatrixValidationError as e:
        current_app.logger.info(f"transit_matrix rejected: {e}")
        return jsonify({"error": f"transit_matrix validation failed: {e}"}), 400

    merged = pack.model_copy(update={"transit_matrix": validated})

    # 1.3c のレスポンスは debug 用途を除いて {"plan_id": null} のみ。
    # ?debug=1 の時だけ merged pack を追加で返す。1.3d で LLM を繋いだら
    # 通常レスポンスを {"plan_id": <UUID>} に差し替える。
    if request.args.get("debug") == "1":
        return jsonify({
            "plan_id": None,
            "evidence_pack": merged.model_dump(mode="json"),
        }), 200
    return jsonify({"plan_id": None}), 200
