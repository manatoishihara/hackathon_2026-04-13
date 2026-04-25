import type { Plan, Participant } from "shared-types";

import { formatDateRange } from "@/lib/format";

type Props = {
  plan: Plan;
  participants: Participant[];
};

/**
 * 1.7 プラン閲覧画面のヘッダー。
 * 上段: ROUTEFUL ロゴ + 参加者アバター列
 * 下段: 英字ラベル「REGION · SEASON」 + 明朝大見出し + メタ
 */
export function PlanHeader({ plan, participants }: Props) {
  const totalDays = countDays(plan.start_date, plan.end_date);
  const nights = Math.max(0, totalDays - 1);
  const seasonLabel = seasonOf(plan.start_date);

  return (
    <header className="flex flex-col gap-6 border-b border-[color:var(--color-border)] pb-8">
      <div className="flex items-center justify-between">
        <div className="flex items-baseline gap-2">
          <span className="font-heading text-lg font-medium tracking-[0.18em] text-[color:var(--color-text-primary)]">
            ROUTEFUL
          </span>
          <span className="hidden text-[10px] italic text-[color:var(--color-text-secondary)] sm:inline">
            — a journal for the journey
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          {participants.slice(0, 5).map((p) => (
            <span
              key={p.id}
              title={p.display_name}
              className="inline-flex h-6 w-6 items-center justify-center rounded-full text-[10px] font-medium text-[color:var(--color-background)]"
              style={{ backgroundColor: p.avatar_color }}
              aria-label={p.display_name}
            >
              {firstChar(p.display_name)}
            </span>
          ))}
        </div>
      </div>

      <div className="flex flex-col gap-3">
        <p className="text-[11px] font-medium tracking-[0.24em] text-[color:var(--color-text-secondary)]">
          {plan.region.toUpperCase()} {seasonLabel ? `· ${seasonLabel}` : ""}
        </p>
        <h1 className="font-heading text-3xl font-medium leading-[1.4] tracking-[0.02em] text-[color:var(--color-text-primary)] sm:text-4xl">
          {plan.title}
        </h1>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-[color:var(--color-text-secondary)]">
          <span>{formatDateRange(plan.start_date, plan.end_date)}</span>
          <span aria-hidden className="text-[color:var(--color-text-tertiary)]">
            ·
          </span>
          <span>
            {nights > 0 ? `${nights}泊${totalDays}日` : `${totalDays}日`}
          </span>
          <span aria-hidden className="text-[color:var(--color-text-tertiary)]">
            ·
          </span>
          <span>
            {participants.length === 1
              ? "ひとり旅"
              : `${participants.length}人`}
          </span>
        </div>
      </div>
    </header>
  );
}

function firstChar(name: string): string {
  if (!name) return "?";
  // サロゲートペア対応で先頭 1 文字を取る
  return Array.from(name)[0] ?? "?";
}

function countDays(startIso: string, endIso: string): number {
  const start = new Date(startIso);
  const end = new Date(endIso);
  const ms = end.getTime() - start.getTime();
  if (ms < 0) return 1;
  return Math.round(ms / (1000 * 60 * 60 * 24)) + 1;
}

function seasonOf(iso: string): string | null {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  const m = d.getMonth() + 1;
  if (m === 12 || m <= 2) return "WINTER";
  if (m <= 5) return "SPRING";
  if (m <= 8) return "SUMMER";
  return "AUTUMN";
}
