"use client";

import { useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import { getParticipants, getPlan, getPlanItems } from "@/lib/api";
import { groupByDate, PlanTimeline } from "@/components/PlanTimeline";
import { MapView } from "@/components/MapView";
import { DayTabs } from "@/components/plan-view/DayTabs";
import { PlanHeader } from "@/components/plan-view/PlanHeader";
import { StatsCard } from "@/components/plan-view/StatsCard";
import { SuggestionCard } from "@/components/plan-view/SuggestionCard";
import { LoadingState } from "@/components/ui/states/LoadingState";
import { ErrorState } from "@/components/ui/states/ErrorState";
import { formatMonthDay } from "@/lib/format";

/**
 * 1.7 プラン閲覧画面 (06)。HTML モック "blue hour" 準拠の構成:
 *   - PlanHeader: ロゴ + 参加者アバター + 英字ラベル + 明朝大見出し + メタ
 *   - DayTabs: 日ごとの切替
 *   - 2 カラム (1.35fr / 1fr): 左 PlanTimeline、右 Map + StatsCard + SuggestionCard
 *
 * データ取得は lib/api.ts 経由（USE_MOCKS=1 なら fixture）。ロジックは触らない。
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

  const groups = useMemo(
    () => (itemsQuery.data ? groupByDate(itemsQuery.data) : []),
    [itemsQuery.data],
  );
  const [activeDateKey, setActiveDateKey] = useState<string | null>(null);
  const effectiveActiveKey =
    activeDateKey ?? groups[0]?.dateKey ?? null;

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

  if (
    error ||
    !planQuery.data ||
    !itemsQuery.data ||
    !participantsQuery.data
  ) {
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
  const participants = participantsQuery.data;

  const activeGroup =
    groups.find((g) => g.dateKey === effectiveActiveKey) ?? groups[0];
  const activeItems = activeGroup?.items ?? [];

  const days = groups.map((g) => ({
    dateKey: g.dateKey,
    label: formatMonthDay(g.items[0].start_time),
  }));

  return (
    <main className="mx-auto flex min-h-screen max-w-6xl flex-col gap-8 px-6 py-8">
      <PlanHeader plan={plan} participants={participants} />

      <DayTabs
        days={days}
        activeDateKey={effectiveActiveKey ?? ""}
        onChange={setActiveDateKey}
      />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1.35fr_1fr]">
        <PlanTimeline items={activeItems} />
        <aside className="flex flex-col gap-3">
          <div className="h-[200px]">
            <MapView items={activeItems} />
          </div>
          <StatsCard items={activeItems} />
          <SuggestionCard />
        </aside>
      </div>
    </main>
  );
}
