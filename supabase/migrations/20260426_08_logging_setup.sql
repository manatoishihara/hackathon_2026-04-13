-- Phase 1.x DB-8: Supabase Row-Level Logging / クエリ統計観測基盤
-- =====================================================================
-- 目的:
--   plan_items INSERT / plans UPDATE / RPC 呼び出しが本番で増えてきたため、
--   スロークエリの検出と統計取得を有効化する。
--
-- 内容:
--   1. pg_stat_statements 拡張を有効化（クエリ別の実行回数・時間を追跡）
--   2. 統計観測用ビューを作成（Supabase ダッシュボードから確認しやすい形）
--   3. pg_stat_statements リセット関数（計測区間をリセットしたいときに手動実行）
--
-- 適用手順:
--   Supabase SQL Editor で本ファイルを実行する。
--   pg_stat_statements は Supabase Free プランでも利用可能。
--
-- 冪等性: CREATE EXTENSION IF NOT EXISTS / CREATE OR REPLACE VIEW

-- ==============================
-- 1. pg_stat_statements 有効化
-- ==============================
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

-- ==============================
-- 2. Routeful 主要テーブルのクエリ統計ビュー
--    Supabase SQL Editor で `SELECT * FROM routeful_query_stats;` で確認可能
-- ==============================
CREATE OR REPLACE VIEW routeful_query_stats AS
SELECT
    left(query, 120)                          AS query_preview,
    calls,
    round(total_exec_time::numeric, 2)        AS total_ms,
    round(mean_exec_time::numeric, 2)         AS mean_ms,
    round(stddev_exec_time::numeric, 2)       AS stddev_ms,
    rows
FROM pg_stat_statements
WHERE
    -- Routeful 主要テーブルに関するクエリのみ絞り込む
    query ILIKE ANY (ARRAY[
        '%plans%',
        '%plan_items%',
        '%participants%',
        '%evidence_pack_sessions%',
        '%finalize_plan%',
        '%acquire_plan_generation_lock%',
        '%get_shared_plan%'
    ])
ORDER BY total_exec_time DESC
LIMIT 50;

-- ==============================
-- 3. スロークエリ確認ビュー（mean_exec_time > 100ms）
-- ==============================
CREATE OR REPLACE VIEW routeful_slow_queries AS
SELECT
    left(query, 120)                          AS query_preview,
    calls,
    round(mean_exec_time::numeric, 2)         AS mean_ms,
    round(max_exec_time::numeric, 2)          AS max_ms,
    rows
FROM pg_stat_statements
WHERE
    mean_exec_time > 100
    AND query ILIKE ANY (ARRAY[
        '%plans%',
        '%plan_items%',
        '%participants%',
        '%evidence_pack_sessions%',
        '%finalize_plan%',
        '%acquire_plan_generation_lock%',
        '%get_shared_plan%'
    ])
ORDER BY mean_exec_time DESC
LIMIT 20;

-- ==============================
-- 4. 統計リセット（計測区間を区切りたいときに手動実行）
--    例: デプロイ後に `SELECT reset_routeful_query_stats();` で計測開始
-- ==============================
CREATE OR REPLACE FUNCTION reset_routeful_query_stats()
RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM pg_stat_statements_reset();
END;
$$;
