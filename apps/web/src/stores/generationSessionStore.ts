import { create } from "zustand";
import type { EvidencePlacesPlaceSummary } from "shared-types";

/**
 * 1.5 submit → 1.6 生成中 → 1.7 プラン閲覧 の**ルート跨ぎ一時 state**。
 *
 * フォームそのものは react-hook-form で管理する（この store には入れない）。
 * サーバー状態（plan / plan_items）は TanStack Query。責務分離（計画書 v3 参照）。
 *
 * TTL 15 分: evidence_pack_sessions の DB 側 TTL と揃える。ブラウザリロードで消える
 * （localStorage 永続化しない）ので、中断したらフォームから再入力させる。
 */
export type GenerationSession = {
  plan_id: string;
  evidence_pack_id: string;
  places: EvidencePlacesPlaceSummary[];
  createdAt: number;
};

type State = {
  session: GenerationSession | null;
  setSession: (session: GenerationSession) => void;
  clearSession: () => void;
};

export const SESSION_TTL_MS = 15 * 60 * 1000;

export const useGenerationSessionStore = create<State>((set) => ({
  session: null,
  setSession: (session) => set({ session }),
  clearSession: () => set({ session: null }),
}));

/**
 * 15 分以内の生きたセッションがあれば返し、無ければ null。
 * 1.6 の mount 時に呼んで、null なら 1.5 にリダイレクトする。
 */
export function getActiveSession(): GenerationSession | null {
  const session = useGenerationSessionStore.getState().session;
  if (!session) return null;
  if (Date.now() - session.createdAt > SESSION_TTL_MS) return null;
  return session;
}
