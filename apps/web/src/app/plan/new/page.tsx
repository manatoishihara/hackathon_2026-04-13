"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm, Controller } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { ArrowRight, Spinner } from "@phosphor-icons/react/dist/ssr";

import type { StartMode } from "shared-types";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  createPlanAndParticipants,
  postEvidencePlaces,
  updatePlanStatus,
} from "@/lib/api";
import { formatJpy } from "@/lib/format";
import {
  planFormSchema,
  type PlanFormValues,
  type ThemeKey,
} from "@/lib/schemas/planForm";
import { ensureAnonymousSession, getCurrentUserId } from "@/lib/supabase";
import { AnchorPicker } from "@/components/AnchorPicker";
import { BudgetBreakdownSlider } from "@/components/BudgetBreakdownSlider";
import { ModeSelector } from "@/components/ModeSelector";
import { ParticipantTabs } from "@/components/ParticipantTabs";
import { ThemePicker } from "@/components/ThemePicker";
import { StepProgressRunway } from "@/components/plan-new/StepProgressRunway";
import { useGenerationSessionStore } from "@/stores/generationSessionStore";

// blue hour 配色（5 人を区別する色パレット、どれもブランドトーンに沿う）
const PARTICIPANT_COLORS = [
  "#042C53", // Deep Navy
  "#F0997B", // Coral
  "#2C5F5D", // Deep Teal
  "#3C5B8F", // Blue Gray
  "#C49C82", // Sand Coral
];

const DEFAULT_VALUES: PlanFormValues = {
  title: "",
  region: "",
  start_date: "",
  end_date: "",
  departure_point: "",
  budget_per_person_jpy: 30000,
  budget_breakdown: { lodging: 40, meal: 30, activity: 20, transit: 10 },
  start_mode: "auto",
  mode_payload: null,
  participants: [
    {
      display_name: "",
      avatar_color: PARTICIPANT_COLORS[0],
      wishes_text: "",
      tags: [],
      order_index: 0,
    },
    {
      display_name: "",
      avatar_color: PARTICIPANT_COLORS[1],
      wishes_text: "",
      tags: [],
      order_index: 1,
    },
  ],
};

/**
 * 1.5 希望入力画面 (04)。
 *
 * submit 時の流れ（計画書 v3「生成フロー契約」と 1 対 1 対応）:
 *   1. 匿名サインイン → user.id を plan.session_id として使う
 *   2. crypto.randomUUID() で plan_id 発行
 *   3. plans + participants を INSERT（plan.status = 'draft'）
 *   4. /api/evidence/places 呼び出し
 *      - 成功時: plans.status は 'draft' のまま、サーバ側 acquire_plan_generation_lock RPC が
 *        compare-and-set で 'draft' → 'generating' に遷移する（Phase 1.3d 設計）
 *      - 失敗時: plans.status = 'failed' に更新、エラー表示
 *   5. generationSessionStore にセッションを stash
 *   6. /plan/<plan_id>/generating に遷移
 *
 * デザイナーは className / 余白 / 入力 UX の調整をしてよい。
 * ロジック（submit 手順・API 呼び出し順）は触らない。
 */
