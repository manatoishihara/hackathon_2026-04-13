-- Phase 1.3d: プラン生成の原子性保証 RPC 群
-- ========================================
-- 以下の 3 関数 + 1 enum を定義する:
--   acquire_plan_generation_lock: status IN ('draft','failed') のときのみ 'generating' に昇格
--   mark_plan_failed: status='generating' のときのみ 'failed' に遷移（compare-and-set）
--   finalize_plan: plan_items bulk INSERT + status='succeeded' を 1 トランザクションで
--
-- 冪等性:
--   enum は DO ブロックで pg_type 存在確認して CREATE TYPE
--   関数は CREATE OR REPLACE で上書き可能
--   → migration を複数回実行しても同じ結果
--
-- 適用手順:
--   1. Supabase SQL Editor で本ファイル内容を貼り付けて実行
--   2. Extensions タブで `pg_cron` が有効化されていることを確認（DB-3 migration の前提）

-- ==============================
-- enum
-- ==============================
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'plan_lock_result') THEN
        CREATE TYPE plan_lock_result AS ENUM (
            'acquired',
            'not_found',
            'already_generating',
            'already_succeeded'
        );
    END IF;
END $$;

-- ==============================
-- acquire_plan_generation_lock
-- ==============================
-- compare-and-set: 'draft' or 'failed' の plan を 'generating' に昇格させる。
-- Flask 側の UPDATE ... RETURNING + 補足 SELECT は race があるため、RPC 内で
-- SELECT ... FOR UPDATE により同時実行を直列化する。
CREATE OR REPLACE FUNCTION acquire_plan_generation_lock(
    p_plan_id UUID,
    p_session_id UUID
) RETURNS plan_lock_result
LANGUAGE plpgsql
AS $$
DECLARE
    v_status TEXT;
BEGIN
    -- 対象行をロック。plan_id + session_id が一致しないと 0 行 → FOUND=false
    SELECT status INTO v_status
    FROM plans
    WHERE id = p_plan_id AND session_id = p_session_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RETURN 'not_found';
    END IF;

    IF v_status IN ('draft', 'failed') THEN
        UPDATE plans SET status = 'generating', updated_at = NOW() WHERE id = p_plan_id;
        RETURN 'acquired';
    ELSIF v_status = 'generating' THEN
        RETURN 'already_generating';
    ELSIF v_status = 'succeeded' THEN
        RETURN 'already_succeeded';
    ELSE
        RAISE EXCEPTION 'unexpected plan status: %', v_status;
    END IF;
END;
$$;

-- ==============================
-- mark_plan_failed
-- ==============================
-- compare-and-set: 'generating' 状態のときだけ 'failed' に落とす。
-- 他プロセスが既に succeeded に到達している場合は no-op（上書きしない）。
-- 明示的に owner 照合もしているので、他人の plan を failed にはできない。
CREATE OR REPLACE FUNCTION mark_plan_failed(
    p_plan_id UUID,
    p_session_id UUID
) RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    UPDATE plans
    SET status = 'failed', updated_at = NOW()
    WHERE id = p_plan_id
      AND session_id = p_session_id
      AND status = 'generating';
END;
$$;

-- ==============================
-- finalize_plan
-- ==============================
-- LLM 生成完了後に呼ぶ。以下を 1 トランザクションで:
--   1. plan の所有者 + 状態（generating）を再確認
--   2. 既存 plan_items を削除（リトライ冪等性のため）
--   3. 新規 plan_items を bulk INSERT
--   4. plans.status = 'succeeded' に遷移
--
-- p_items は JSONB の配列で、各要素は plan_items のカラムを key とする。
CREATE OR REPLACE FUNCTION finalize_plan(
    p_plan_id UUID,
    p_session_id UUID,
    p_items JSONB
) RETURNS VOID
LANGUAGE plpgsql
AS $$
DECLARE
    v_status TEXT;
BEGIN
    -- 所有者 + 状態の再確認。`FOR UPDATE` で plans 行を関数終了までロックして、
    -- 並行な mark_plan_failed / cleanup cron が割り込んで status を上書きするのを防ぐ。
    SELECT status INTO v_status
    FROM plans
    WHERE id = p_plan_id AND session_id = p_session_id
    FOR UPDATE;

    IF NOT FOUND OR v_status <> 'generating' THEN
        RAISE EXCEPTION 'plan % is not in generating state for session % (found=%, status=%)',
            p_plan_id, p_session_id, FOUND, v_status;
    END IF;

    -- 既存 plan_items を削除（リトライ時の重複を防ぐ）
    DELETE FROM plan_items WHERE plan_id = p_plan_id;

    -- 新規 plan_items を bulk INSERT
    INSERT INTO plan_items (
        id, plan_id, order_index, item_type, title, description,
        start_time, end_time,
        place_id, place_name, lat, lng, address,
        cost_jpy, cost_confidence, evidence, transit_to_next, notes
    )
    SELECT
        COALESCE((item->>'id')::UUID, gen_random_uuid()),
        p_plan_id,
        (item->>'order_index')::INTEGER,
        item->>'item_type',
        item->>'title',
        item->>'description',
        (item->>'start_time')::TIMESTAMPTZ,
        (item->>'end_time')::TIMESTAMPTZ,
        item->>'place_id',
        item->>'place_name',
        NULLIF(item->>'lat', '')::DOUBLE PRECISION,
        NULLIF(item->>'lng', '')::DOUBLE PRECISION,
        item->>'address',
        NULLIF(item->>'cost_jpy', '')::INTEGER,
        item->>'cost_confidence',
        item->'evidence',
        item->'transit_to_next',
        item->>'notes'
    FROM jsonb_array_elements(p_items) AS item;

    -- status を 'succeeded' に遷移
    UPDATE plans
    SET status = 'succeeded', updated_at = NOW()
    WHERE id = p_plan_id;
END;
$$;
