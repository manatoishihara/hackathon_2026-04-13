-- =====================================================================
-- Routeful — 全マイグレーション統合ファイル
-- 適用順: 00 → 01 → 02 → 03 → 04 → 05 → 06(skip) → 07
-- 注意: pg_cron を使う 03 は Supabase Extensions で pg_cron を有効化してから実行
-- =====================================================================


-- =====================================================================
-- 00: 初期スキーマ（sessions / plans / participants / plan_items + RLS）
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Sessions（匿名セッション）
CREATE TABLE IF NOT EXISTS sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ DEFAULT NOW()
);

-- Plans（旅行プラン全体、status カラムは 02 で追加）
CREATE TABLE IF NOT EXISTS plans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    region TEXT NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    departure_point TEXT NOT NULL,
    budget_per_person_jpy INTEGER NOT NULL,
    budget_breakdown JSONB NOT NULL,
    start_mode TEXT NOT NULL CHECK (start_mode IN ('auto', 'anchor', 'theme')),
    mode_payload JSONB,
    share_token TEXT UNIQUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_plans_session_id ON plans(session_id);
CREATE INDEX IF NOT EXISTS idx_plans_share_token ON plans(share_token);

-- Participants（参加者 2〜5 人）
CREATE TABLE IF NOT EXISTS participants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id UUID NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
    display_name TEXT NOT NULL,
    avatar_color TEXT NOT NULL,
    wishes_text TEXT NOT NULL,
    tags TEXT[] DEFAULT '{}',
    order_index INTEGER NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_participants_plan_id ON participants(plan_id);

-- PlanItems（プランの各アイテム、時系列）
CREATE TABLE IF NOT EXISTS plan_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id UUID NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
    order_index INTEGER NOT NULL,
    item_type TEXT NOT NULL CHECK (item_type IN ('activity', 'meal', 'transit', 'lodging')),
    title TEXT NOT NULL,
    description TEXT,
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ NOT NULL,
    place_id TEXT,
    place_name TEXT,
    lat DOUBLE PRECISION,
    lng DOUBLE PRECISION,
    address TEXT,
    cost_jpy INTEGER,
    cost_confidence TEXT CHECK (cost_confidence IN ('verified', 'estimated', 'unknown')),
    evidence JSONB NOT NULL,
    transit_to_next JSONB,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_plan_items_plan_id ON plan_items(plan_id);
CREATE INDEX IF NOT EXISTS idx_plan_items_order ON plan_items(plan_id, order_index);

-- Row Level Security
ALTER TABLE sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE participants ENABLE ROW LEVEL SECURITY;
ALTER TABLE plan_items ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Own session only" ON sessions;
CREATE POLICY "Own session only" ON sessions
    FOR ALL USING (id = auth.uid());

DROP POLICY IF EXISTS "Plans of own session" ON plans;
CREATE POLICY "Plans of own session" ON plans
    FOR ALL USING (session_id = auth.uid());

DROP POLICY IF EXISTS "Participants of own plans" ON participants;
CREATE POLICY "Participants of own plans" ON participants
    FOR ALL USING (plan_id IN (SELECT id FROM plans WHERE session_id = auth.uid()));

DROP POLICY IF EXISTS "PlanItems of own plans" ON plan_items;
CREATE POLICY "PlanItems of own plans" ON plan_items
    FOR ALL USING (plan_id IN (SELECT id FROM plans WHERE session_id = auth.uid()));

-- 共有トークン経由の閲覧 view（Flask + service_role 経由採用のためオプション）
CREATE OR REPLACE VIEW shared_plans AS
    SELECT p.*
    FROM plans p
    WHERE p.share_token IS NOT NULL;


-- =====================================================================
-- 01: evidence_pack_sessions（/api/evidence/places の短期キャッシュ TTL 15 分）
-- =====================================================================

