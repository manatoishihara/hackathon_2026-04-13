-- Phase 1.3a: /api/evidence/places の短期キャッシュ（TTL 15 分）
-- =====================================================================
-- 適用履歴: 本番 Supabase プロジェクトには 2026-04-19 頃に手動で適用済み。
--
-- 方針: RLS は有効化するが **policy は一切定義しない**。
--   → anon / authenticated から完全遮断、service_role だけが読み書きできる。
--   → Flask が pack を格納し、generate リクエストで取り出す設計（詳細は
--     `apps/api/src/evidence/cache.py`）。
--
-- 冪等設計: CREATE TABLE / INDEX は IF NOT EXISTS、ALTER ... ENABLE RLS は冪等。

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

ALTER TABLE evidence_pack_sessions ENABLE ROW LEVEL SECURITY;
-- 本テーブルに policy を付けないことで anon からの SELECT / INSERT / UPDATE / DELETE を
-- すべて拒否する（`apps/api/tests/test_rls.py::test_anon_client_cannot_*_evidence_pack_sessions`
-- で検証済み）。将来 policy を追加する場合は Flask の service_role 経路と互換を検討すること。
