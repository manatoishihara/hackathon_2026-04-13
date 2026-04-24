"use client";

import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Calendar, MapPin, Users, Wallet } from "@phosphor-icons/react/dist/ssr";

import { getParticipants, getPlan, getPlanItems } from "@/lib/api";
import { BudgetSummary } from "@/components/BudgetSummary";
import { PlanTimeline } from "@/components/PlanTimeline";
import { LoadingState } from "@/components/ui/states/LoadingState";
import { ErrorState } from "@/components/ui/states/ErrorState";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Separator } from "@/components/ui/separator";
import { formatDateRange } from "@/lib/format";

/**
 * 1.7 プラン閲覧画面 (06)。
 *
 * タイムライン（主役）/ 予算サマリ（脇役）/ マップ（脇役、Branch 4 で差し込み） の 3 カラム。
 * 「タイムライン / マップ / 予算」タブで切り替え可能。
 *
 * データ取得は lib/api.ts 経由（USE_MOCKS=1 なら fixture、それ以外は Supabase 直接）。
 * デザイナーは className / レイアウト / Motion を触ってよい。ロジックは触らない。
 */
export default function PlanPage() {
  const params = useParams<{ id: string }>();
  const planId = params.id;

  const planQuery = useQuery({
    queryKey: ["plan", planId],
    queryFn: () => getPlan(planId),
    enabled: Boolean(planId),
  });
  const itemsQuery = useQuery({
    queryKey: ["plan-items", planId],
    queryFn: () => getPlanItems(planId),
    enabled: Boolean(planId),
  });
  const participantsQuery = useQuery({
    queryKey: ["participants", planId],
    queryFn: () => getParticipants(planId),
    enabled: Boolean(planId),
  });

  const isLoading =
    planQuery.isPending || itemsQuery.isPending || participantsQuery.isPending;
  const error = planQuery.error ?? itemsQuery.error ?? participantsQuery.error;

  if (isLoading) {
    return (
      <main className="mx-auto min-h-screen max-w-6xl px-6 py-12">
        <LoadingState message="プランを読み込み中..." />
      </main>
    );
  }

  if (error || !planQuery.data || !itemsQuery.data || !participantsQuery.data) {
    return (
      <main className="mx-auto min-h-screen max-w-6xl px-6 py-12">
        <ErrorState
          title="プランを表示できません"
          message={
            error instanceof Error
              ? error.message
              : "プランデータの読み込みに失敗しました。もう一度お試しください。"
          }
          action={{
            label: "もう一度読み込む",
            onClick: () => {
              planQuery.refetch();
              itemsQuery.refetch();
              participantsQuery.refetch();
            },
          }}
        />
      </main>
    );
  }

  const plan = planQuery.data;
  const items = itemsQuery.data;
  const participants = participantsQuery.data;

  return (
    <main className="mx-auto flex min-h-screen max-w-6xl flex-col gap-6 px-6 py-8">
      <PlanHeader plan={plan} participantCount={participants.length} />
      <Tabs defaultValue="timeline" className="flex flex-col gap-4">
        <TabsList>
          <TabsTrigger value="timeline" className="gap-2">
            <Calendar size={14} weight="duotone" />
            タイムライン
          </TabsTrigger>
          <TabsTrigger value="map" className="gap-2">
            <MapPin size={14} weight="duotone" />
            マップ
          </TabsTrigger>
          <TabsTrigger value="budget" className="gap-2">
            <Wallet size={14} weight="duotone" />
            予算
          </TabsTrigger>
        </TabsList>

        {/* デスクトップ: タイムラインが主役、予算サマリを右サイドに */}
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_320px]">
          <TabsContent value="timeline" className="m-0">
            <PlanTimeline items={items} />
          </TabsContent>
          <TabsContent value="map" className="m-0">
            <MapViewPlaceholder />
          </TabsContent>
          <TabsContent value="budget" className="m-0 lg:hidden">
            <BudgetSummary plan={plan} items={items} />
          </TabsContent>
          <aside className="hidden flex-col gap-4 lg:flex">
            <BudgetSummary plan={plan} items={items} />
            <ParticipantList participants={participants} />
          </aside>
        </div>
      </Tabs>
    </main>
  );
}

function PlanHeader({
  plan,
  participantCount,
}: {
  plan: Awaited<ReturnType<typeof getPlan>>;
  participantCount: number;
}) {
  return (
    <header className="flex flex-col gap-3">
      <div className="flex items-center gap-2 text-sm text-[color:var(--color-text-secondary)]">
        <MapPin size={14} weight="duotone" />
        <span>{plan.region}</span>
        <Separator orientation="vertical" className="mx-1 h-3" />
        <Calendar size={14} weight="duotone" />
        <span>{formatDateRange(plan.start_date, plan.end_date)}</span>
        <Separator orientation="vertical" className="mx-1 h-3" />
        <Users size={14} weight="duotone" />
        <span>
          {participantCount} 人
        </span>
      </div>
      <h1 className="text-2xl font-bold text-[color:var(--color-text-primary)] sm:text-3xl">
        {plan.title}
      </h1>
      {plan.status === "generating" ? (
        <p className="inline-flex w-fit items-center gap-1 rounded-full bg-[color:var(--color-primary)]/10 px-2 py-0.5 text-xs font-medium text-[color:var(--color-primary)]">
          生成中
        </p>
      ) : null}
      {plan.status === "failed" ? (
        <p className="inline-flex w-fit items-center gap-1 rounded-full bg-[color:var(--color-danger)]/10 px-2 py-0.5 text-xs font-medium text-[color:var(--color-danger)]">
          生成失敗
        </p>
      ) : null}
    </header>
  );
}

function ParticipantList({
  participants,
}: {
  participants: Awaited<ReturnType<typeof getParticipants>>;
}) {
  if (participants.length === 0) return null;
  return (
    <section className="flex flex-col gap-3 rounded-lg border border-[color:var(--color-border)] bg-[color:var(--color-surface)] p-4">
      <h3 className="text-sm font-semibold text-[color:var(--color-text-secondary)]">
        参加者
      </h3>
      <ul className="flex flex-col gap-2">
        {participants.map((p) => (
          <li key={p.id} className="flex items-center gap-2 text-sm">
            <span
              className="inline-block h-3 w-3 shrink-0 rounded-full"
              style={{ backgroundColor: p.avatar_color }}
              aria-hidden="true"
            />
            <span className="truncate text-[color:var(--color-text-primary)]">
              {p.display_name}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function MapViewPlaceholder() {
  return (
    <div className="flex min-h-[480px] items-center justify-center rounded-lg border border-dashed border-[color:var(--color-border)] bg-[color:var(--color-surface)]/50 text-sm text-[color:var(--color-text-tertiary)]">
      マップビューは Phase 1.8（Branch 4）で差し込まれます。
    </div>
  );
}