CREATE TABLE IF NOT EXISTS evidence_pack_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_session_id UUID NOT NULL,
    pack JSONB NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '15 minutes'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_evidence_pack_sessions_expires_at
    ON evidence_pack_sessions(expires_at);
CREATE INDEX IF NOT EXISTS idx_evidence_pack_sessions_owner
    ON evidence_pack_sessions(owner_session_id);

-- policy なし = anon 完全遮断、service_role のみ操作可
ALTER TABLE evidence_pack_sessions ENABLE ROW LEVEL SECURITY;


-- =====================================================================
-- 02: plans.status カラム追加（draft / generating / succeeded / failed）
-- =====================================================================

ALTER TABLE plans
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'draft';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'plans_status_check'
          AND conrelid = 'plans'::regclass
    ) THEN
        ALTER TABLE plans
            ADD CONSTRAINT plans_status_check
            CHECK (status IN ('draft', 'generating', 'succeeded', 'failed'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_plans_status ON plans(status);


-- =====================================================================
-- 03: 定期クリーンアップ cron（pg_cron）
-- 前提: Supabase Extensions で pg_cron を有効化してから実行すること
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS pg_cron;

DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'cleanup-evidence-pack-sessions') THEN
        PERFORM cron.unschedule('cleanup-evidence-pack-sessions');
    END IF;
    IF EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'cleanup-stuck-plans') THEN
        PERFORM cron.unschedule('cleanup-stuck-plans');
    END IF;
    IF EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'cleanup-abandoned-plans') THEN
        PERFORM cron.unschedule('cleanup-abandoned-plans');
    END IF;
END $$;

SELECT cron.schedule(
    'cleanup-evidence-pack-sessions',
    '0 * * * *',
    $$DELETE FROM evidence_pack_sessions WHERE expires_at < now()$$
);

SELECT cron.schedule(
    'cleanup-stuck-plans',
    '5 * * * *',
    $$DELETE FROM plans WHERE status = 'generating' AND updated_at < now() - INTERVAL '1 hour'$$
);

SELECT cron.schedule(
    'cleanup-abandoned-plans',
    '0 3 * * *',
    $$DELETE FROM plans WHERE status IN ('draft', 'failed') AND created_at < now() - INTERVAL '24 hours'$$
);


-- =====================================================================
-- 04: プラン生成の原子性保証 RPC 群
--     acquire_plan_generation_lock / mark_plan_failed / finalize_plan
-- =====================================================================

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

CREATE OR REPLACE FUNCTION acquire_plan_generation_lock(
    p_plan_id UUID,
    p_session_id UUID
) RETURNS plan_lock_result
LANGUAGE plpgsql
AS $$
DECLARE
    v_status TEXT;
BEGIN
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
    SELECT status INTO v_status
    FROM plans
    WHERE id = p_plan_id AND session_id = p_session_id
    FOR UPDATE;

    IF NOT FOUND OR v_status <> 'generating' THEN
        RAISE EXCEPTION 'plan % is not in generating state for session % (found=%, status=%)',
            p_plan_id, p_session_id, FOUND, v_status;
    END IF;

    DELETE FROM plan_items WHERE plan_id = p_plan_id;

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

    UPDATE plans
    SET status = 'succeeded', updated_at = NOW()
    WHERE id = p_plan_id;
END;
$$;


-- =====================================================================
-- 05: インデックス最適化（cron クリーンアップ + 共有閲覧 API 高速化）
-- =====================================================================

CREATE INDEX IF NOT EXISTS idx_plans_status_updated_at
    ON plans(status, updated_at);

CREATE INDEX IF NOT EXISTS idx_plans_status_created_at
    ON plans(status, created_at);

CREATE INDEX IF NOT EXISTS idx_participants_plan_order
    ON participants(plan_id, order_index);


-- =====================================================================
-- 07: 共有プラン一括取得 RPC get_shared_plan v2（最小カラム取得）
-- =====================================================================

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
