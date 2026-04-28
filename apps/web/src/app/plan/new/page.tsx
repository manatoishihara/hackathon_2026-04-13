"use client";

import { useRouter } from "next/navigation";
import { useState, useEffect } from "react";
import { useForm, Controller } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { ArrowRight, Spinner, WarningCircle, WifiSlash } from "@phosphor-icons/react/dist/ssr";

import type { StartMode } from "shared-types";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  checkApiHealth,
  createPlanAndParticipants,
  postEvidencePlaces,
  updatePlanStatus,
  ApiError,
} from "@/lib/api";
import { formatJpy } from "@/lib/format";
import {
  planFormSchema,
  type PlanFormValues,
} from "@/lib/schemas/planForm";
import { ensureAnonymousSession, getCurrentUserId } from "@/lib/supabase";
import { AnchorPicker } from "@/components/AnchorPicker";
import { BudgetBreakdownSlider } from "@/components/BudgetBreakdownSlider";
import { DateRangePicker } from "@/components/DateRangePicker";
import { ModeSelector } from "@/components/ModeSelector";
import { ParticipantTabs } from "@/components/ParticipantTabs";
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
type SubmitStep = "session" | "plan" | "evidence" | null;

function classifyError(err: unknown): { message: string; detail?: string } {
  // ネットワーク層エラー（DNS 解決失敗・接続拒否・タイムアウト）
  if (err instanceof TypeError && (err.message.includes("fetch") || err.message.includes("network") || err.message.includes("Failed to fetch"))) {
    return { message: "サーバーに接続できませんでした", detail: "インターネット接続またはサーバーの状態を確認してください。" };
  }
  if (err instanceof DOMException && err.name === "AbortError") {
    return { message: "接続がタイムアウトしました", detail: "サーバーの応答が遅い可能性があります。しばらくしてから再試行してください。" };
  }

  if (err instanceof ApiError) {
    // 422: LLM バリデーション失敗 or Evidence Pack 検証失敗
    if (err.status === 422) {
      return {
        message: "プラン生成の検証に失敗しました（422）",
        detail: "スポット情報の整合性チェックで問題が発生しました。しばらくしてから再試行してください。",
      };
    }
    // 429: レート制限
    if (err.status === 429) {
      return { message: "リクエストが集中しています（429）", detail: "少し時間をおいてから再試行してください。" };
    }
    // 401: セッション認証切れ
    if (err.status === 401) {
      return { message: "セッション認証エラー（401）", detail: "ページを再読み込みしてください。" };
    }
    // 403: API キー制限またはアクセス権限なし
    if (err.status === 403) {
      return { message: "アクセス権限エラー（403）", detail: "APIキーの制限または権限設定の問題の可能性があります。" };
    }
    // 404: Evidence Pack の有効期限切れなど
    if (err.status === 404) {
      return { message: "リソースが見つかりません（404）", detail: "セッションの有効期限が切れた可能性があります。最初からやり直してください。" };
    }
    // 502/503/504: ゲートウェイ・Render コールドスタート
    if (err.status === 502 || err.status === 503 || err.status === 504) {
      return {
        message: `APIサーバーが応答していません（${err.status}）`,
        detail: "Render のコールドスタート中の可能性があります。30秒ほど待ってから再試行してください。",
      };
    }
    // 500: サーバー内部エラー
    if (err.status === 500) {
      return { message: "サーバー内部エラー（500）", detail: err.message || "予期しないエラーが発生しました。" };
    }
    // その他のHTTPエラー
    return { message: `エラーが発生しました（${err.status}）`, detail: err.message };
  }

  if (err instanceof Error) {
    return { message: err.message };
  }
  return { message: "プラン生成の開始に失敗しました。" };
}

