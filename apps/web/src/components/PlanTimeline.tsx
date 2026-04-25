import { Fragment } from "react";
import type { PlanItem as PlanItemType } from "shared-types";
import { Calendar } from "@phosphor-icons/react/dist/ssr";

import { PlanItem } from "./PlanItem";
import { TransitRow } from "./plan-view/TransitRow";
import { EmptyState } from "./ui/states/EmptyState";

type Props = {
  /** 表示対象の PlanItem（DayTabs で絞り込み済みの単日想定） */
  items: PlanItemType[];
};

/**
 * タイムライン本体。HTML モック準拠で:
 * - 各 PlanItem は時刻 / カテゴリ別 thumb / タイトル + 説明 / Evidence の横並び
 * - transit は区切り線型（縦線 + italic 明朝）でカード化しない
 * - アイテム間に transit_to_next があれば挿入
 */
export function PlanTimeline({ items }: Props) {
  if (items.length === 0) {
    return (
      <EmptyState
        icon={<Calendar size={32} />}
        title="この日の予定はまだありません"
        description="DAY タブで日を切り替えるか、プランを再生成してください。"
      />
    );
  }

  const sorted = [...items].sort((a, b) => {
    if (a.order_index !== b.order_index) return a.order_index - b.order_index;
    return a.start_time.localeCompare(b.start_time);
  });

  return (
    <div className="flex flex-col gap-1.5">
      {sorted.map((item) => {
        if (item.item_type === "transit") {
          return (
            <TransitRow
              key={item.id}
              kind="item"
              item={item as PlanItemType & { item_type: "transit" }}
            />
          );
        }
        return (
          <Fragment key={item.id}>
            <PlanItem item={item} />
            {item.transit_to_next ? (
              <TransitRow kind="next" transit={item.transit_to_next} />
            ) : null}
          </Fragment>
        );
      })}
    </div>
  );
}

/**
 * 日付（JST の YYYY-MM-DD）でグルーピング。テスト互換性のため export 維持。
 * 1.7 では page.tsx 側で DAY タブ生成に使う。
 */
export function groupByDate(
  items: PlanItemType[],
): { dateKey: string; items: PlanItemType[] }[] {
  const keyOf = (iso: string): string => {
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

  for (const key of order) {
    map.get(key)!.sort((a, b) => {
      if (a.order_index !== b.order_index) return a.order_index - b.order_index;
      return a.start_time.localeCompare(b.start_time);
    });
  }

  return order.map((dateKey) => ({ dateKey, items: map.get(dateKey)! }));
}
