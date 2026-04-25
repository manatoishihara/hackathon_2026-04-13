import { describe, expect, it } from "vitest";

import { planFormSchema } from "./planForm";

const baseValid = {
  title: "箱根温泉旅",
  region: "箱根",
  start_date: "2026-06-01",
  end_date: "2026-06-02",
  departure_point: "新宿駅",
  budget_per_person_jpy: 30000,
  budget_breakdown: { lodging: 40, meal: 30, activity: 20, transit: 10 },
  participants: [
    {
      display_name: "太郎",
      avatar_color: "#D97757",
      wishes_text: "温泉でゆっくり",
      tags: ["温泉"],
      order_index: 0,
    },
    {
      display_name: "花子",
      avatar_color: "#2C5F5D",
      wishes_text: "美味しいもの食べたい",
      tags: ["和食"],
      order_index: 1,
    },
  ],
};

describe("planFormSchema (Phase 2.1: discriminated union for start_mode)", () => {
  it("accepts auto mode with null mode_payload", () => {
    const result = planFormSchema.safeParse({
      ...baseValid,
      start_mode: "auto",
      mode_payload: null,
    });
    expect(result.success).toBe(true);
  });

  it("rejects auto mode with non-null mode_payload", () => {
    const result = planFormSchema.safeParse({
      ...baseValid,
      start_mode: "auto",
      mode_payload: { theme: "onsen" },
    });
    expect(result.success).toBe(false);
  });

  it("accepts anchor mode with valid anchor_place_ids", () => {
    const result = planFormSchema.safeParse({
      ...baseValid,
      start_mode: "anchor",
      mode_payload: { anchor_place_ids: ["ChIJ_one", "ChIJ_two"] },
    });
    expect(result.success).toBe(true);
  });

  it("rejects anchor mode with empty anchor_place_ids", () => {
    const result = planFormSchema.safeParse({
      ...baseValid,
      start_mode: "anchor",
      mode_payload: { anchor_place_ids: [] },
    });
    expect(result.success).toBe(false);
  });

  it("rejects anchor mode with more than 3 ids", () => {
    const result = planFormSchema.safeParse({
      ...baseValid,
      start_mode: "anchor",
      mode_payload: { anchor_place_ids: ["a", "b", "c", "d"] },
    });
    expect(result.success).toBe(false);
  });

  it("rejects anchor mode with empty string id", () => {
    const result = planFormSchema.safeParse({
      ...baseValid,
      start_mode: "anchor",
      mode_payload: { anchor_place_ids: [""] },
    });
    expect(result.success).toBe(false);
  });

  it("rejects anchor mode with null payload", () => {
    const result = planFormSchema.safeParse({
      ...baseValid,
      start_mode: "anchor",
      mode_payload: null,
    });
    expect(result.success).toBe(false);
  });

  it("accepts each of the 6 valid themes", () => {
    for (const theme of [
      "onsen",
      "art",
      "gourmet",
      "nature",
      "history",
      "experience",
    ] as const) {
      const result = planFormSchema.safeParse({
        ...baseValid,
        start_mode: "theme",
        mode_payload: { theme },
      });
      expect(result.success, `theme=${theme} should be valid`).toBe(true);
    }
  });

  it("rejects unknown theme key", () => {
    const result = planFormSchema.safeParse({
      ...baseValid,
      start_mode: "theme",
      mode_payload: { theme: "ramen" },
    });
    expect(result.success).toBe(false);
  });

  it("rejects theme mode with anchor-shaped payload (mismatched)", () => {
    const result = planFormSchema.safeParse({
      ...baseValid,
      start_mode: "theme",
      mode_payload: { anchor_place_ids: ["a"] },
    });
    expect(result.success).toBe(false);
  });

  it("preserves existing date / participants / budget validation", () => {
    // 開始日 > 終了日 は拒否（既存挙動の regression check）
    const result = planFormSchema.safeParse({
      ...baseValid,
      start_date: "2026-06-03",
      end_date: "2026-06-01",
      start_mode: "auto",
      mode_payload: null,
    });
    expect(result.success).toBe(false);
  });
});
