-- Phase 1.3d DB-3: 定期クリーンアップ cron（pg_cron）
-- ====================================================
-- 目的:
--   1. evidence_pack_sessions: 期限切れ (expires_at < now) を 1 時間毎に削除
--   2. plans (generating のまま stuck): updated_at から 1 時間超の generating を削除
--      → Flask 側の finalize_plan RpcTransportError（commit 不明）経路の救済
--   3. plans (draft/failed で 24h 放置): 1 日毎に削除（plan_items / participants は CASCADE）
--      `succeeded` は絶対に削除しない（ユーザの成果物）
--
-- 適用手順:
--   1. Supabase ダッシュボード > Database > Extensions で `pg_cron` を有効化しておく
--   2. 本ファイルを Supabase SQL Editor で実行
--
-- 冪等性:
--   既存 job があれば `cron.unschedule` で外してから再 `cron.schedule`。複数回実行しても安全。

CREATE EXTENSION IF NOT EXISTS pg_cron;

-- 既存ジョブを一旦 unschedule（再実行時の重複登録を防ぐ）
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

-- evidence_pack_sessions の期限切れを 1 時間毎に削除
SELECT cron.schedule(
    'cleanup-evidence-pack-sessions',
    '0 * * * *',
    $$DELETE FROM evidence_pack_sessions WHERE expires_at < now()$$
);

-- plans が generating のまま stuck（通信失敗 / ユーザ離脱後に残存）→ 1 時間後に削除。
-- LLM 生成は通常 60 秒以内完了、150 秒 deadline なので 1 時間のマージンは十分過剰。
-- 実行時刻を :05 にずらして evidence_pack cleanup と同じ分に集中しないように。
SELECT cron.schedule(
    'cleanup-stuck-plans',
    '5 * * * *',
    $$DELETE FROM plans WHERE status = 'generating' AND updated_at < now() - INTERVAL '1 hour'$$
);

-- plans が draft / failed で 24 時間放置 → 1 日毎 03:00 に削除（plan_items / participants は CASCADE）。
-- `succeeded` はユーザの成果物として保全する（削除条件に含めない）。
SELECT cron.schedule(
    'cleanup-abandoned-plans',
    '0 3 * * *',
    $$DELETE FROM plans WHERE status IN ('draft', 'failed') AND created_at < now() - INTERVAL '24 hours'$$
);
