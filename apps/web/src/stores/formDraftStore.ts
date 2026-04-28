import { create } from "zustand";
import type { PlanFormValues } from "@/lib/schemas/planForm";

export type FormError = { message: string; detail?: string };

export type FormDraft = {
  values: PlanFormValues;
  error: FormError | null;
  savedAt: number;
};

export const DRAFT_TTL_MS = 30 * 60 * 1000;

type State = {
  draft: FormDraft | null;
  saveDraft: (values: PlanFormValues, error?: FormError | null) => void;
  setDraftError: (error: FormError | null) => void;
  clearDraft: () => void;
};

export const useFormDraftStore = create<State>((set, get) => ({
  draft: null,
  saveDraft: (values, error) =>
    set({ draft: { values, error: error ?? null, savedAt: Date.now() } }),
  setDraftError: (error) => {
    const current = get().draft;
    if (!current) return;
    set({ draft: { ...current, error, savedAt: Date.now() } });
  },
  clearDraft: () => set({ draft: null }),
}));

export function getActiveDraft(): FormDraft | null {
  const draft = useFormDraftStore.getState().draft;
  if (!draft) return null;
  if (Date.now() - draft.savedAt > DRAFT_TTL_MS) {
    useFormDraftStore.getState().clearDraft();
    return null;
  }
  return draft;
}