export default function NewPlanPage() {
  const router = useRouter();
  const setSession = useGenerationSessionStore((s) => s.setSession);
  const [activeParticipantIndex, setActiveParticipantIndex] = useState(0);
  const [submitError, setSubmitError] = useState<{ message: string; detail?: string } | null>(null);
  const [apiAvailable, setApiAvailable] = useState<boolean | null>(null);
  const [submitStep, setSubmitStep] = useState<SubmitStep>(null);

  useEffect(() => {
    checkApiHealth().then(setApiAvailable);
  }, []);

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

  const anchorIds =
    startMode === "anchor" &&
    watched.mode_payload &&
    "anchor_place_ids" in watched.mode_payload
      ? watched.mode_payload.anchor_place_ids
      : [];

  // 入力埋まり率（飛行機の進行に使う）
  // D 案 (2026-04-28): departure_point は demo スコープから外したので進捗計算からも除外。
  const baseFields: Array<string | undefined> = [
    watched.title,
    watched.region,
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
  const totalFields = 4 + 1 + participants.length * 2;
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
    setSubmitStep(null);
    let planId: string | null = null;
    try {
      // 1. 匿名サインイン（session_id を確定）
      setSubmitStep("session");
      await ensureAnonymousSession();
      const sessionId = await getCurrentUserId();
      if (!sessionId) {
        throw new Error("Supabase セッションの取得に失敗しました。");
      }

      // 2. plan_id 発行
      planId = crypto.randomUUID();

      // 3. plans + participants を INSERT
      setSubmitStep("plan");
      await createPlanAndParticipants({
        planId,
        sessionId,
        form: values,
      });

      // 4. /api/evidence/places
      setSubmitStep("evidence");
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
      setSubmitError(classifyError(err));
      setSubmitStep(null);
      if (planId) {
        void updatePlanStatus(planId, "failed").catch((e) => {
          console.warn("updatePlanStatus(failed) failed", e);
        });
      }
    }
  };

  const SUBMIT_STEP_LABELS: Record<NonNullable<SubmitStep>, string> = {
    session: "セッション確認中...",
    plan: "プランを保存中...",
    evidence: "スポット情報を取得中...",
  };

  const isApiChecking = apiAvailable === null;
  const isApiDown = apiAvailable === false;
  const canSubmit = !isSubmitting && !isApiDown && !isApiChecking;

  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col gap-10 px-6 py-12">
      {isApiChecking ? (
        <div className="flex items-center gap-3 rounded-lg border border-[color:var(--color-border)] bg-[color:var(--color-surface)] px-4 py-3 text-sm text-[color:var(--color-text-tertiary)]">
          <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent" />
          <span>サーバーの状態を確認中...</span>
        </div>
      ) : isApiDown ? (
        <div className="flex items-start gap-3 rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          <WifiSlash size={18} weight="bold" className="mt-0.5 shrink-0" />
          <span>
            APIサーバーが起動していません（コールドスタートの可能性）。30秒ほど待ってからページを再読み込みしてください。
          </span>
        </div>
      ) : null}

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
          <div className="flex flex-col gap-2 sm:col-span-2">
            <Label htmlFor="region">行き先エリア</Label>
            <Input
              id="region"
              placeholder="箱根"
              {...register("region")}
            />
          </div>
          <div className="sm:col-span-2">
            <DateRangePicker
              startDate={watched.start_date ?? ""}
              endDate={watched.end_date ?? ""}
              onStartChange={(v) => setValue("start_date", v, { shouldValidate: true, shouldDirty: true })}
              onEndChange={(v) => setValue("end_date", v, { shouldValidate: true, shouldDirty: true })}
              error={formState.errors.end_date?.message ?? formState.errors.start_date?.message}
            />
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
            予算配分
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
            モード
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
                  {formState.errors.mode_payload.message ?? "こだわりを 1 件以上指定してください"}
                </p>
              ) : null}
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
          <div className="rounded-md border border-[color:var(--color-danger)]/40 bg-[color:var(--color-danger)]/5 p-4 text-sm leading-relaxed">
            <div className="flex items-start gap-3 font-medium text-[color:var(--color-danger)]">
              <WarningCircle size={18} weight="bold" className="mt-0.5 shrink-0" />
              <span>{submitError.message}</span>
            </div>
            {submitError.detail ? (
              <p className="mt-1.5 pl-7 text-[color:var(--color-text-secondary)]">
                {submitError.detail}
              </p>
            ) : null}
          </div>
        ) : null}

        <div className="flex items-center justify-end gap-3 pt-2">
          <button
            type="submit"
            disabled={!canSubmit}
            aria-busy={isSubmitting}
            className="inline-flex items-center gap-2 rounded-full bg-[color:var(--color-primary)] px-7 py-3.5 text-base font-medium text-[color:var(--color-background)] shadow-[0_8px_24px_rgba(4,44,83,0.18)] transition hover:opacity-90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--color-primary)] disabled:cursor-not-allowed disabled:opacity-40"
          >
            {isSubmitting ? (
              <>
                <Spinner size={18} weight="bold" className="animate-spin" />
                {submitStep ? SUBMIT_STEP_LABELS[submitStep] : "生成を開始中..."}
              </>
            ) : isApiDown ? (
              <>
                <WifiSlash size={18} weight="bold" />
                APIサーバーに接続できません
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
