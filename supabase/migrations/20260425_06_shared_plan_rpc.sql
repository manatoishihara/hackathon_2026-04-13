-- Phase 1.9 DB-5: 共有プラン一括取得 RPC（非同期・バッチ化）
-- =====================================================================
-- 目的:
--   GET /api/plans/shared/:token で必要な plan / participants / plan_items の
--   3 テーブル取得を 1 本の RPC に集約し、Flask ↔ Supabase のラウンドトリップを
--   3 回 → 1 回に削減する（⑬ 非同期・バッチ化）。
--
--   Flask から service_role クライアントで呼ぶため RLS をバイパスする。
--   share_token IS NOT NULL の条件は SQL 内にハードコードし、
--   リクエストパラメータで変えられない設計を維持する（handoff-db.md DB-5 方針）。
--
-- 呼び出し方（Flask 側）:
--   result = client.rpc("get_shared_plan", {"p_token": token}).execute()
--   # result.data が None → 404、JSONB → plan / participants / plan_items を取り出す
--
-- 戻り値:
--   - token が見つかる / share_token IS NOT NULL の場合:
--     {
--       "plan":         { plans テーブルの全カラム（session_id / share_token も含む） },
--       "participants": [ { participants 全カラム } ... ]  ← order_index 昇順
--       "plan_items":   [ { plan_items 全カラム } ... ]    ← order_index 昇順
--     }
--     ※ session_id / share_token / plan_id の除外は Flask 側 Pydantic で行う
--   - 見つからない場合: NULL
--
-- 冪等性: CREATE OR REPLACE FUNCTION

CREATE OR REPLACE FUNCTION get_shared_plan(p_token TEXT)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    v_plan  plans%ROWTYPE;
    v_participants JSONB;
    v_plan_items   JSONB;
BEGIN
    -- share_token 照合。IS NOT NULL を WHERE に固定してリクエスト側で変えられない設計。
    SELECT * INTO v_plan
    FROM plans
    WHERE share_token = p_token
      AND share_token IS NOT NULL;

    IF NOT FOUND THEN
        RETURN NULL;
    END IF;

    -- participants を order_index 昇順で集約（0 件は空配列）
    SELECT COALESCE(
               jsonb_agg(to_jsonb(pa.*) ORDER BY pa.order_index),
               '[]'::jsonb
           )
    INTO v_participants
    FROM participants pa
    WHERE pa.plan_id = v_plan.id;

    -- plan_items を order_index 昇順で集約（0 件は空配列）
    SELECT COALESCE(
               jsonb_agg(to_jsonb(pi.*) ORDER BY pi.order_index),
               '[]'::jsonb
           )
    INTO v_plan_items
    FROM plan_items pi
    WHERE pi.plan_id = v_plan.id;

    RETURN jsonb_build_object(
        'plan',         to_jsonb(v_plan),
        'participants', v_participants,
        'plan_items',   v_plan_items
    );
END;
$$;
