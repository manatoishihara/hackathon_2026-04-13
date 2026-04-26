import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  formatDateRange,
  formatDurationMin,
  formatHHmmJst,
  formatJpy,
  formatMonthDay,
  formatNumber,
  formatVerifiedAt,
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

describe("formatVerifiedAt", () => {
  it("UTC ISO を JST の YYYY-MM-DD HH:mm に変換", () => {
    // 2026-04-26 01:32 UTC = 2026-04-26 10:32 JST
    expect(formatVerifiedAt("2026-04-26T01:32:00Z")).toBe("2026-04-26 10:32");
  });

  it("JST 直接指定の ISO もそのまま JST", () => {
    expect(formatVerifiedAt("2026-04-26T10:32:00+09:00")).toBe("2026-04-26 10:32");
  });

  it("DST 期の UTC でも JST 固定で変換（夏時間がない JST の振る舞い検証）", () => {
    // 北米 DST 中の 2026-07-15 01:32 UTC = JST 10:32
    expect(formatVerifiedAt("2026-07-15T01:32:00Z")).toBe("2026-07-15 10:32");
  });

  it("分が 1 桁でも 2 桁ゼロパディング", () => {
    expect(formatVerifiedAt("2026-04-26T00:05:00Z")).toBe("2026-04-26 09:05");
  });

  it.each<[string | null | undefined, string]>([
    [null, "null"],
    [undefined, "undefined"],
    ["", "empty string"],
    ["not-an-iso", "invalid string"],
  ])('"%s" は "— 不明" を返す (%s)', (input, _label) => {
    expect(formatVerifiedAt(input)).toBe("— 不明");
  });

  describe("環境タイムゾーン非依存（formatter モジュールも再生成）", () => {
    // codex review 2 回目で指摘: VERIFIED_AT_FORMATTER はモジュール読込時に生成されるため、
    // process.env.TZ を変えても同一 formatter を使い続ける。vi.resetModules() + dynamic import で
    // 再構築させると、もし将来 timeZone option を渡し忘れたら test が確実に落ちる保険になる。
    beforeEach(() => {
      vi.resetModules();
      vi.stubEnv("TZ", "America/Los_Angeles");
    });

    afterEach(() => {
      vi.unstubAllEnvs();
    });

    it("LA timezone で formatter を再構築しても JST 固定で変換される", async () => {
      const mod = await import("./format");
      expect(mod.formatVerifiedAt("2026-04-26T01:32:00Z")).toBe("2026-04-26 10:32");
    });
  });
});
