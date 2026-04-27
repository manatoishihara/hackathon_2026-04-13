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
  // Phase 2 polish: 必須化
  transport_mode: "all_modes" as const,
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

  // Phase 2 polish (2026-04-27): transport_mode（移動手段指定）
  it("rejects when transport_mode is omitted (form must always set it)", () => {
    // form の DEFAULT_VALUES で必ず "all_modes" がセットされるため、ここでは
    // schema 側で省略されたら fail するのが正しい挙動。
    const { transport_mode: _omitted, ...withoutTransport } = baseValid;
    const result = planFormSchema.safeParse({
      ...withoutTransport,
      start_mode: "auto",
      mode_payload: null,
    });
    expect(result.success).toBe(false);
  });

  it("accepts transport_mode='public_transit_only' explicitly", () => {
    const result = planFormSchema.safeParse({
      ...baseValid,
      start_mode: "auto",
      mode_payload: null,
      transport_mode: "public_transit_only",
    });
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.transport_mode).toBe("public_transit_only");
    }
  });

  it("rejects unknown transport_mode value", () => {
    const result = planFormSchema.safeParse({
      ...baseValid,
      start_mode: "auto",
      mode_payload: null,
      transport_mode: "bicycle_only",
    });
    expect(result.success).toBe(false);
  });

  it("transport_mode flows through anchor and theme variants", () => {
    const anchorResult = planFormSchema.safeParse({
      ...baseValid,
      start_mode: "anchor",
      mode_payload: { anchor_place_ids: ["ChIJ_one"] },
      transport_mode: "public_transit_only",
    });
    expect(anchorResult.success).toBe(true);
    const themeResult = planFormSchema.safeParse({
      ...baseValid,
      start_mode: "theme",
      mode_payload: { theme: "onsen" },
      transport_mode: "public_transit_only",
    });
    expect(themeResult.success).toBe(true);
  });
});
