"""`/api/plans/*` エンドポイント（Phase 1.3d で最終化）。

`POST /api/plans/generate` の処理手順:
1. JWT 認証（`require_session`）
2. `PlanGenerationPayload` を Pydantic validate
   - plan_id / evidence_pack_id は UUID 型
   - transit_matrix は list[ClientTransitEdge]、max_length=200（静的 hard cap）
3. `load_pack(evidence_pack_id, owner_session_id=...)` で取り出し、None は 404
4. `validate_client_transit_matrix` で place_id 所属 / 自己ループ / 距離 15km /
   dedupe（完全一致 drop、矛盾 reject）/ 正規化後件数上限 を検証
5. `try_lock_plan_for_generation` で compare-and-set ロック取得
   - acquired: 続行
   - not_found: 404（plan 未知 or owner 不一致、漏えい防止で 404 に統一）
   - already_generating: 409（二重 generate 防止）
   - already_succeeded: 409（再生成は Phase 2 の別エンドポイントで）
6. `generate_plan(merged)` で LLM 生成（retry ×3 + fallback ×1、deadline 150s）
   失敗分類:
     - LlmGenerationError → 422（ハルシネーション持続）
     - LlmTransportError → 502（OpenAI 通信失敗）
     - LlmRefusalError → 422（safety refuse）
     - LlmBadRequestError → 500（実装バグ）
     - DeadlineExceededError → 504
     - 想定外例外 → 500（mark_plan_failed で status=failed に倒す保険）
   失敗時は mark_plan_failed（compare-and-set で generating→failed）
7. `call_finalize_plan` で原子的に plan_items bulk INSERT + plans.status='succeeded'
   失敗分類:
     - RpcTransportError → 504（commit 済か不明、status='generating' を残す、DB-3 cleanup に委任）
     - その他の例外 → 500 + mark_plan_failed

レスポンス:
- 成功: `{ "plan_id": "<UUID>" }` (200)
- 失敗: `{ "error": "...", ... }` + 適切な HTTP status
"""

from __future__ import annotations

import hashlib

from flask import Blueprint, current_app, g, jsonify, request
from pydantic import ValidationError

