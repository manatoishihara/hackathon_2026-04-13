import { describe, expect, it } from "vitest";

import { computeSpentByCategory } from "./BudgetSummary";
import { mockPlanItems } from "@/lib/mocks/planItems";

describe("computeSpentByCategory", () => {
  it("各カテゴリの合計を計算する（箱根モック）", () => {
    const spent = computeSpentByCategory(mockPlanItems);
    // transit: 2470*2 + 320 (transit_to_next from i1) = 5260
    expect(spent.transit).toBe(5260);
    // meal: 1800 + 2500 = 4300
    expect(spent.meal).toBe(4300);
    // activity: 2000 + 1500 + 0 = 3500
    expect(spent.activity).toBe(3500);
    // lodging: 12000
    expect(spent.lodging).toBe(12000);
  });

  it("空配列は全カテゴリ 0", () => {
    const spent = computeSpentByCategory([]);
    expect(spent).toEqual({ lodging: 0, meal: 0, activity: 0, transit: 0 });
  });
});
