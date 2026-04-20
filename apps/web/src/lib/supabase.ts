import { createClient, type SupabaseClient } from "@supabase/supabase-js";

let cachedClient: SupabaseClient | null = null;

/**
 * ブラウザ / Next.js 側で使う Supabase クライアントを返す。
 * 匿名認証 (signInAnonymously) を前提とし、RLS を経由してユーザースコープで操作する。
 *
 * service_role キーは絶対にここで使わない（サーバー側 `apps/api/src/supabase_client.py`）。
 */
export function getSupabaseClient(): SupabaseClient {
  if (cachedClient) return cachedClient;

  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

  if (!url || !anonKey) {
    throw new Error(
      "Supabase env vars が未設定です。`.env.local` に NEXT_PUBLIC_SUPABASE_URL と NEXT_PUBLIC_SUPABASE_ANON_KEY を設定してください。",
    );
  }

  cachedClient = createClient(url, anonKey);
  return cachedClient;
}
