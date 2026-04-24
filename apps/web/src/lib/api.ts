/**
 * Flask API クライアント + Supabase 直接読み取り helper。
 *
 * - Flask 側（`/api/evidence/places` / `/api/plans/generate`）: JWT 認証必須。
 *   `getSupabaseAccessToken()` で匿名セッション JWT を付与する
 * - Supabase 直接読み取り（`plans` / `plan_items` / `participants`）: RLS で session_id スコープ
 *
 * モック戦略:
 *   `NEXT_PUBLIC_USE_MOCKS=1` の時は **fetch を一切走らせず** fixture を即 resolve する。
 *   `initialData` を使った裏 fetch 混在パターンは避ける（計画書 v3 の「モック戦略」節参照）。
 */

import type {
  EvidencePlacesResponse,
  GeneratePlanRequest,
  Plan,
  PlanGenerationPayload,
  PlanItem,
  Participant,
} from "shared-types";

import { getSupabaseAccessToken, getSupabaseClient } from "./supabase";
import { mockEvidencePlacesResponse } from "./mocks/evidencePlaces";
import { mockParticipants } from "./mocks/participants";
import { mockPlan } from "./mocks/plan";
import { mockPlanItems } from "./mocks/planItems";

const API_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:5000";
const USE_MOCKS = process.env.NEXT_PUBLIC_USE_MOCKS === "1";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public body?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function authedFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = await getSupabaseAccessToken();
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      ...(init.headers ?? {}),
    },
  });
  if (!res.ok) {
    let body: unknown = undefined;
    try {
      body = await res.json();
    } catch {
      /* body may not be JSON */
    }
    const message =
      (typeof body === "object" && body !== null && "error" in body
        ? String((body as { error?: unknown }).error)
        : null) ?? res.statusText;
    throw new ApiError(message, res.status, body);
  }
  return res.json() as Promise<T>;
}

// ==============================
// Flask API 呼び出し
// ==============================

export async function postEvidencePlaces(
  req: GeneratePlanRequest,
): Promise<EvidencePlacesResponse> {
  if (USE_MOCKS) {
    return mockEvidencePlacesResponse;
  }
  return authedFetch<EvidencePlacesResponse>("/api/evidence/places", {
    method: "POST",
    body: JSON.stringify(req),
  });
}

export async function postPlanGenerate(
  req: PlanGenerationPayload,
): Promise<{ plan_id: string | null }> {
  if (USE_MOCKS) {
    return { plan_id: req.plan_id };
  }
  return authedFetch<{ plan_id: string | null }>("/api/plans/generate", {
    method: "POST",
    body: JSON.stringify(req),
  });
}

// ==============================
// Supabase 直接読み取り（RLS 経由）
// ==============================

export async function getPlan(planId: string): Promise<Plan> {
  if (USE_MOCKS) {
    return { ...mockPlan, id: planId };
  }
  const client = getSupabaseClient();
  const { data, error } = await client
    .from("plans")
    .select("*")
    .eq("id", planId)
    .single();
  if (error) throw new ApiError(error.message, 500, error);
  return data as Plan;
}

export async function getPlanItems(planId: string): Promise<PlanItem[]> {
  if (USE_MOCKS) {
    return mockPlanItems.map((item) => ({ ...item, plan_id: planId }));
  }
  const client = getSupabaseClient();
  const { data, error } = await client
    .from("plan_items")
    .select("*")
    .eq("plan_id", planId)
    .order("order_index");
  if (error) throw new ApiError(error.message, 500, error);
  return data as PlanItem[];
}

export async function getParticipants(planId: string): Promise<Participant[]> {
  if (USE_MOCKS) {
    return mockParticipants.map((p) => ({ ...p, plan_id: planId }));
  }
  const client = getSupabaseClient();
  const { data, error } = await client
    .from("participants")
    .select("*")
    .eq("plan_id", planId)
    .order("order_index");
  if (error) throw new ApiError(error.message, 500, error);
  return data as Participant[];
}

// ==============================
// 1.5 submit で使う Supabase mutation
// ==============================

/**
 * フロントで発行した plan_id + participants を Supabase に INSERT する。
 * 成功時 `plans.status = 'draft'`（DDL デフォルト）。失敗時は呼び出し元が failed 更新 or エラー表示。
 *
 * USE_MOCKS 時は即 resolve し、Supabase 書き込みは走らない。
 */
export async function createPlanAndParticipants(args: {
  planId: string;
  sessionId: string;
  form: GeneratePlanRequest;
}): Promise<void> {
  if (USE_MOCKS) {
    return;
  }
  const client = getSupabaseClient();
  const { form, planId, sessionId } = args;

  const { error: planError } = await client.from("plans").insert({
    id: planId,
    session_id: sessionId,
    title: form.title,
    region: form.region,
    start_date: form.start_date,
    end_date: form.end_date,
    departure_point: form.departure_point,
    budget_per_person_jpy: form.budget_per_person_jpy,
    budget_breakdown: form.budget_breakdown,
    start_mode: form.start_mode,
    mode_payload: form.mode_payload,
    status: "draft",
  });
  if (planError) throw new ApiError(planError.message, 500, planError);

  if (form.participants.length > 0) {
    const { error: participantsError } = await client.from("participants").insert(
      form.participants.map((p) => ({
        plan_id: planId,
        display_name: p.display_name,
        avatar_color: p.avatar_color,
        wishes_text: p.wishes_text,
        tags: p.tags,
        order_index: p.order_index,
      })),
    );
    if (participantsError) {
      throw new ApiError(participantsError.message, 500, participantsError);
    }
  }
}

/**
 * `plans.status` を更新する。fire-and-forget で呼ばれることが多いので、呼び出し側で
 * `.catch(() => {})` して UI ブロックしないこと。
 */
export async function updatePlanStatus(
  planId: string,
  status: Plan["status"],
): Promise<void> {
  if (USE_MOCKS) return;
  const client = getSupabaseClient();
  const { error } = await client
    .from("plans")
    .update({ status })
    .eq("id", planId);
  if (error) throw new ApiError(error.message, 500, error);
}
