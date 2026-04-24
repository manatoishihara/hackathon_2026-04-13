"use client";

import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Copy, CheckCircle, Share } from "@phosphor-icons/react/dist/ssr";

import { getPlan } from "@/lib/api";
import { ShareQRCode } from "@/components/ShareQRCode";
import { LoadingState } from "@/components/ui/states/LoadingState";
import { ErrorState } from "@/components/ui/states/ErrorState";
import { EmptyState } from "@/components/ui/states/EmptyState";

/**
 * 1.9 プラン共有画面 (08)。
 *
 * - `share_token` がある Plan: QR + URL + コピーボタン
 * - まだ `share_token` がない Plan: 「共有を有効化」ボタン（POST /api/plans/:id/share は
 *   メンバー B が DB 整理タスクで実装予定、このボタンは 1.9 本実装時に配線する placeholder）
 *
 * デザイナーは QR の見た目、コピーボタンの UX、印刷用レイアウトを調整してよい。
 * API 配線（fetch 等）は DB 担当が別ブランチで完成させる。
 */
export default function SharePage() {
  const params = useParams<{ id: string }>();
  const planId = params.id;

  const planQuery = useQuery({
    queryKey: ["plan", planId],
    queryFn: () => getPlan(planId),
    enabled: Boolean(planId),
  });

  if (planQuery.isPending) {
    return (
      <main className="mx-auto min-h-screen max-w-2xl px-6 py-12">
        <LoadingState message="プランを読み込み中..." />
      </main>
    );
  }

  if (planQuery.error || !planQuery.data) {
    return (
      <main className="mx-auto min-h-screen max-w-2xl px-6 py-12">
        <ErrorState
          title="プランを表示できません"
          message={
            planQuery.error instanceof Error
              ? planQuery.error.message
              : "プランデータの読み込みに失敗しました。"
          }
        />
      </main>
    );
  }

  const plan = planQuery.data;

  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col gap-8 px-6 py-12">
      <header className="flex flex-col gap-2">
        <p className="text-sm font-medium tracking-widest text-[color:var(--color-primary)]">
          SHARE
        </p>
        <h1 className="text-2xl font-bold text-[color:var(--color-text-primary)] sm:text-3xl">
          {plan.title} を共有
        </h1>
        <p className="text-sm text-[color:var(--color-text-secondary)]">
          読み取り専用リンクを共有します。受け取った人はプランを閲覧できますが、編集はできません。
        </p>
      </header>

      {plan.share_token ? (
        <ShareReadyView planId={planId} shareToken={plan.share_token} />
      ) : (
        <ShareDisabledView planId={planId} />
      )}
    </main>
  );
}

function ShareReadyView({
  planId,
  shareToken,
}: {
  planId: string;
  shareToken: string;
}) {
  const shareUrl = buildShareUrl(shareToken);
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(shareUrl);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      // クリップボード API が使えない環境では何もしない（UX 劣化、致命ではない）
    }
  };

  return (
    <section className="flex flex-col items-center gap-6 rounded-lg border border-[color:var(--color-border)] bg-[color:var(--color-surface)] p-6">
      <ShareQRCode value={shareUrl} />
      <div className="flex w-full flex-col gap-2">
        <p className="text-xs font-semibold uppercase tracking-wide text-[color:var(--color-text-tertiary)]">
          共有 URL
        </p>
        <div className="flex items-center gap-2 rounded-md border border-[color:var(--color-border)] bg-[color:var(--color-background)] px-3 py-2 text-sm">
          <code className="min-w-0 flex-1 truncate font-mono text-xs text-[color:var(--color-text-primary)]">
            {shareUrl}
          </code>
          <button
            type="button"
            onClick={handleCopy}
            className="inline-flex shrink-0 items-center gap-1 rounded-md bg-[color:var(--color-primary)] px-3 py-1 text-xs font-medium text-white transition hover:opacity-90"
            aria-label="共有 URL をコピー"
          >
            {copied ? (
              <>
                <CheckCircle size={14} weight="fill" />
                コピー済み
              </>
            ) : (
              <>
                <Copy size={14} weight="bold" />
                コピー
              </>
            )}
          </button>
        </div>
      </div>
      <p className="text-xs text-[color:var(--color-text-tertiary)]">
        プラン ID: <span className="font-mono">{planId.slice(0, 8)}</span>
      </p>
    </section>
  );
}

function ShareDisabledView({ planId }: { planId: string }) {
  // POST /api/plans/:id/share は DB 担当が実装予定（tasks/handoff-db.md DB-4）。
  // 骨組みでは API 呼び出しは行わず、有効化ボタンを無効状態で表示する。
  return (
    <EmptyState
      icon={<Share size={32} weight="duotone" />}
      title="このプランはまだ共有されていません"
      description="共有を有効化すると、読み取り専用の URL と QR コードが発行されます。"
      action={
        <button
          type="button"
          disabled
          title="1.9 本実装で配線されます（POST /api/plans/:id/share）"
          className="inline-flex items-center gap-2 rounded-md border border-[color:var(--color-border)] bg-[color:var(--color-surface)] px-4 py-2 text-sm font-medium opacity-50"
        >
          共有を有効化（準備中）
        </button>
      }
    />
  );
}

function buildShareUrl(shareToken: string): string {
  if (typeof window === "undefined") {
    return `/plan/shared/${shareToken}`;
  }
  return `${window.location.origin}/plan/shared/${shareToken}`;
}