from ..auth import require_session
from ..evidence.cache import load_pack
from ..evidence.pack import EvidencePack
from ..evidence.validator import (
    TransitMatrixValidationError,
    validate_client_transit_matrix,
)
from ..llm.generator import (
    DeadlineExceededError,
    LlmBadRequestError,
    LlmGenerationError,
    LlmRefusalError,
    LlmTransportError,
    generate_plan as _generate_plan_llm,
)
from ..llm.schema import LlmPlanItem
from ..plans.storage import (
    RpcTransportError,
    call_finalize_plan,
    mark_plan_failed,
    try_lock_plan_for_generation,
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

    plan_id = str(payload.plan_id)
    owner_session_id = g.owner_session_id

    pack = load_pack(str(payload.evidence_pack_id), owner_session_id=owner_session_id)
    if pack is None:
        _log_pack_missing(str(payload.evidence_pack_id), owner_session_id)
        return jsonify({"error": "evidence pack not found or expired"}), 404

    try:
        validated = validate_client_transit_matrix(payload.transit_matrix, pack)
    except TransitMatrixValidationError as e:
        current_app.logger.info(f"transit_matrix rejected: {e}")
        return jsonify({"error": f"transit_matrix validation failed: {e}"}), 400

    merged = pack.model_copy(update={"transit_matrix": validated})

    # Lock 取得（compare-and-set）
    try:
        lock_result = try_lock_plan_for_generation(plan_id, owner_session_id)
    except RpcTransportError as e:
        current_app.logger.warning(f"acquire_plan_generation_lock transport error: {e}")
        return jsonify({"error": "failed to acquire plan lock (transport)"}), 504
    except Exception as e:
        current_app.logger.exception(f"acquire_plan_generation_lock unexpected: {e}")
        return jsonify({"error": "failed to acquire plan lock"}), 500

    if lock_result == "not_found":
        return jsonify({"error": "plan not found"}), 404
    if lock_result == "already_generating":
        return jsonify({"error": "plan is already being generated"}), 409
    if lock_result == "already_succeeded":
        return jsonify({"error": "plan already succeeded, regenerate via Phase 2 endpoint"}), 409
    if lock_result != "acquired":
        current_app.logger.error(f"unexpected lock_result: {lock_result!r}")
        return jsonify({"error": "unexpected plan lock state"}), 500

    # ここから先（lock 取得後）は、どの経路で失敗しても必ず status を generating から
    # 落とす（mark_plan_failed）か finalize_plan で succeeded にするかのどちらか。
    # 想定外例外で status='generating' のまま stuck するのを防ぐため、広めの try/except を被せる。
    # （RpcTransportError の finalize 経路だけは意図的に status=generating のまま残す。
    #  後述の分岐で明示的に return するので、この try/except は通らない）
    try:
        # LLM 生成
        try:
            generated = _generate_plan_llm(merged)
        except LlmGenerationError as e:
            current_app.logger.info(
                f"LLM generation failed: {len(e.issues)} issues after {e.attempts} attempts"
            )
            mark_plan_failed(plan_id, owner_session_id)
            return jsonify({
                "error": "plan generation failed after retries",
                "issues_count": len(e.issues),
            }), 422
        except LlmRefusalError as e:
            current_app.logger.info(f"LLM refused: {e}")
            mark_plan_failed(plan_id, owner_session_id)
            return jsonify({"error": "plan generation refused by model"}), 422
        except LlmBadRequestError as e:
            current_app.logger.exception(f"LLM bad request (implementation bug?): {e}")
            mark_plan_failed(plan_id, owner_session_id)
            return jsonify({"error": "plan generation request invalid"}), 500
        except LlmTransportError as e:
            current_app.logger.warning(f"LLM transport error: {e}")
            mark_plan_failed(plan_id, owner_session_id)
            return jsonify({"error": "plan generation service unavailable"}), 502
        except DeadlineExceededError as e:
            current_app.logger.warning(f"LLM deadline exceeded: {e}")
            mark_plan_failed(plan_id, owner_session_id)
            return jsonify({"error": "plan generation timed out"}), 504

        # LLM 出力を plan_items ペイロードに変換（merged pack の places から場所情報を引く）
        items_payload = [_serialize_plan_item(item, merged) for item in generated.items]

        # 原子保存 RPC
        try:
            call_finalize_plan(plan_id, owner_session_id, items_payload)
        except RpcTransportError as e:
            # 通信失敗: commit 済か未実行か不明。mark_plan_failed は呼ばず、
            # status=generating のまま残して DB-3 の stuck cleanup に救済を委ねる。
            current_app.logger.warning(
                f"finalize_plan transport error (status left as generating): {e}"
            )
            return jsonify({
                "error": "plan save unclear, please retry after checking /plan/<id>"
            }), 504
        except Exception as e:
            # 明示的失敗（RPC 内で例外）: status を failed に
            current_app.logger.exception(f"finalize_plan failed: {e}")
            mark_plan_failed(plan_id, owner_session_id)
            return jsonify({"error": "failed to save generated plan"}), 500

        return jsonify({"plan_id": plan_id}), 200
    except Exception as e:
        # 想定外例外（_serialize_plan_item のバグ、LLM 例外階層外の例外等）。
        # status=generating の stuck を防ぐため mark_plan_failed で落としてから再 raise。
        # 既にどこかで mark_plan_failed 済みなら compare-and-set で no-op なので二重更新なし。
        current_app.logger.exception(f"unexpected error after lock acquired: {e}")
        mark_plan_failed(plan_id, owner_session_id)
        return jsonify({"error": "unexpected error during plan generation"}), 500


# ==============================
# Private helpers
# ==============================


def _log_pack_missing(pack_id: str, owner_session_id: str) -> None:
    # PII 対策: Supabase user.id と pack_id は生で残さず hash 付きの短縮 prefix のみ
    owner_hash = hashlib.sha256(
        owner_session_id.encode("utf-8")
    ).hexdigest()[:8]
    current_app.logger.info(
        f"generate_plan: pack not available (pack_prefix={pack_id[:8]} "
        f"owner_hash={owner_hash}, reason=expired|unknown|owner-mismatch)"
    )


def _serialize_plan_item(item: LlmPlanItem, pack: EvidencePack) -> dict:
    """LlmPlanItem を plan_items テーブル行の JSONB dict に変換する。

    LLM は place_id しか出さないので、`pack.places` から引いて place_name / lat / lng /
    address を埋める（1.7 MapView が lat/lng を必須とするため）。
    `transit_to_next` は Phase 1.3d では未設定（Phase 2.4 の隣接アイテム間経路で使う予定）。
    `evidence.sources` は Phase 1.3d では最小限（Phase 2 で場所別根拠を埋める）。
    """
    place_name: str | None = None
    lat: float | None = None
    lng: float | None = None
    address: str | None = None
    if item.place_id is not None:
        place = next((p for p in pack.places if p.place_id == item.place_id), None)
        if place is not None:
            place_name = place.name
            lat = place.lat
            lng = place.lng
            address = place.address

    return {
        "order_index": item.order_index,
        "item_type": item.item_type,
        "title": item.title,
        "description": item.description,
        "start_time": item.start_time,
        "end_time": item.end_time,
        "place_id": item.place_id,
        "place_name": place_name,
        "lat": lat,
        "lng": lng,
        "address": address,
        "cost_jpy": item.cost_jpy,
        "cost_confidence": item.cost_confidence,
        "evidence": {"sources": []},
        "transit_to_next": None,
        "notes": None,
    }
