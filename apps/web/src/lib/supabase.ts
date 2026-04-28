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

/**
 * 匿名サインインを保証する。既にセッションがあればそれを返し、無ければ `signInAnonymously` する。
 * Flask API（`Authorization: Bearer ...`）呼び出し前に必ず実行する。
 *
 * Next.js SSR で呼ばれても落ちないように `typeof window` ガードは不要（Supabase client 自体が
 * localStorage にフォールバックする）。ただしサーバーコンポーネントから呼ぶと意味がないので、
 * 呼び出し側は `"use client"` を付けたコンポーネントに閉じ込める。
 */
export async function ensureAnonymousSession(): Promise<string> {
  const client = getSupabaseClient();
  const { data: sessionData } = await client.auth.getSession();
  if (sessionData.session?.access_token) {
    return sessionData.session.access_token;
  }
  const { data, error } = await client.auth.signInAnonymously();
  if (error || !data.session) {
    throw new Error(
      `Supabase 匿名サインイン失敗: ${error?.message ?? "unknown error"}`,
    );
  }
  return data.session.access_token;
}

/**
 * 現在の匿名セッションの JWT を取得する。未サインインなら `ensureAnonymousSession` でサインインする。
 * Flask API 呼び出しで `Authorization: Bearer <token>` として使う。
 */
export async function getSupabaseAccessToken(): Promise<string> {
  return ensureAnonymousSession();
}

/**
 * 現在のセッションの user.id（= session_id）を返す。未サインインなら null。
 * RLS のオーナーキーとして使う（plans.session_id に INSERT する値）。
 */
export async function getCurrentUserId(): Promise<string | null> {
  const client = getSupabaseClient();
  const { data } = await client.auth.getUser();
  return data.user?.id ?? null;
}
