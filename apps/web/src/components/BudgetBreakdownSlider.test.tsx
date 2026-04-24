import { describe, expect, it } from "vitest";

import { rebalance } from "./BudgetBreakdownSlider";
import type { BudgetBreakdown } from "shared-types";

const INITIAL: BudgetBreakdown = { lodging: 40, meal: 30, activity: 20, transit: 10 };

function sum(b: BudgetBreakdown): number {
  return b.lodging + b.meal + b.activity + b.transit;
}

describe("rebalance", () => {
  it("任意カテゴリを変更しても合計 100% を保つ", () => {
    const next = rebalance(INITIAL, "lodging", 60);
    expect(next.lodging).toBe(60);
    expect(sum(next)).toBe(100);
  });

  it("他カテゴリが全て 0 なら残りを等分配する", () => {
    const zeroOthers: BudgetBreakdown = { lodging: 40, meal: 0, activity: 0, transit: 0 };
    const next = rebalance(zeroOthers, "lodging", 40);
    expect(sum(next)).toBe(100);
    // lodging が 40 なので残り 60 を 3 等分 → 20 + 20 + 20
    expect(next.meal).toBe(20);
    expect(next.activity).toBe(20);
    expect(next.transit).toBe(20);
  });

  it("100 を指定すると他は全て 0 になる", () => {
    const next = rebalance(INITIAL, "meal", 100);
    expect(next.meal).toBe(100);
    expect(next.lodging).toBe(0);
    expect(next.activity).toBe(0);
    expect(next.transit).toBe(0);
    expect(sum(next)).toBe(100);
  });

  it("0 を指定すると他に比例配分される", () => {
    const next = rebalance(INITIAL, "lodging", 0);
    expect(next.lodging).toBe(0);
    expect(sum(next)).toBe(100);
    // meal: 30 / 60 * 100 = 50
    // activity: 20 / 60 * 100 ≈ 33
    // transit: 10 / 60 * 100 ≈ 17
    expect(next.meal).toBeGreaterThanOrEqual(49);
    expect(next.meal).toBeLessThanOrEqual(51);
  });

  it("負数や 100 超を渡しても clamp される", () => {
    const up = rebalance(INITIAL, "lodging", 150);
    expect(up.lodging).toBe(100);
    expect(sum(up)).toBe(100);
    const down = rebalance(INITIAL, "lodging", -20);
    expect(down.lodging).toBe(0);
    expect(sum(down)).toBe(100);
  });
});
