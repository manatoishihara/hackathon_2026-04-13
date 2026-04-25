-- Phase 1.9 DB-5: get_shared_plan RPC v2（SELECT * 廃止・最小カラム取得）
-- =====================================================================
-- 変更理由（チートシート ③⑦ の対応）:
--   v1（20260425_06）は `to_jsonb(p.*)` で plans / participants / plan_items の
--   全カラムを取得していた（SELECT * 相当）。
--   session_id / share_token / plan_id など Flask 側で除外するカラムも
--   Supabase → Flask 間のネットワークを流れていた。
--
--   v2 は Pydantic の公開型（SharedPlanSummary / SharedParticipant / SharedPlanItem）
--   と 1:1 になるカラムだけを jsonb_build_object で明示的に組み立てる。
--   - plans.session_id / plans.share_token → 送信しない
--   - participants.plan_id / plan_items.plan_id → 送信しない
--   - plan_items: LIMIT 100（異常データで巨大 JSON になるのを防ぐ）
--   - participants: LIMIT 5（ドメイン最大 5 人）
--
-- 冪等性: CREATE OR REPLACE で v1 を上書き。呼び出し側のシグネチャは変わらない。

CREATE OR REPLACE FUNCTION get_shared_plan(p_token TEXT)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    v_plan_id   UUID;
    v_plan_json JSONB;
    v_participants JSONB;
    v_plan_items   JSONB;
BEGIN
    -- share_token 照合（NULL ガード込み）
    -- SharedPlanSummary に必要なカラムだけ組み立てる（session_id / share_token は除外）
    SELECT
        p.id,
        jsonb_build_object(
            'id',                     p.id,
            'title',                  p.title,
            'region',                 p.region,
            'start_date',             p.start_date,
            'end_date',               p.end_date,
            'departure_point',        p.departure_point,
            'budget_per_person_jpy',  p.budget_per_person_jpy,
            'budget_breakdown',       p.budget_breakdown,
            'start_mode',             p.start_mode,
            'mode_payload',           p.mode_payload,
            'status',                 p.status,
            'created_at',             p.created_at,
            'updated_at',             p.updated_at
        )
    INTO v_plan_id, v_plan_json
    FROM plans p
    WHERE p.share_token = p_token
      AND p.share_token IS NOT NULL;

    IF v_plan_id IS NULL THEN
        RETURN NULL;
    END IF;

    -- SharedParticipant に必要なカラムだけ（plan_id は除外）、最大 5 件
    SELECT COALESCE(
               jsonb_agg(
                   jsonb_build_object(
                       'id',           pa.id,
                       'display_name', pa.display_name,
                       'avatar_color', pa.avatar_color,
                       'wishes_text',  pa.wishes_text,
                       'tags',         pa.tags,
                       'order_index',  pa.order_index
                   )
                   ORDER BY pa.order_index
               ),
               '[]'::jsonb
           )
    INTO v_participants
    FROM (
        SELECT * FROM participants
        WHERE plan_id = v_plan_id
        ORDER BY order_index
        LIMIT 5
    ) pa;

    -- SharedPlanItem に必要なカラムだけ（plan_id は除外）、最大 100 件
    -- place_id / place_name / lat / lng / address は Flask 側で location オブジェクトに変換
    SELECT COALESCE(
               jsonb_agg(
                   jsonb_build_object(
                       'id',              pi.id,
                       'order_index',     pi.order_index,
                       'item_type',       pi.item_type,
                       'title',           pi.title,
                       'description',     pi.description,
                       'start_time',      pi.start_time,
                       'end_time',        pi.end_time,
                       'place_id',        pi.place_id,
                       'place_name',      pi.place_name,
                       'lat',             pi.lat,
                       'lng',             pi.lng,
                       'address',         pi.address,
                       'cost_jpy',        pi.cost_jpy,
                       'cost_confidence', pi.cost_confidence,
                       'evidence',        pi.evidence,
                       'transit_to_next', pi.transit_to_next,
                       'notes',           pi.notes,
                       'created_at',      pi.created_at,
                       'updated_at',      pi.updated_at
                   )
                   ORDER BY pi.order_index
               ),
               '[]'::jsonb
           )
    INTO v_plan_items
    FROM (
        SELECT * FROM plan_items
        WHERE plan_id = v_plan_id
        ORDER BY order_index
        LIMIT 100
    ) pi;

    RETURN jsonb_build_object(
        'plan',         v_plan_json,
        'participants', v_participants,
        'plan_items',   v_plan_items
    );
END;
$$;
