"use client";

import { useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import dynamic from "next/dynamic";

import { getParticipants, getPlan, getPlanItems } from "@/lib/api";
import { groupByDate, PlanTimeline } from "@/components/PlanTimeline";
import { MapMiniStrip } from "@/components/MapMiniStrip";
import { DayTabs } from "@/components/plan-view/DayTabs";
import { PlanHeader } from "@/components/plan-view/PlanHeader";
import { StatsCard } from "@/components/plan-view/StatsCard";
import { SuggestionCard } from "@/components/plan-view/SuggestionCard";
import { LoadingState } from "@/components/ui/states/LoadingState";
import { SkeletonTimeline } from "@/components/ui/states/SkeletonPlanItem";
import { ErrorState } from "@/components/ui/states/ErrorState";
import { MapErrorBoundary } from "@/components/ui/MapErrorFallback";
import { formatMonthDay } from "@/lib/format";

// Mapbox GL（~300KB）を遅延ロードして初期バンドルを削減（⑥ Lazy Load）
const MapView = dynamic(
  () => import("@/components/MapView").then((m) => m.MapView),
  {
    ssr: false,
    loading: () => (
      <div className="h-full w-full animate-pulse rounded-lg bg-[color:var(--color-border)]" />
    ),
  },
);

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
    // 遷移時に前のデータを保持してチラつきを防ぐ（⑭ フォールバック設計）
    placeholderData: (prev) => prev,
  });
  const itemsQuery = useQuery({
    queryKey: ["plan-items", planId],
    queryFn: () => getPlanItems(planId),
    enabled: Boolean(planId),
    placeholderData: (prev) => prev,
  });
  const participantsQuery = useQuery({
    queryKey: ["participants", planId],
    queryFn: () => getParticipants(planId),
    enabled: Boolean(planId),
    placeholderData: (prev) => prev,
  });

  const groups = useMemo(
    () => (itemsQuery.data ? groupByDate(itemsQuery.data) : []),
    [itemsQuery.data],
  );
  const [activeDateKey, setActiveDateKey] = useState<string | null>(null);
  const effectiveActiveKey =
    activeDateKey ?? groups[0]?.dateKey ?? null;


  const error = planQuery.error ?? itemsQuery.error ?? participantsQuery.error;

  if (planQuery.isPending) {
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

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* タイムラインはデータ取得中は Skeleton で表示（⑥ Lazy Load / Skeleton UI）*/}
        {itemsQuery.isPending ? (
          <SkeletonTimeline />
        ) : (
          <PlanTimeline items={activeItems} />
        )}
        <aside className="flex flex-col gap-3">
          <section className="flex flex-col gap-2">
            <p className="text-[10px] font-medium tracking-[0.18em] text-[color:var(--color-text-secondary)]">
              MAP
            </p>
            <div className="h-[50vh] min-h-[320px]">
              {/* MapView は dynamic import + Error Boundary で隔離（⑥ Lazy Load / ⑭ フォールバック）*/}
              <MapErrorBoundary>
                <MapView items={activeItems} />
              </MapErrorBoundary>
            </div>
          </section>
          <MapMiniStrip items={activeItems} />
          <StatsCard items={activeItems} />
          <SuggestionCard />
        </aside>
      </div>
    </main>
  );
}
