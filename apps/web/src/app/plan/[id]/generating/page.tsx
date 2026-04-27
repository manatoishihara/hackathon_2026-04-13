"use client";

import { useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";

import { postPlanGenerate, updatePlanStatus } from "@/lib/api";
import { fetchTransitMatrix } from "@/lib/transit";
import {
  getActiveSession,
  useGenerationSessionStore,
} from "@/stores/generationSessionStore";
import { FlyingPlane } from "@/components/plan-generating/FlyingPlane";

import { shouldEarlyThrowOnTransit } from "./transit-guard";

type Step =
  | "loading-session"
  | "fetching-transit"
  | "generating-plan"
  | "ready-mock"
  | "done"
  | "error";

const STEP_LABELS: Record<Step, string> = {
  "loading-session": "搭乗手続き",
  "fetching-transit": "ルート計算",
  "generating-plan": "プラン編集",
  "ready-mock": "サーバー応答待ち",
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
 * mock 時のみ、演出を見せるための擬似的な進行時間。
 * 本番（実 LLM 接続）では各 await が実時間を消費するので不要。
 * 合計 ≒ 14.5 秒（fetching 4s + generating 9s + done 1.5s）。
 */
const MOCK_DELAY_MS = {
  fetching: 4000,
  generating: 9000,
  done: 1500,
} as const;

const sleep = (ms: number) =>
  new Promise<void>((resolve) => setTimeout(resolve, ms));

/**
 * 1.6 プラン生成中 (05)。
 *
 * フロー:
 *   1. Zustand から generationSession を取り出す（無効なら /plan/new にリダイレクト）
 *   2. fetchTransitMatrix(places) で transit を取得
 *      - 全 pair 失敗 (succeeded === 0 && attempted > 0) なら早期 throw → エラー表示
 *      - SDK 例外も catch で再 throw（旧 fail-soft の握りつぶしを排除、Phase 1.10 後段 fix）
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
          // 全 pair 失敗 → サーバー 422 へ流さず早期エラー化（Codex review 2 Blocker 1）。
          // attempted === 0 (places 1 件以下) は transit_matrix=[] で続行（既存挙動）。
          if (shouldEarlyThrowOnTransit(result.stats)) {
            throw new Error(
              "経路情報を取得できませんでした。少し時間をおいてお試しください。",
            );
          }
        } catch (err) {
          // SDK ロード失敗 / API 不到達 / fetch 中の throw / 上の throw を一律 error に集約。
          // 旧実装は catch で空配列にして続行 → 422 に流れる穴があったため再 throw。
          throw err instanceof Error
            ? err
            : new Error("経路情報の取得中にエラーが発生しました");
        }
        // mock 時は実 await が即解決するので、演出を見せるための擬似ウェイトを挟む
        if (useMocks) await sleep(MOCK_DELAY_MS.fetching);

        setStep("generating-plan");
        const { plan_id: serverPlanId } = await postPlanGenerate({
          plan_id: session.plan_id,
          evidence_pack_id: session.evidence_pack_id,
          transit_matrix: transitMatrix,
        });
        if (useMocks) await sleep(MOCK_DELAY_MS.generating);

        if (serverPlanId) {
          // 1.3d 完成後: サーバーが plan_id を返す（Zustand と同じ UUID が返る前提）
          // 成功したので session を必ずクリア（戻る操作・再マウントでの重複 generate 防止）
          clearSession();
          setStep("done");
          if (useMocks) await sleep(MOCK_DELAY_MS.done);
          router.replace(`/plan/${serverPlanId}`);
          return;
        }

        // 1.3c 時点: plan_id=null
        if (useMocks) {
          // モックモード: Zustand の plan_id で遷移（デザイン確認）
          clearSession();
          setStep("done");
          await sleep(MOCK_DELAY_MS.done);
          router.replace(`/plan/${session.plan_id}`);
          return;
        }
        // 実運用: 1.3d 未完成の間は待機表示
        // session は保持したまま（LLM 接続完了後に再チャレンジする導線を残すため）。
        // 重複 generate の懸念は startedRef による 1 回ガード + React Query 側の整合で緩和。
        setStep("ready-mock");
      } catch (err) {
        const message = err instanceof Error ? err.message : "生成に失敗しました";
        setError(message);
        setStep("error");
        // status を failed に更新（失敗時も session は保持せず破棄、再入力からやり直させる）
        clearSession();
        // fire-and-forget だが失敗ログは残して追跡可能にする
        void updatePlanStatus(urlPlanId, "failed").catch((e) => {
          console.warn("updatePlanStatus(failed) failed", e);
        });
      }
    };

    void run();
  }, [urlPlanId, router, useMocks]);

  const handleRetry = () => {
    clearSession();
    router.replace("/plan/new");
  };

  const visibleStep = step === "ready-mock" ? "generating-plan" : step;
  const activeIdx = step === "error" ? -1 : STEP_ORDER.indexOf(visibleStep);

  const variant: "flying" | "landed" | "error" =
    step === "error" ? "error" : step === "done" ? "landed" : "flying";

  // 飛行機の水平進捗 (0〜1)
  const progress =
    step === "done"
      ? 1
      : step === "error"
        ? 0
        : Math.max(0, activeIdx) / (STEP_ORDER.length - 1);

  const headline =
    step === "error"
      ? "離陸できませんでした"
      : step === "ready-mock"
        ? "サーバーの応答を待っています"
        : step === "done"
          ? "目的地に到着しました"
          : "プランを編んでいます";

  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col items-center justify-center gap-10 px-6 py-16 text-center">
      <div className="flex w-full flex-col items-center gap-6">
        <p className="text-[10px] font-medium tracking-[0.28em] text-[color:var(--color-text-secondary)]">
          IN FLIGHT
        </p>
        <FlyingPlane variant={variant} progress={progress} />
        <h1 className="font-heading text-3xl font-medium leading-[1.4] text-[color:var(--color-text-primary)] sm:text-4xl">
          {headline}
        </h1>
        {step === "ready-mock" ? (
          <p className="max-w-md text-sm leading-relaxed text-[color:var(--color-text-secondary)]">
            プラン生成は準備完了しました。LLM 接続（Phase 1.3d）の完成を待つ画面です。
            <code className="mx-1 rounded bg-[color:var(--color-surface)] px-1 py-0.5 text-xs">
              NEXT_PUBLIC_USE_MOCKS=1
            </code>
            を設定すると、モックプランで続きを確認できます。
          </p>
        ) : error ? (
          <p className="flex max-w-md items-start gap-2 border-l-2 border-[color:var(--color-accent)] pl-3 text-left text-sm leading-relaxed text-[color:var(--color-text-primary)]">
            {error}
          </p>
        ) : null}
      </div>

      <ol
        className="grid w-full max-w-md gap-0"
        style={{
          gridTemplateColumns: `repeat(${STEP_ORDER.length}, minmax(0, 1fr))`,
        }}
        role="list"
      >
        {STEP_ORDER.map((s, i) => {
          const isActive = activeIdx === i;
          const isDone = activeIdx > i || step === "done";
          const isFirst = i === 0;
          const isLast = i === STEP_ORDER.length - 1;
          return (
            <li
              key={s}
              className="relative flex flex-col items-center gap-2 pt-1"
            >
              {/* 経路線（左半分） */}
              {!isFirst ? (
                <span
                  aria-hidden
                  className={`absolute left-0 top-2.5 h-px w-1/2 ${
                    isDone || isActive
                      ? "bg-[color:var(--color-primary)]"
                      : "bg-[color:var(--color-border)]"
                  }`}
                />
              ) : null}
              {/* 経路線（右半分） */}
              {!isLast ? (
                <span
                  aria-hidden
                  className={`absolute right-0 top-2.5 h-px w-1/2 ${
                    isDone
                      ? "bg-[color:var(--color-primary)]"
                      : "bg-[color:var(--color-border)]"
                  }`}
                />
              ) : null}
              {/* マイルストーンドット（active は scale + ring で強調） */}
              <span
                aria-hidden
                className={`relative z-10 inline-block rounded-full border-2 transition-all duration-500 ${
                  isDone
                    ? "h-3 w-3 border-[color:var(--color-primary)] bg-[color:var(--color-primary)]"
                    : isActive
                      ? "h-4 w-4 border-[color:var(--color-primary)] bg-[color:var(--color-accent)] shadow-[0_0_0_4px_rgba(240,153,123,0.25)]"
                      : "h-3 w-3 border-[color:var(--color-border)] bg-[color:var(--color-surface)]"
                }`}
              />
              <span
                className={`text-[10px] font-medium leading-tight ${
                  isActive
                    ? "text-[color:var(--color-primary)]"
                    : isDone
                      ? "text-[color:var(--color-text-primary)]"
                      : "text-[color:var(--color-text-tertiary)]"
                }`}
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
          className="rounded-full border border-[color:var(--color-border)] bg-[color:var(--color-surface)] px-6 py-2.5 text-sm font-medium text-[color:var(--color-text-primary)] transition-colors hover:border-[color:var(--color-primary)] hover:text-[color:var(--color-primary)]"
        >
          もう一度入力からやり直す
        </button>
      ) : null}
    </main>
  );
}
