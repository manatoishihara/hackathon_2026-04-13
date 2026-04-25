-- Phase 1.x: インデックス最適化
-- =====================================================================
-- 背景:
--   既存インデックスは単一カラムが中心で、以下の複合条件クエリが
--   フルテーブルスキャン（Seq Scan）になっていた。
--
-- 追加する 3 インデックス:
--
--   [1] plans(status, updated_at)
--       対象クエリ: cron cleanup-stuck-plans
--         DELETE FROM plans
--         WHERE status = 'generating'
--           AND updated_at < now() - INTERVAL '1 hour'
--       既存 idx_plans_status(status 単独) では status フィルタ後に
--       updated_at を再評価するためのソートコストが残る。
--       複合インデックスで status + updated_at を 1 回の B-tree 走査で解決する。
--
--   [2] plans(status, created_at)
--       対象クエリ: cron cleanup-abandoned-plans
--         DELETE FROM plans
--         WHERE status IN ('draft', 'failed')
--           AND created_at < now() - INTERVAL '24 hours'
--       同様に status 後の created_at フィルタを複合インデックスで高速化。
--       status IN ('draft','failed') は OR 相当だが、PostgreSQL は
--       Index Scan で status = 'draft' + status = 'failed' を
--       それぞれ B-tree で走査して Bitmap OR で結合する。
--
--   [3] participants(plan_id, order_index)
--       対象クエリ: DB-5 共有閲覧 API
--         SELECT ... FROM participants
--         WHERE plan_id = :id
--         ORDER BY order_index
--       既存 idx_participants_plan_id(plan_id 単独) では ORDER BY のために
--       PostgreSQL がソートステップを追加する。複合インデックスにすることで
--       plan_id で絞り込みつつ order_index 順が保証されたリーフを走査でき、
--       Sort ステップを排除して Index Only Scan に昇格できる。
--       plan_items には idx_plan_items_order(plan_id, order_index) が既にあり、
--       participants も同じパターンで揃える。
--
-- 冪等性: CREATE INDEX IF NOT EXISTS
-- 適用手順: Supabase SQL Editor で本ファイルを実行する（既存データへの破壊なし）

-- ==============================
-- [1] cron stuck-plans クリーンアップ高速化
-- ==============================
CREATE INDEX IF NOT EXISTS idx_plans_status_updated_at
    ON plans(status, updated_at);

-- ==============================
-- [2] cron abandoned-plans クリーンアップ高速化
-- ==============================
CREATE INDEX IF NOT EXISTS idx_plans_status_created_at
    ON plans(status, created_at);

-- ==============================
-- [3] 共有閲覧 API (DB-5) の ORDER BY 排除
-- ==============================
CREATE INDEX IF NOT EXISTS idx_participants_plan_order
    ON participants(plan_id, order_index);
