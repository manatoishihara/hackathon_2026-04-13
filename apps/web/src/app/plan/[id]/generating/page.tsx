"use client";

import { useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { Spinner, WarningCircle, CheckCircle } from "@phosphor-icons/react/dist/ssr";

import { postPlanGenerate, updatePlanStatus } from "@/lib/api";
import { fetchTransitMatrix } from "@/lib/transit";
import {
  getActiveSession,
  useGenerationSessionStore,
} from "@/stores/generationSessionStore";

type Step =
  | "loading-session"
  | "fetching-transit"
  | "generating-plan"
  | "ready-mock"
  | "done"
  | "error";

const STEP_LABELS: Record<Step, string> = {
  "loading-session": "セッション確認中",
  "fetching-transit": "経路情報を取得中",
  "generating-plan": "プランを生成中",
  "ready-mock": "生成サーバーの応答待ち",
  done: "完了",
  error: "エラー",
};

const STEP_ORDER: Step[] = [
  "loading-session",
  "fetching-transit",
  "generating-plan",
  "done",
];

/**
 * 1.6 プラン生成中 (05)。
 *
 * フロー:
 *   1. Zustand から generationSession を取り出す（無効なら /plan/new にリダイレクト）
 *   2. fetchTransitMatrix(places) で transit を取得（失敗しても空配列で fail-soft）
 *   3. postPlanGenerate({ plan_id, evidence_pack_id, transit_matrix })
 *   4. 成功レスポンスの plan_id で /plan/<id> に遷移
 *      - 1.3c 時点は { plan_id: null } が返るので:
 *        - NEXT_PUBLIC_USE_MOCKS=1 なら Zustand の plan_id で遷移
 *        - それ以外なら "ready-mock" 状態で待機（1.3d 完成まで）
 *
 * デザイナーはアニメーション（Framer Motion での step 切り替え）と見た目を仕上げてよい。
 * ロジックと step 遷移順は触らない。
 */
export default function GeneratingPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const urlPlanId = params.id;
  const clearSession = useGenerationSessionStore((s) => s.clearSession);

  const [step, setStep] = useState<Step>("loading-session");
  const [error, setError] = useState<string | null>(null);
  const startedRef = useRef(false);
  const useMocks = process.env.NEXT_PUBLIC_USE_MOCKS === "1";

  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;

    const run = async () => {
      const session = getActiveSession();
      if (!session) {
        router.replace("/plan/new");
        return;
      }

      // URL と Zustand の plan_id が不一致 → Zustand を真実として URL を揃える
      if (session.plan_id !== urlPlanId) {
        router.replace(`/plan/${session.plan_id}/generating`);
        return;
      }

      try {
        setStep("fetching-transit");
        const departureTime = new Date();
        let transitMatrix: Awaited<ReturnType<typeof fetchTransitMatrix>>["edges"] = [];
        try {
          const result = await fetchTransitMatrix(session.places, departureTime);
          transitMatrix = result.edges;
        } catch {
          // fetchTransitMatrix は fail-soft で空配列を返す設計だが、SDK ロードや
          // 環境変数未設定の例外もここで拾う。空で続行する。
          transitMatrix = [];
        }

        setStep("generating-plan");
        const { plan_id: serverPlanId } = await postPlanGenerate({
          plan_id: session.plan_id,
          evidence_pack_id: session.evidence_pack_id,
          transit_matrix: transitMatrix,
        });

        if (serverPlanId) {
          // 1.3d 完成後: サーバーが plan_id を返す（Zustand と同じ UUID が返る前提）
          setStep("done");
          router.replace(`/plan/${serverPlanId}`);
          return;
        }

        // 1.3c 時点: plan_id=null
        if (useMocks) {
          // モックモード: Zustand の plan_id で遷移（デザイン確認）
          setStep("done");
          router.replace(`/plan/${session.plan_id}`);
          return;
        }
        // 実運用: 1.3d 未完成の間は待機表示
        setStep("ready-mock");
      } catch (err) {
        const message = err instanceof Error ? err.message : "生成に失敗しました";
        setError(message);
        setStep("error");
        // status を failed に（fire-and-forget）
        void updatePlanStatus(urlPlanId, "failed").catch(() => {});
      }
    };

    void run();
  }, [urlPlanId, router, useMocks]);

  const handleRetry = () => {
    clearSession();
    router.replace("/plan/new");
  };

  const activeIdx = step === "error" ? -1 : STEP_ORDER.indexOf(step === "ready-mock" ? "generating-plan" : step);

  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col items-center justify-center gap-8 px-6 py-16 text-center">
      <div className="flex flex-col items-center gap-4">
        {step === "error" ? (
          <WarningCircle size={48} weight="duotone" className="text-[color:var(--color-danger)]" />
        ) : step === "done" ? (
          <CheckCircle size={48} weight="duotone" className="text-[color:var(--color-evidence-verified)]" />
        ) : (
          <Spinner size={48} weight="bold" className="animate-spin text-[color:var(--color-primary)]" />
        )}
        <h1 className="text-2xl font-bold text-[color:var(--color-text-primary)]">
          {step === "error"
            ? "プラン生成に失敗しました"
            : step === "ready-mock"
            ? "生成サーバーの応答を待っています"
            : step === "done"
            ? "完成しました"
            : "プランを組み立てています..."}
        </h1>
        {step === "ready-mock" ? (
          <p className="max-w-md text-sm text-[color:var(--color-text-secondary)]">
            プラン生成は準備完了しました。LLM 接続（Phase 1.3d）の完成を待つ画面です。
            <code className="mx-1 rounded bg-[color:var(--color-surface)] px-1 py-0.5 text-xs">
              NEXT_PUBLIC_USE_MOCKS=1
            </code>
            を設定すると、モックプランで続きを確認できます。
          </p>
        ) : error ? (
          <p className="max-w-md text-sm text-[color:var(--color-danger)]">{error}</p>
        ) : null}
      </div>

      <ol className="flex w-full max-w-md flex-col gap-2">
        {STEP_ORDER.slice(0, 3).map((s, i) => {
          const isActive = activeIdx === i;
          const isDone = activeIdx > i;
          return (
            <li
              key={s}
              className="flex items-center gap-3 rounded-md border border-[color:var(--color-border)] bg-[color:var(--color-surface)] px-4 py-2 text-left text-sm"
            >
              <span
                className={
                  isDone
                    ? "text-[color:var(--color-evidence-verified)]"
                    : isActive
                    ? "text-[color:var(--color-primary)]"
                    : "text-[color:var(--color-text-tertiary)]"
                }
              >
                {isDone ? "✓" : i + 1}
              </span>
              <span
                className={
                  isActive
                    ? "font-medium text-[color:var(--color-text-primary)]"
                    : "text-[color:var(--color-text-secondary)]"
                }
              >
                {STEP_LABELS[s]}
              </span>
            </li>
          );
        })}
      </ol>

      {step === "error" ? (
        <button
          type="button"
          onClick={handleRetry}
          className="rounded-md border border-[color:var(--color-border)] bg-[color:var(--color-surface)] px-4 py-2 text-sm font-medium hover:opacity-80"
        >
          もう一度入力からやり直す
        </button>
      ) : null}
    </main>
  );
}
