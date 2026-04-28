-- Phase 1.10 デプロイ後の本番 E2E で発覚: anon サインインだけでは public.sessions に
-- 行が無く、plans.session_id (FK -> sessions.id) で 23503 (foreign_key_violation)
-- → HTTP 409 (Conflict) が返って submit 失敗していた。
-- =====================================================================
-- 真因:
--   フロントが /plan/new submit で `INSERT INTO plans (id, session_id=auth.uid(), ...)`
--   を実行するが、Supabase の anon サインインは auth.users にだけ行を作る。
--   public.sessions は別テーブルなので、紐づく行が無い → FK 違反。
--
--   test_routes_plans.py の "RLS 42501" 失敗も、test 環境では FK より先に
--   RLS WITH CHECK が評価されるか何かのタイミングで違うエラーとして観測されていた
--   (同根の問題、別の表面化)。
--
-- 対処:
--   (1) auth.users INSERT トリガで public.sessions にも mirror 行を自動作成
--   (2) 既存 auth.users 全員を backfill (一回限りの SELECT INSERT)
--
-- 冪等性:
--   CREATE OR REPLACE FUNCTION / DROP TRIGGER IF EXISTS / ON CONFLICT DO NOTHING
--   ですべて idempotent。複数回適用しても破壊なし。

-- ==============================
-- (1) トリガ: auth.users insert -> public.sessions insert
-- ==============================
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    INSERT INTO public.sessions (id) VALUES (NEW.id) ON CONFLICT DO NOTHING;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

-- ==============================
-- (2) 既存 auth.users の backfill
-- ==============================
INSERT INTO public.sessions (id)
SELECT id FROM auth.users
ON CONFLICT DO NOTHING;
