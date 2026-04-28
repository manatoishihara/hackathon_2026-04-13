import { describe, expect, it } from "vitest";

import {
  type BudgetBreakdown,
  getEvidenceBadgeInfo,
  isValidBudgetBreakdown,
  isValidParticipantCount,
} from "./index";

describe("isValidBudgetBreakdown", () => {
  it("合計がちょうど 100 なら true", () => {
    const b: BudgetBreakdown = { lodging: 40, meal: 30, activity: 20, transit: 10 };
    expect(isValidBudgetBreakdown(b)).toBe(true);
  });

  it("合計が 99 や 101 なら false", () => {
    expect(isValidBudgetBreakdown({ lodging: 40, meal: 30, activity: 20, transit: 9 })).toBe(false);
    expect(isValidBudgetBreakdown({ lodging: 41, meal: 30, activity: 20, transit: 10 })).toBe(false);
  });

  it("負の値や 100 超の値を含むと false", () => {
    expect(isValidBudgetBreakdown({ lodging: -10, meal: 40, activity: 40, transit: 30 })).toBe(false);
    expect(isValidBudgetBreakdown({ lodging: 110, meal: 0, activity: 0, transit: 0 })).toBe(false);
  });

  it("NaN / Infinity を含むと false", () => {
    expect(isValidBudgetBreakdown({ lodging: NaN, meal: 0, activity: 0, transit: 100 })).toBe(false);
    expect(isValidBudgetBreakdown({ lodging: Infinity, meal: 0, activity: 0, transit: 0 })).toBe(false);
  });

  it("極端配分（宿泊 80%）でも合計 100 なら true", () => {
    expect(isValidBudgetBreakdown({ lodging: 80, meal: 10, activity: 5, transit: 5 })).toBe(true);
  });
});

describe("isValidParticipantCount", () => {
  it("2〜5 は true", () => {
    [2, 3, 4, 5].forEach((n) => expect(isValidParticipantCount(n)).toBe(true));
  });

  it("1 / 6 は false", () => {
    expect(isValidParticipantCount(1)).toBe(false);
    expect(isValidParticipantCount(6)).toBe(false);
  });

  it("小数や負数は false", () => {
    expect(isValidParticipantCount(2.5)).toBe(false);
    expect(isValidParticipantCount(-1)).toBe(false);
  });
});

describe("getEvidenceBadgeInfo", () => {
  it("verified + sources[0] があればその出典名をラベルに使う", () => {
    const info = getEvidenceBadgeInfo("verified", ["Google Places", "楽天トラベル"]);
    expect(info.variant).toBe("verified");
    expect(info.label).toBe("Google Places");
    expect(info.colorToken).toBe("--color-evidence-verified");
  });

  it("verified + sources 空なら汎用ラベル", () => {
    const info = getEvidenceBadgeInfo("verified", []);
    expect(info.label).toBe("検証済み");
  });

  it("estimated は固定ラベル + estimated カラー", () => {
    const info = getEvidenceBadgeInfo("estimated", ["LLM 推定"]);
    expect(info.variant).toBe("estimated");
    expect(info.label).toBe("推定");
    expect(info.colorToken).toBe("--color-evidence-estimated");
  });

  it("unknown は固定ラベル + unknown カラー", () => {
    const info = getEvidenceBadgeInfo("unknown", []);
    expect(info.variant).toBe("unknown");
    expect(info.label).toBe("不明");
    expect(info.colorToken).toBe("--color-evidence-unknown");
  });
});
