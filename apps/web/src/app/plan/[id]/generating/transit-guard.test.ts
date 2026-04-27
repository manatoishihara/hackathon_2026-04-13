import { describe, expect, it } from "vitest";

import type { FetchTransitStats } from "@/lib/transit";

import { shouldEarlyThrowOnTransit } from "./transit-guard";

/**
 * Phase 1.10 後段 fix（Codex review 2 Blocker 1 反映）:
 * フロント transit が全 pair 失敗（成功経路で `succeeded === 0 && attempted > 0`）の場合
 * は generate を続行せず早期エラー化する。
 */
describe("shouldEarlyThrowOnTransit", () => {
  it("attempted > 0 / succeeded === 0 なら true（全 pair 失敗）", () => {
    const stats: FetchTransitStats = {
      attempted: 40,
      succeeded: 0,
      errors: 40,
      timedOut: 0,
      deadlineReached: false,
    };
    expect(shouldEarlyThrowOnTransit(stats)).toBe(true);
  });

  it("attempted > 0 / succeeded > 0 なら false（部分成功は許容）", () => {
    const stats: FetchTransitStats = {
      attempted: 40,
      succeeded: 5,
      errors: 35,
      timedOut: 0,
      deadlineReached: false,
    };
    expect(shouldEarlyThrowOnTransit(stats)).toBe(false);
  });

  it("attempted === 0 なら false（places 1 件以下で transit 不要、空のまま続行）", () => {
    const stats: FetchTransitStats = {
      attempted: 0,
      succeeded: 0,
      errors: 0,
      timedOut: 0,
      deadlineReached: false,
    };
    expect(shouldEarlyThrowOnTransit(stats)).toBe(false);
  });

  it("attempted > 0 / 全 timeout（succeeded=0）でも true（実質全滅）", () => {
    const stats: FetchTransitStats = {
      attempted: 20,
      succeeded: 0,
      errors: 0,
      timedOut: 20,
      deadlineReached: true,
    };
    expect(shouldEarlyThrowOnTransit(stats)).toBe(true);
  });
});
