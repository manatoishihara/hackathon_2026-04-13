import type { PlanItem } from "shared-types";

import { formatDurationMin, formatJpy } from "@/lib/format";

type Props = {
  /** その日の PlanItem だけを渡す（DayTabs で絞り込み済み） */
  items: PlanItem[];
};

/**
 * 「その日の輪郭」カード。HTML モック準拠。
 * 移動時間 / 想定予算 / アイテム数 を簡潔に並べる。
 */
export function StatsCard({ items }: Props) {
  const stats = computeStats(items);

  const rows: Array<[string, string]> = [
    ["移動", formatDurationMin(stats.transitMin)],
    ["想定予算", formatJpy(stats.totalCost)],
    ["立ち寄り", `${stats.spotsCount}か所`],
  ];

  return (
    <section className="flex flex-col gap-3 rounded-md border border-[color:var(--color-border)] bg-[color:var(--color-surface)] p-4">
      <h3 className="font-heading text-sm font-medium text-[color:var(--color-text-primary)]">
        その日の輪郭
      </h3>
      <dl className="flex flex-col gap-1.5">
        {rows.map(([k, v]) => (
          <div key={k} className="flex items-baseline justify-between text-xs">
            <dt className="text-[color:var(--color-text-secondary)]">{k}</dt>
            <dd className="font-mono tabular-nums text-[color:var(--color-text-primary)]">
              {v}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function computeStats(items: PlanItem[]) {
  let transitMin = 0;
  let totalCost = 0;
  let spotsCount = 0;
  for (const item of items) {
    if (item.item_type === "transit") {
      const dur =
        (new Date(item.end_time).getTime() -
          new Date(item.start_time).getTime()) /
        60_000;
      transitMin += Math.max(0, Math.round(dur));
    } else {
      spotsCount += 1;
    }
    if (item.cost_jpy != null) totalCost += item.cost_jpy;
    if (item.transit_to_next?.duration_min != null) {
      transitMin += item.transit_to_next.duration_min;
    }
    if (item.transit_to_next?.fare_jpy != null) {
      totalCost += item.transit_to_next.fare_jpy;
    }
  }
  return { transitMin, totalCost, spotsCount };
}
