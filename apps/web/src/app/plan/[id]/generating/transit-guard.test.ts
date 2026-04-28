import { describe, expect, it } from "vitest";

import type { FetchTransitStats } from "@/lib/transit";

import { shouldEarlyThrowOnTransit } from "./transit-guard";

/**
 * Phase 2 polish v3 (Codex review 3 Major + review 5 Major 反映):
 * フロント transit が
 *   (a) 全滅 (`succeeded === 0`)
 *   (b) 絶対下限 `MIN_SUCCEEDED_FOR_GENERATE = 10` 未満
 *   (c) 比率下限 `MIN_COVERAGE_RATIO = 0.3` 未満
 *   (d) `attempted === 0 && placeCount > 1` (距離フィルタで pair 全落ち抜け穴)
 * のいずれかなら deadline 関係なく早期エラー化する。
 */
describe("shouldEarlyThrowOnTransit", () => {
  it("attempted > 0 / succeeded === 0 なら true（全滅）", () => {
    const stats: FetchTransitStats = {
      attempted: 40,
      succeeded: 0,
      errors: 40,
      timedOut: 0,
      deadlineReached: false,
    };
    expect(shouldEarlyThrowOnTransit(stats, 12)).toBe(true);
  });

  it("placeCount <= 1 なら false（places 1 件以下で transit 不要、空のまま続行）", () => {
    const stats: FetchTransitStats = {
      attempted: 0,
      succeeded: 0,
      errors: 0,
      timedOut: 0,
      deadlineReached: false,
    };
    expect(shouldEarlyThrowOnTransit(stats, 1)).toBe(false);
    expect(shouldEarlyThrowOnTransit(stats, 0)).toBe(false);
  });

  it("attempted === 0 && placeCount > 1 なら true（距離フィルタで pair 全落ち、Codex review 5 Major）", () => {
    const stats: FetchTransitStats = {
      attempted: 0,
      succeeded: 0,
      errors: 0,
      timedOut: 0,
      deadlineReached: false,
    };
    // places は複数あるのに pair 0 件 = 距離フィルタが効きすぎ or places 散らばりすぎ
    expect(shouldEarlyThrowOnTransit(stats, 12)).toBe(true);
    expect(shouldEarlyThrowOnTransit(stats, 2)).toBe(true);
  });

  it("attempted > 0 / 全 timeout（succeeded=0）でも true（実質全滅）", () => {
    const stats: FetchTransitStats = {
      attempted: 20,
      succeeded: 0,
      errors: 0,
      timedOut: 20,
      deadlineReached: true,
    };
    expect(shouldEarlyThrowOnTransit(stats, 12)).toBe(true);
  });

  it("succeeded=9, attempted=20 (45%) は絶対下限未満で true（Codex review 2 Major: 比率高くても少数バッチ throw）", () => {
    const stats: FetchTransitStats = {
      attempted: 20,
      succeeded: 9,
      errors: 11,
      timedOut: 0,
      deadlineReached: false,
    };
    expect(shouldEarlyThrowOnTransit(stats, 12)).toBe(true);
  });

  it("succeeded=10, attempted=40 (25%) は比率下限未満で true（絶対数 OK でも比率で reject）", () => {
    const stats: FetchTransitStats = {
      attempted: 40,
      succeeded: 10,
      errors: 30,
      timedOut: 0,
      deadlineReached: false,
    };
    expect(shouldEarlyThrowOnTransit(stats, 12)).toBe(true);
  });

  it("succeeded=12, attempted=40 (30%) は比率下限ぎりぎりで false（境界値、両条件 OK）", () => {
    const stats: FetchTransitStats = {
      attempted: 40,
      succeeded: 12,
      errors: 28,
      timedOut: 0,
      deadlineReached: false,
    };
    expect(shouldEarlyThrowOnTransit(stats, 12)).toBe(false);
  });

  it("succeeded=20, attempted=40 (50%) で deadline 未到達でも false（健全 coverage）", () => {
    const stats: FetchTransitStats = {
      attempted: 40,
      succeeded: 20,
      errors: 20,
      timedOut: 0,
      deadlineReached: false,
    };
    expect(shouldEarlyThrowOnTransit(stats, 12)).toBe(false);
  });

  it("succeeded=10, attempted=20 (50%) で deadline 到達でも false（Codex review 3: deadline 依存撤廃）", () => {
    const stats: FetchTransitStats = {
      attempted: 20,
      succeeded: 10,
      errors: 5,
      timedOut: 5,
      deadlineReached: true,
    };
    expect(shouldEarlyThrowOnTransit(stats, 12)).toBe(false);
  });
});
