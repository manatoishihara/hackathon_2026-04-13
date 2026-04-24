import { describe, expect, it } from "vitest";

import { groupByDate } from "./PlanTimeline";
import { mockPlanItems } from "@/lib/mocks/planItems";

describe("groupByDate", () => {
  it("箱根モック 8 件を 2 日分にグルーピングする", () => {
    const groups = groupByDate(mockPlanItems);
    expect(groups).toHaveLength(2);
    expect(groups[0].dateKey).toBe("2026-06-01");
    expect(groups[1].dateKey).toBe("2026-06-02");
    expect(groups[0].items).toHaveLength(5);
    expect(groups[1].items).toHaveLength(3);
  });

  it("各グループ内は order_index 昇順", () => {
    const groups = groupByDate(mockPlanItems);
    for (const g of groups) {
      const orders = g.items.map((i) => i.order_index);
      expect(orders).toEqual([...orders].sort((a, b) => a - b));
    }
  });

  it("日付を跨ぐアイテム（lodging）は start_time の日付に配置", () => {
    const groups = groupByDate(mockPlanItems);
    const lodging = groups[0].items.find((i) => i.item_type === "lodging");
    expect(lodging).toBeDefined();
    expect(lodging?.id).toBe("i5");
  });

  it("空配列を渡すと空配列を返す", () => {
    expect(groupByDate([])).toEqual([]);
  });
});
