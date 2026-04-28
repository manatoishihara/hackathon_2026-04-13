-- Phase 0.2: 初期スキーマ（sessions / plans / participants / plan_items + RLS）
-- =====================================================================
-- 適用履歴: 本番 Supabase プロジェクトには 2026-04-01 頃に `docs/data-model.md`
-- の DDL を SQL Editor で手動実行済み（plans.status カラム追加前の初期形）。
-- plans.status 追加は 20260424_02_plans_status.sql で別途適用している。
--
-- 冪等設計:
--   CREATE TABLE / INDEX は IF NOT EXISTS。既存テーブル再定義は行わないので
--   本番に再適用しても破壊的変更は起きない（スキーマの drift がある場合は
--   本ファイルでは何もせず、別 migration で吸収する運用）。
--   RLS ENABLE は冪等。POLICY は DROP IF EXISTS → CREATE で「最新内容に揃える」
--   セマンティクスになる点だけ注意（意図した挙動）。
--   shared_plans VIEW は CREATE OR REPLACE で冪等。

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ==============================
-- Sessions（匿名セッション）
-- ==============================
CREATE TABLE IF NOT EXISTS sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ DEFAULT NOW()
);

-- ==============================
-- Plans（旅行プラン全体、status カラムは 20260424_02 で追加）
-- ==============================
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

-- ==============================
-- Participants（参加者 2〜5 人）
-- ==============================
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

-- ==============================
-- PlanItems（プランの各アイテム、時系列）
-- ==============================
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

-- ==============================
-- Row Level Security
-- ==============================
ALTER TABLE sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE participants ENABLE ROW LEVEL SECURITY;
ALTER TABLE plan_items ENABLE ROW LEVEL SECURITY;

-- POLICY は DROP → CREATE で最新内容に上書き（冪等）
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

-- ==============================
-- Shared Plans View（共有トークン経由の閲覧はこの view 経由、ただし Phase 1.9 の
-- 実装は Flask + service_role を採用したため、view の利用はオプション）
-- ==============================
CREATE OR REPLACE VIEW shared_plans AS
    SELECT p.*
    FROM plans p
    WHERE p.share_token IS NOT NULL;
