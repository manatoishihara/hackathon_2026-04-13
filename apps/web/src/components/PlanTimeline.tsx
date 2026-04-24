import type { PlanItem as PlanItemType } from "shared-types";

import { PlanItem } from "./PlanItem";
import { EmptyState } from "./ui/states/EmptyState";
import { formatMonthDay } from "@/lib/format";
import { Calendar } from "@phosphor-icons/react/dist/ssr";

type Props = {
  items: PlanItemType[];
};

/**
 * PlanItem[] を `start_time` の日付でグルーピングして縦並びに描画。
 * タイムライン画面の主役コンポーネント。0 件時は EmptyState を出す。
 */
export function PlanTimeline({ items }: Props) {
  if (items.length === 0) {
    return (
      <EmptyState
        icon={<Calendar size={32} />}
        title="プラン項目がまだありません"
        description="「プランを生成」を押すと時系列のタイムラインが表示されます。"
      />
    );
  }

  const groups = groupByDate(items);

  return (
    <div className="flex flex-col gap-6">
      {groups.map((group) => (
        <section key={group.dateKey} className="flex flex-col gap-3">
          <h2 className="text-sm font-semibold tracking-wide text-[color:var(--color-text-secondary)]">
            {formatMonthDay(group.items[0].start_time)}
          </h2>
          <div className="flex flex-col gap-3">
            {group.items.map((item) => (
              <PlanItem key={item.id} item={item} />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

/**
 * 日付（JST の YYYY-MM-DD）でグルーピング。export してテストに使う。
 */
export function groupByDate(
  items: PlanItemType[],
): { dateKey: string; items: PlanItemType[] }[] {
  const keyOf = (iso: string): string => {
    // JST の YYYY-MM-DD に丸める（`formatISOToJstDate`）
    return new Intl.DateTimeFormat("en-CA", {
      timeZone: "Asia/Tokyo",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).format(new Date(iso));
  };

  const map = new Map<string, PlanItemType[]>();
  const order: string[] = [];
  for (const item of items) {
    const key = keyOf(item.start_time);
    if (!map.has(key)) {
      map.set(key, []);
      order.push(key);
    }
    map.get(key)!.push(item);
  }

  // 各グループ内は order_index または start_time で昇順
  for (const key of order) {
    map.get(key)!.sort((a, b) => {
      if (a.order_index !== b.order_index) return a.order_index - b.order_index;
      return a.start_time.localeCompare(b.start_time);
    });
  }

  return order.map((dateKey) => ({ dateKey, items: map.get(dateKey)! }));
}
