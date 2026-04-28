-- Phase 1.3c+: plans テーブルに status カラムを追加（draft / generating / succeeded / failed）
-- =====================================================================
-- 適用履歴: 本番 Supabase プロジェクトには 2026-04-24 頃に手動で適用済み。
--
-- 背景: /api/plans/generate の排他制御と UI 側の進行状態表示のため plans.status
-- を導入。
--   draft      → 1.5 submit 直後（plan を INSERT した時点の default）
--   generating → /api/evidence/places 成功後、フロントが UPDATE
--   succeeded  → Phase 1.3d の finalize_plan RPC が遷移
--   failed     → /api/evidence/places 失敗時 or /api/plans/generate 失敗時
--
-- 冪等設計:
--   ADD COLUMN IF NOT EXISTS (PostgreSQL 9.6+)。既存カラムがあれば何もしない。
--   CHECK 制約は pg_constraint を参照して重複追加を回避。
--   CREATE INDEX IF NOT EXISTS。

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
