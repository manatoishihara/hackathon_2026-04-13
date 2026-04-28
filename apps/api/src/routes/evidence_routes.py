"""`/api/evidence/*` エンドポイント（Phase 1.3a）。

現時点では `/api/evidence/places` のみ:
- JWT 認証必須（`require_session` デコレータ）
- `GeneratePlanRequest` で入力検証
- `build_evidence_pack` で places のみ取得、予算・時間制約を展開
- `store_pack` で短期キャッシュに入れ、フロントには `evidence_pack_id + places の最小サブセット` を返す

transit はフロント Maps JS SDK で取得後、Phase 1.3c の `/api/plans/generate` に送られる。
"""

from __future__ import annotations

from flask import Blueprint, current_app, g, jsonify, request
from pydantic import ValidationError

from ..auth import require_session
from ..evidence.builder import (
    AnchorFetchError,
    AnchorFetchUpstreamError,
    build_evidence_pack,
)
from ..evidence.cache import CacheError, store_pack
from ..schemas import (
    EvidencePlacesPlaceSummary,
    EvidencePlacesResponse,
    GeneratePlanRequest,
)

bp = Blueprint("evidence_routes", __name__, url_prefix="/api/evidence")


@bp.post("/places")
@require_session
def create_places_pack():
    raw = request.get_json(silent=True)
    if not isinstance(raw, dict):
        return jsonify({"error": "request body must be a JSON object"}), 400

    try:
        payload = GeneratePlanRequest.model_validate(raw)
    except ValidationError as e:
        # include_context=False: model_validator が raise した ValueError オブジェクトを
        # ctx から外す（そのままでは JSON シリアライズできずに 500 に畳まれる）
        return jsonify({
            "error": "validation failed",
            "details": e.errors(include_context=False),
        }), 400

    try:
        pack = build_evidence_pack(payload)
    except AnchorFetchError as e:
        # Phase 2.1 Codex Major 3: anchor が 404 (存在しない) → user 入力ミス相当で 400。
        return jsonify({
            "error": "anchor places not found",
            "missing_anchor_ids": e.missing_ids,
        }), 400
    except AnchorFetchUpstreamError as e:
        # Codex 再レビュー Major 1: Places API 側のインフラ障害は user の責ではないので 502。
        # 監視メトリクス（5xx 率）が誤って 400 に薄まらないようにする。
        current_app.logger.warning(
            f"anchor fetch upstream error: place_id={e.place_id!r} cause={e.__cause__}"
        )
        return jsonify({"error": "anchor lookup upstream unavailable"}), 502

    try:
        pack_id = store_pack(pack, owner_session_id=g.owner_session_id)
    except CacheError as e:
        current_app.logger.error(f"store_pack failed: {e}")
        return jsonify({"error": "failed to cache evidence pack"}), 500

    response = EvidencePlacesResponse(
        evidence_pack_id=pack_id,
        places=[
            EvidencePlacesPlaceSummary(
                place_id=p.place_id,
                name=p.name,
                lat=p.lat,
                lng=p.lng,
            )
            for p in pack.places
        ],
    )
    return response.model_dump(mode="json"), 200