export default function NewPlanPage() {
  const router = useRouter();
  const setSession = useGenerationSessionStore((s) => s.setSession);
  const [activeParticipantIndex, setActiveParticipantIndex] = useState(0);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const form = useForm<PlanFormValues>({
    resolver: zodResolver(planFormSchema),
    defaultValues: DEFAULT_VALUES,
  });
  const { control, register, handleSubmit, watch, setValue, clearErrors, formState } = form;
  const participants = watch("participants");
  const watched = watch();
  const isSubmitting = formState.isSubmitting;
  const startMode = watched.start_mode;

  // Phase 2.1: mode 切替時に mode_payload も対応する形にリセットする。
  // discriminated union なので start_mode と mode_payload は常にペアで一貫させる必要がある。
  // 旧 mode で残った mode_payload エラーは clearErrors で即時除去（Codex Minor 3 対応）。
  const handleModeChange = (next: StartMode) => {
    setValue("start_mode", next, { shouldDirty: true });
    if (next === "auto") {
      setValue("mode_payload", null, { shouldDirty: true });
    } else if (next === "anchor") {
      setValue(
        "mode_payload",
        { anchor_place_ids: [] },
        { shouldDirty: true },
      );
    } else if (next === "theme") {
      setValue(
        "mode_payload",
        { theme: "onsen" },
        { shouldDirty: true },
      );
    }
    clearErrors("mode_payload");
  };

  const handleAnchorChange = (placeIds: string[]) => {
    setValue(
      "mode_payload",
      { anchor_place_ids: placeIds },
      { shouldDirty: true, shouldValidate: true },
    );
  };

  const handleThemeChange = (theme: ThemeKey | null) => {
    if (theme === null) {
      // 選択解除 → auto モードに戻す（discriminated union を壊さない安全側）
      handleModeChange("auto");
      return;
    }
    setValue(
      "mode_payload",
      { theme },
      { shouldDirty: true, shouldValidate: true },
    );
  };

  const anchorIds =
    startMode === "anchor" &&
    watched.mode_payload &&
    "anchor_place_ids" in watched.mode_payload
      ? watched.mode_payload.anchor_place_ids
      : [];
  const currentTheme: ThemeKey | null =
    startMode === "theme" &&
    watched.mode_payload &&
    "theme" in watched.mode_payload
      ? watched.mode_payload.theme
      : null;

  // 入力埋まり率（飛行機の進行に使う）
  const baseFields: Array<string | undefined> = [
    watched.title,
    watched.region,
    watched.departure_point,
    watched.start_date,
    watched.end_date,
  ];
  const baseFilled = baseFields.filter(
    (v) => typeof v === "string" && v.trim().length > 0,
  ).length;
  const budgetFilled = (watched.budget_per_person_jpy ?? 0) > 0 ? 1 : 0;
  const participantFilled = participants.reduce(
    (sum, p) =>
      sum +
      (p.display_name?.trim() ? 1 : 0) +
      (p.wishes_text?.trim() ? 1 : 0),
    0,
  );
  const totalFields = 5 + 1 + participants.length * 2;
  const progress = (baseFilled + budgetFilled + participantFilled) / totalFields;

  const handleAddParticipant = () => {
    if (participants.length >= 5) return;
    const nextIndex = participants.length;
    const color = PARTICIPANT_COLORS[nextIndex % PARTICIPANT_COLORS.length];
    setValue("participants", [
      ...participants,
      {
        display_name: "",
        avatar_color: color,
        wishes_text: "",
        tags: [],
        order_index: nextIndex,
      },
    ]);
    setActiveParticipantIndex(nextIndex);
  };

  const handleRemoveParticipant = (index: number) => {
    if (participants.length <= 2) return;
    const next = participants
      .filter((_, i) => i !== index)
      .map((p, i) => ({ ...p, order_index: i }));
    setValue("participants", next);
    setActiveParticipantIndex(Math.min(activeParticipantIndex, next.length - 1));
  };

  const onSubmit = async (values: PlanFormValues) => {
    setSubmitError(null);
    let planId: string | null = null;
    try {
      // 1. 匿名サインイン（session_id を確定）
      await ensureAnonymousSession();
      const sessionId = await getCurrentUserId();
      if (!sessionId) {
        throw new Error("Supabase セッションの取得に失敗しました。");
      }

      // 2. plan_id 発行
      planId = crypto.randomUUID();

      // 3. plans + participants を INSERT
      await createPlanAndParticipants({
        planId,
        sessionId,
        form: values,
      });

      // 4. /api/evidence/places
      const evidenceResponse = await postEvidencePlaces(values);

      // 注: status は 'draft' のまま維持。サーバ側 acquire_plan_generation_lock RPC が
      // 'draft' or 'failed' のときだけ 'generating' に compare-and-set で遷移する設計。
      // フロントが先に 'generating' に書き換えると、acquire_lock が already_generating を
      // 返して 409 になる（2026-04-26 本番 E2E Run 6 で実証）。

      // 5. Zustand stash
      setSession({
        plan_id: planId,
        evidence_pack_id: evidenceResponse.evidence_pack_id,
        places: evidenceResponse.places,
        createdAt: Date.now(),
      });

      // 6. 遷移
      router.push(`/plan/${planId}/generating`);
    } catch (err) {
      const message = err instanceof Error ? err.message : "プラン生成の開始に失敗しました。";
      setSubmitError(message);
      if (planId) {
        void updatePlanStatus(planId, "failed").catch((e) => {
          console.warn("updatePlanStatus(failed) failed", e);
        });
      }
    }
  };

  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col gap-10 px-6 py-12">
      <header className="flex flex-col gap-6">
        <StepProgressRunway progress={progress} isSubmitting={isSubmitting} />
        <div className="flex flex-col gap-3">
          <h1 className="font-heading text-3xl leading-[1.4] text-[color:var(--color-text-primary)] sm:text-4xl lg:text-[40px]">
            どこへ、誰と、どんな旅にしますか？
          </h1>
          <p className="max-w-xl text-sm leading-[1.85] text-[color:var(--color-text-primary)] opacity-80">
            参加者 2〜5 人の希望と予算配分を入力してください。LLM がその場で合意案を組み立てます。
          </p>
        </div>
      </header>

      <form className="flex flex-col gap-8" onSubmit={handleSubmit(onSubmit)}>
        <section className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="flex flex-col gap-2 sm:col-span-2">
            <Label htmlFor="title">プランのタイトル</Label>
            <Input
              id="title"
              placeholder="箱根で温泉と自然を満喫する 2 日間"
              maxLength={60}
              {...register("title")}
            />
            {formState.errors.title ? (
              <p className="flex items-start gap-2 border-l-2 border-[color:var(--color-accent)] pl-2 text-xs leading-relaxed text-[color:var(--color-text-primary)]">
                {formState.errors.title.message}
              </p>
            ) : null}
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="region">行き先エリア</Label>
            <Input
              id="region"
              placeholder="箱根"
              {...register("region")}
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="departure_point">出発地</Label>
            <Input
              id="departure_point"
              placeholder="新宿駅"
              {...register("departure_point")}
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="start_date">開始日</Label>
            <Input id="start_date" type="date" {...register("start_date")} />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="end_date">終了日</Label>
            <Input id="end_date" type="date" {...register("end_date")} />
            {formState.errors.end_date ? (
              <p className="flex items-start gap-2 border-l-2 border-[color:var(--color-accent)] pl-2 text-xs leading-relaxed text-[color:var(--color-text-primary)]">
                {formState.errors.end_date.message}
              </p>
            ) : null}
          </div>
          <div className="flex flex-col gap-3 sm:col-span-2">
            <div className="flex items-baseline justify-between">
              <Label htmlFor="budget_per_person_jpy">1 人あたり予算</Label>
              <span className="font-mono text-xl tabular-nums text-[color:var(--color-primary)]">
                {formatJpy(watched.budget_per_person_jpy ?? 0)}
              </span>
            </div>
            <Input
              id="budget_per_person_jpy"
              type="number"
              min={1000}
              max={1_000_000}
              step={1000}
              {...register("budget_per_person_jpy", { valueAsNumber: true })}
            />
            <div className="flex flex-wrap gap-2">
              {[10000, 20000, 30000, 50000, 100000].map((amount) => {
                const active = watched.budget_per_person_jpy === amount;
                return (
                  <button
                    type="button"
                    key={amount}
                    onClick={() =>
                      setValue("budget_per_person_jpy", amount, {
                        shouldValidate: true,
                        shouldDirty: true,
                      })
                    }
                    className={`rounded-full px-4 py-1.5 text-xs font-medium transition-colors ${
                      active
                        ? "bg-[color:var(--color-primary)] text-[color:var(--color-background)]"
                        : "border border-[color:var(--color-border)] bg-[color:var(--color-surface)] text-[color:var(--color-text-secondary)] hover:border-[color:var(--color-primary)] hover:text-[color:var(--color-primary)]"
                    }`}
                  >
                    {formatJpy(amount)}
                  </button>
                );
              })}
            </div>
          </div>
        </section>

        <section className="flex flex-col gap-3">
          <h2 className="text-sm font-semibold text-[color:var(--color-text-secondary)]">
            予算配分（合計 100%）
          </h2>
          <Controller
            control={control}
            name="budget_breakdown"
            render={({ field }) => (
              <BudgetBreakdownSlider value={field.value} onChange={field.onChange} />
            )}
          />
          {formState.errors.budget_breakdown ? (
            <p className="text-xs text-[color:var(--color-danger)]">
              {formState.errors.budget_breakdown.message ??
                "配分が 100% になるように調整してください"}
            </p>
          ) : null}
        </section>

        <section className="flex flex-col gap-3">
          <h2
            id="start-mode-heading"
            className="text-sm font-semibold text-[color:var(--color-text-secondary)]"
          >
            出発モード
          </h2>
          <ModeSelector
            value={startMode}
            onChange={handleModeChange}
            ariaLabelledBy="start-mode-heading"
          />

          {startMode === "anchor" ? (
            <div className="mt-2 rounded-lg border border-[color:var(--color-border)] bg-[color:var(--color-surface)] p-4">
              <AnchorPicker value={anchorIds} onChange={handleAnchorChange} />
              {formState.errors.mode_payload ? (
                <p className="mt-2 text-xs text-[color:var(--color-danger)]">
                  {formState.errors.mode_payload.message ?? "アンカーを 1 件以上指定してください"}
                </p>
              ) : null}
            </div>
          ) : null}

          {startMode === "theme" ? (
            <div className="mt-2 rounded-lg border border-[color:var(--color-border)] bg-[color:var(--color-surface)] p-4">
              <ThemePicker value={currentTheme} onChange={handleThemeChange} />
            </div>
          ) : null}
        </section>

        <section className="flex flex-col gap-3">
          <h2 className="text-sm font-semibold text-[color:var(--color-text-secondary)]">
            参加者（2〜5 人）
          </h2>
          <Controller
            control={control}
            name="participants"
            render={({ field }) => (
              <ParticipantTabs
                participants={field.value}
                activeIndex={activeParticipantIndex}
                onActiveChange={setActiveParticipantIndex}
                onParticipantChange={(i, next) =>
                  field.onChange(field.value.map((p, idx) => (idx === i ? next : p)))
                }
                onAddParticipant={handleAddParticipant}
                onRemoveParticipant={handleRemoveParticipant}
                onAddTag={(i, tag) =>
                  field.onChange(
                    field.value.map((p, idx) =>
                      idx === i && !p.tags.includes(tag)
                        ? { ...p, tags: [...p.tags, tag] }
                        : p,
                    ),
                  )
                }
                onRemoveTag={(i, tag) =>
                  field.onChange(
                    field.value.map((p, idx) =>
                      idx === i ? { ...p, tags: p.tags.filter((t) => t !== tag) } : p,
                    ),
                  )
                }
              />
            )}
          />
        </section>

        {submitError ? (
          <div className="rounded-md border border-[color:var(--color-danger)]/40 bg-[color:var(--color-danger)]/5 p-4 text-sm leading-relaxed text-[color:var(--color-danger)]">
            {submitError}
          </div>
        ) : null}

        <div className="flex items-center justify-end gap-3 pt-2">
          <button
            type="submit"
            disabled={isSubmitting}
            className="inline-flex items-center gap-2 rounded-full bg-[color:var(--color-primary)] px-7 py-3.5 text-base font-medium text-[color:var(--color-background)] shadow-[0_8px_24px_rgba(4,44,83,0.18)] transition hover:opacity-90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--color-primary)] disabled:cursor-not-allowed disabled:opacity-40"
          >
            {isSubmitting ? (
              <>
                <Spinner size={18} weight="bold" className="animate-spin" />
                生成を開始中...
              </>
            ) : (
              <>
                プランを生成
                <ArrowRight size={18} weight="bold" />
              </>
            )}
          </button>
        </div>
      </form>
    </main>
  );
}
