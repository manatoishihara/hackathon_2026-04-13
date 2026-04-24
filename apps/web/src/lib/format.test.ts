import { describe, expect, it } from "vitest";

import {
  formatDateRange,
  formatDurationMin,
  formatHHmmJst,
  formatJpy,
  formatMonthDay,
  formatNumber,
} from "./format";

describe("formatJpy", () => {
  it("3 桁区切りで ¥ を付ける", () => {
    expect(formatJpy(48200)).toBe("￥48,200");
  });

  it("0 は ¥0", () => {
    expect(formatJpy(0)).toBe("￥0");
  });
});

describe("formatNumber", () => {
  it("3 桁区切りで整形", () => {
    expect(formatNumber(1234567)).toBe("1,234,567");
  });
});

describe("formatHHmmJst", () => {
  it("ISO datetime を JST の HH:mm に変換", () => {
    expect(formatHHmmJst("2026-06-01T09:00:00+09:00")).toBe("09:00");
  });

  it("UTC の ISO でも JST 基準で整形", () => {
    // 2026-06-01 00:00 UTC = 2026-06-01 09:00 JST
    expect(formatHHmmJst("2026-06-01T00:00:00Z")).toBe("09:00");
  });
});

describe("formatMonthDay", () => {
  it("6月1日 を含む（週も短縮表示）", () => {
    const out = formatMonthDay("2026-06-01T09:00:00+09:00");
    expect(out).toContain("6月1日");
  });
});

describe("formatDateRange", () => {
  it("2 日分のレンジを 6/1 – 6/2 形式で出す", () => {
    expect(formatDateRange("2026-06-01T00:00:00+09:00", "2026-06-02T00:00:00+09:00")).toBe(
      "6/1 – 6/2",
    );
  });
});

describe("formatDurationMin", () => {
  it.each([
    [30, "30分"],
    [45, "45分"],
    [60, "1時間"],
    [75, "1時間15分"],
    [120, "2時間"],
    [125, "2時間5分"],
  ])("%d 分 → %s", (input, expected) => {
    expect(formatDurationMin(input)).toBe(expected);
  });
});
