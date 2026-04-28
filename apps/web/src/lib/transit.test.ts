/* eslint-disable @typescript-eslint/no-explicit-any -- partial Google Maps の mock 値で `any` キャストが必要 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { EvidencePlacesPlaceSummary } from "shared-types";

// setOptions/importLibrary を差し替えて実 Google API を呼ばない。
// installMockGoogle が globalThis.google の routes ライブラリ（DirectionsService）を
// 仕込むので、importLibrary はその routes 名前空間を返せば良い。
vi.mock("@googlemaps/js-api-loader", () => ({
  setOptions: vi.fn(),
  importLibrary: vi.fn(async () => {
    const g = (globalThis as unknown as { google?: { maps: { DirectionsService: unknown } } }).google;
    return { DirectionsService: g?.maps.DirectionsService };
  }),
}));

import {
  _resetLoaderForTests,
  CANONICAL_DEPARTURE_TIMES,
  TransitConfigError,
  fetchTransitMatrix,
  haversineKm,
  parseDirectionsResult,
  selectPairs,
} from "./transit";

// ==============================
// テスト用データ
// ==============================

function place(
  id: string,
  lat: number,
  lng: number,
  name = id,
): EvidencePlacesPlaceSummary {
  return { place_id: id, name, lat, lng };
}

// ==============================
// haversineKm
// ==============================

describe("haversineKm", () => {
  it("東京駅 → 新宿駅 はおよそ 6km", () => {
    const d = haversineKm(
      { lat: 35.681236, lng: 139.767125 },
      { lat: 35.690921, lng: 139.700258 },
    );
    expect(d).toBeGreaterThan(5);
    expect(d).toBeLessThan(8);
  });

  it("同地点は 0", () => {
    expect(haversineKm({ lat: 35, lng: 139 }, { lat: 35, lng: 139 })).toBeCloseTo(0, 5);
  });

  it("十分遠距離は 100km 以上", () => {
    const d = haversineKm({ lat: 35.68, lng: 139.76 }, { lat: 34.69, lng: 135.50 });
    expect(d).toBeGreaterThan(300); // 東京〜大阪
  });
});

// ==============================
// selectPairs
// ==============================

describe("selectPairs", () => {
  it("places が 1 件未満なら空配列", () => {
    expect(selectPairs([], 10, 20)).toEqual([]);
    expect(selectPairs([place("p1", 35, 139)], 10, 20)).toEqual([]);
  });

  it("近い 2 点だけのとき 1 ペア返す", () => {
    const a = place("a", 35.0, 139.0);
    const b = place("b", 35.01, 139.0); // ~1.1km
    const pairs = selectPairs([a, b], 10, 20);
    expect(pairs).toHaveLength(1);
  });

  it("遠すぎる pair は除外", () => {
    const a = place("a", 35.0, 139.0);
    const b = place("b", 36.0, 140.0); // ~140km
    expect(selectPairs([a, b], 10, 20)).toEqual([]);
  });

  it("maxPairs 以上は取らない（距離順で切る）", () => {
    const places = [
      place("a", 35.0, 139.0),
      place("b", 35.001, 139.0),
      place("c", 35.002, 139.0),
      place("d", 35.003, 139.0),
      place("e", 35.004, 139.0),
    ];
    const pairs = selectPairs(places, 10, 2);
    expect(pairs).toHaveLength(2);
  });

  it("各 place が最低 1 接続を持つ（被覆性）", () => {
    // 近傍クラスタ + 孤立寄り（ただし maxKm 内）の place
    const places = [
      place("a", 35.0, 139.0),
      place("b", 35.001, 139.0),
      place("c", 35.002, 139.0),
      place("d", 35.05, 139.0), // 5km ほど離れている
    ];
    const pairs = selectPairs(places, 10, 3);
    const idsInPairs = new Set<string>();
    for (const [x, y] of pairs) {
      idsInPairs.add(x.place_id);
      idsInPairs.add(y.place_id);
    }
    // "d" も必ず含まれる（被覆保証）
    expect(idsInPairs.has("d")).toBe(true);
  });

  it("重複ペアは返さない", () => {
    const places = [
      place("a", 35.0, 139.0),
      place("b", 35.001, 139.0),
    ];
    const pairs = selectPairs(places, 10, 20);
    expect(pairs).toHaveLength(1);
  });
});

// ==============================
// parseDirectionsResult
// ==============================

function fakeResult(partial: {
  durationSec?: number;
  fare?: { currency: string; value: number };
  transitLineName?: string;
  vehicleType?: string;
  departureValue?: Date | null;
  noRoutes?: boolean;
}): google.maps.DirectionsResult {
  if (partial.noRoutes) {
    return { routes: [] } as unknown as google.maps.DirectionsResult;
  }
  const steps: unknown[] = [];
  if (partial.transitLineName) {
    steps.push({
      travel_mode: "TRANSIT",
      transit: {
        line: {
          name: partial.transitLineName,
          vehicle: { type: partial.vehicleType ?? "HEAVY_RAIL" },
        },
        departure_time: partial.departureValue
          ? { value: partial.departureValue, text: "dummy" }
          : undefined,
      },
    });
  } else {
    steps.push({ travel_mode: "WALKING" });
  }
  return {
    routes: [
      {
        fare: partial.fare,
        legs: [
          {
            duration: { value: partial.durationSec ?? 1800, text: "dummy" },
            steps,
          },
        ],
      },
    ],
  } as unknown as google.maps.DirectionsResult;
}

describe("parseDirectionsResult", () => {
  it("正常な transit レスポンスを edge に整形", () => {
    const edge = parseDirectionsResult(
      fakeResult({
        durationSec: 5400, // 90 min
        fare: { currency: "JPY", value: 2330 },
        transitLineName: "小田急線 特急はこね",
        vehicleType: "HEAVY_RAIL",
        departureValue: new Date("2026-06-01T09:15:00+09:00"),
      }),
      "A",
      "B",
      new Date("2026-06-01T09:00:00+09:00"),
      "TRANSIT",
    );
    expect(edge).not.toBeNull();
    expect(edge!.duration_min).toBe(90);
    expect(edge!.fare_jpy).toBe(2330);
    expect(edge!.mode).toBe("train");
    expect(edge!.route_summary).toBe("小田急線 特急はこね");
    // departure_time (09:15) は canonical 8 点と merge して 9 件で sort 済み
    expect(edge!.candidate_departures).toContain("09:15");
    expect(edge!.candidate_departures).toContain("00:00");
    expect(edge!.candidate_departures).toContain("23:59");
    expect(edge!.candidate_departures.length).toBe(9);
  });

  it("transit step が無ければ walk + 徒歩 + requested departure にフォールバック", () => {
    const edge = parseDirectionsResult(
      fakeResult({ durationSec: 600 }),
      "A",
      "B",
      new Date("2026-06-01T08:30:00+09:00"),
      "TRANSIT",
    );
    expect(edge).not.toBeNull();
    expect(edge!.mode).toBe("walk");
    expect(edge!.route_summary).toBe("徒歩");
    // requested 08:30 は canonical と merge → 9 件
    expect(edge!.candidate_departures).toContain("08:30");
    expect(edge!.candidate_departures.length).toBe(9);
  });

  it("duration 欠損 / 負数 / 24h 超は null", () => {
    expect(
      parseDirectionsResult(
        { routes: [{ legs: [{ duration: undefined }] }] } as any,
        "A",
        "B",
        new Date(),
        "TRANSIT",
      ),
    ).toBeNull();
    expect(
      parseDirectionsResult(
        { routes: [{ legs: [{ duration: { value: -10, text: "" } }] }] } as any,
        "A",
        "B",
        new Date(),
        "TRANSIT",
      ),
    ).toBeNull();
    expect(
      parseDirectionsResult(
        { routes: [{ legs: [{ duration: { value: 100_000, text: "" } }] }] } as any,
        "A",
        "B",
        new Date(),
        "TRANSIT",
      ),
    ).toBeNull();
  });

  it("非 JPY の fare は無視（null になる）", () => {
    const edge = parseDirectionsResult(
      fakeResult({
        durationSec: 600,
        fare: { currency: "USD", value: 5 },
        transitLineName: "Muni Bus",
        vehicleType: "BUS",
      }),
      "A",
      "B",
      new Date("2026-06-01T09:00:00+09:00"),
      "TRANSIT",
    );
    expect(edge!.fare_jpy).toBeNull();
    expect(edge!.mode).toBe("bus");
  });

  it("route_summary は 120 文字で clamp", () => {
    const longName = "あ".repeat(500);
    const edge = parseDirectionsResult(
      fakeResult({
        durationSec: 600,
        transitLineName: longName,
        vehicleType: "SUBWAY",
      }),
      "A",
      "B",
      new Date("2026-06-01T09:00:00+09:00"),
      "TRANSIT",
    );
    expect(edge!.route_summary.length).toBe(120);
  });
});

// ==============================
// parseDirectionsResult — requestedMode 分岐
// ==============================

describe("parseDirectionsResult — requestedMode", () => {
  it("requestedMode='DRIVING' なら default mode='car' / route_summary='車'", () => {
    const result = {
      routes: [
        {
          legs: [
            {
              duration: { value: 1800, text: "" },
              steps: [{ travel_mode: "DRIVING" }],
            },
          ],
        },
      ],
    } as unknown as google.maps.DirectionsResult;
    const edge = parseDirectionsResult(
      result,
      "A",
      "B",
      new Date("2026-06-01T09:00:00+09:00"),
      "DRIVING",
    );
    expect(edge!.mode).toBe("car");
    expect(edge!.route_summary).toBe("車");
    expect(edge!.duration_min).toBe(30);
  });

  it("requestedMode='WALKING' なら default mode='walk' / route_summary='徒歩'", () => {
    const result = {
      routes: [
        {
          legs: [
            {
              duration: { value: 600, text: "" },
              steps: [{ travel_mode: "WALKING" }],
            },
          ],
        },
      ],
    } as unknown as google.maps.DirectionsResult;
    const edge = parseDirectionsResult(
      result,
      "A",
      "B",
      new Date("2026-06-01T08:30:00+09:00"),
      "WALKING",
    );
    expect(edge!.mode).toBe("walk");
    expect(edge!.route_summary).toBe("徒歩");
  });

  it("requestedMode='TRANSIT' で transit step あり → 既存挙動（line name 抽出）", () => {
    const edge = parseDirectionsResult(
      fakeResult({
        durationSec: 5400,
        transitLineName: "小田急線 特急はこね",
        vehicleType: "HEAVY_RAIL",
      }),
      "A",
      "B",
      new Date("2026-06-01T09:00:00+09:00"),
      "TRANSIT",
    );
    expect(edge!.mode).toBe("train");
    expect(edge!.route_summary).toBe("小田急線 特急はこね");
  });

  it("requestedMode='DRIVING' でも transit step が紛れていたら無視する", () => {
    // DRIVING 要求の結果に万一 TRANSIT step が混じっても上書きしない
    const result = {
      routes: [
        {
          legs: [
            {
              duration: { value: 1200, text: "" },
              steps: [
                {
                  travel_mode: "TRANSIT",
                  transit: { line: { name: "ノイズ", vehicle: { type: "BUS" } } },
                },
                { travel_mode: "DRIVING" },
              ],
            },
          ],
        },
      ],
    } as unknown as google.maps.DirectionsResult;
    const edge = parseDirectionsResult(
      result,
      "A",
      "B",
      new Date("2026-06-01T09:00:00+09:00"),
      "DRIVING",
    );
    expect(edge!.mode).toBe("car");
    expect(edge!.route_summary).toBe("車");
  });
});

// ==============================
// fetchTransitMatrix — 並列 / タイムアウト / 締切 / fail-soft
// ==============================

type RouteFn = (req: google.maps.DirectionsRequest) => Promise<google.maps.DirectionsResult>;

function installMockGoogle(routeFn: RouteFn) {
  (globalThis as unknown as { google: unknown }).google = {
    maps: {
      TravelMode: { TRANSIT: "TRANSIT", WALKING: "WALKING", DRIVING: "DRIVING" },
      DirectionsService: class {
        route = routeFn;
      },
    },
  };
}

function uninstallMockGoogle() {
  delete (globalThis as unknown as { google?: unknown }).google;
}

describe("fetchTransitMatrix", () => {
  beforeEach(() => {
    _resetLoaderForTests();
    process.env.NEXT_PUBLIC_GOOGLE_MAPS_BROWSER_KEY = "pk-fake";
  });

  afterEach(() => {
    uninstallMockGoogle();
    delete process.env.NEXT_PUBLIC_GOOGLE_MAPS_BROWSER_KEY;
  });

  it("places が 2 件未満なら空結果（SDK は呼ばない）", async () => {
    installMockGoogle(async () => {
      throw new Error("should not be called");
    });
    const result = await fetchTransitMatrix([], new Date());
    expect(result.edges).toEqual([]);
    expect(result.stats.attempted).toBe(0);
  });

  it("API key 未設定で TransitConfigError", async () => {
    delete process.env.NEXT_PUBLIC_GOOGLE_MAPS_BROWSER_KEY;
    installMockGoogle(async () => ({ routes: [] }) as any);
    await expect(
      fetchTransitMatrix(
        [place("a", 35.0, 139.0), place("b", 35.001, 139.0)],
        new Date("2026-06-01T09:00:00+09:00"),
      ),
    ).rejects.toBeInstanceOf(TransitConfigError);
  });

  it("有向 2 方向を呼ぶ（A→B と B→A で 2 回）", async () => {
    const calls: string[] = [];
    installMockGoogle(async (req) => {
      const originId =
        typeof req.origin === "object" && req.origin && "placeId" in req.origin
          ? (req.origin as { placeId: string }).placeId
          : "?";
      const destId =
        typeof req.destination === "object" &&
        req.destination &&
        "placeId" in req.destination
          ? (req.destination as { placeId: string }).placeId
          : "?";
      calls.push(`${originId}->${destId}`);
      return fakeResult({
        durationSec: 1200,
        transitLineName: "テスト線",
        vehicleType: "SUBWAY",
      });
    });
    const result = await fetchTransitMatrix(
      [place("a", 35.0, 139.0), place("b", 35.001, 139.0)],
      new Date("2026-06-01T09:00:00+09:00"),
    );
    expect(calls.sort()).toEqual(["a->b", "b->a"]);
    expect(result.stats.attempted).toBe(2);
    expect(result.stats.succeeded).toBe(2);
    expect(result.edges).toHaveLength(2);
  });

  it("個別エラーは fail-soft（stats.errors を加算、他のエッジは返す）", async () => {
    const places = [
      place("a", 35.0, 139.0),
      place("b", 35.001, 139.0),
      place("c", 35.002, 139.0),
    ];
    installMockGoogle(async (req) => {
      const destId =
        typeof req.destination === "object" && req.destination && "placeId" in req.destination
          ? (req.destination as { placeId: string }).placeId
          : "?";
      if (destId === "b") throw new Error("ZERO_RESULTS for b");
      return fakeResult({ durationSec: 600, transitLineName: "テスト", vehicleType: "SUBWAY" });
    });
    const result = await fetchTransitMatrix(places, new Date("2026-06-01T09:00:00+09:00"));
    expect(result.stats.errors).toBeGreaterThan(0);
    expect(result.stats.succeeded).toBeGreaterThan(0);
    expect(result.edges.every((e) => e.to_place_id !== "b")).toBe(true);
  });

  it("タイムアウトは stats.timedOut に加算（fail-soft）", async () => {
    installMockGoogle(
      () =>
        new Promise((resolve) => {
          setTimeout(
            () => resolve(fakeResult({ durationSec: 60, transitLineName: "線", vehicleType: "SUBWAY" })),
            5000,
          );
        }),
    );
    const result = await fetchTransitMatrix(
      [place("a", 35.0, 139.0), place("b", 35.001, 139.0)],
      new Date("2026-06-01T09:00:00+09:00"),
      { perCallTimeoutMs: 50, globalDeadlineMs: 2000 },
    );
    expect(result.stats.timedOut).toBeGreaterThan(0);
    expect(result.stats.succeeded).toBe(0);
  });

  it("globalDeadline 到達で新規バッチ投入停止、途中打ち切り", async () => {
    const places = Array.from({ length: 6 }, (_, i) =>
      place(`p${i}`, 35.0 + i * 0.001, 139.0),
    );
    // 6 places なら undirected ペア 20 cap 以下で directed 10+ になる
    installMockGoogle(
      () =>
        new Promise((resolve) => {
          setTimeout(
            () =>
              resolve(
                fakeResult({
                  durationSec: 600,
                  transitLineName: "テスト",
                  vehicleType: "SUBWAY",
                }),
              ),
            40,
          );
        }),
    );
    const result = await fetchTransitMatrix(
      places,
      new Date("2026-06-01T09:00:00+09:00"),
      { perCallTimeoutMs: 200, globalDeadlineMs: 80, parallelism: 2, maxPairs: 20 },
    );
    expect(result.stats.deadlineReached).toBe(true);
    // directed 合計は 10+ だが、80ms 締切で 2 並列 x ~40ms × 数バッチしか完了しない
    expect(result.stats.attempted).toBeLessThan(20); // 全部はやっていない
  });

  it("parallelism=0 を渡しても infinite loop にならない（1 に clamp）", async () => {
    installMockGoogle(async () =>
      fakeResult({ durationSec: 600, transitLineName: "T", vehicleType: "SUBWAY" }),
    );
    const result = await fetchTransitMatrix(
      [place("a", 35.0, 139.0), place("b", 35.001, 139.0)],
      new Date("2026-06-01T09:00:00+09:00"),
      { parallelism: 0 },
    );
    expect(result.stats.attempted).toBe(2);
    expect(result.stats.succeeded).toBe(2);
  });

  it("importLibrary 失敗後に singleton をクリアして再試行可能", async () => {
    const { importLibrary } = await import("@googlemaps/js-api-loader");
    const mocked = vi.mocked(importLibrary);
    // 1 回目: reject
    mocked.mockRejectedValueOnce(new Error("network down"));
    await expect(
      fetchTransitMatrix(
        [place("a", 35.0, 139.0), place("b", 35.001, 139.0)],
        new Date(),
      ),
    ).rejects.toThrow("network down");
    // 2 回目: 成功（前回の rejected singleton が残っていたら再試行できない）
    installMockGoogle(async () =>
      fakeResult({ durationSec: 600, transitLineName: "T", vehicleType: "SUBWAY" }),
    );
    mocked.mockResolvedValueOnce({
      DirectionsService: (globalThis as unknown as { google: { maps: { DirectionsService: unknown } } })
        .google.maps.DirectionsService,
    } as unknown as google.maps.RoutesLibrary);
    const result = await fetchTransitMatrix(
      [place("a", 35.0, 139.0), place("b", 35.001, 139.0)],
      new Date("2026-06-01T09:00:00+09:00"),
    );
    expect(result.stats.succeeded).toBe(2);
  });
});

// ==============================
// parseDirectionsResult — canonical candidate_departures (Phase 1.10 後段 fix)
// ==============================

describe("parseDirectionsResult — canonical candidate_departures", () => {
  it("CANONICAL_DEPARTURE_TIMES は 8 点で sort 済み", () => {
    expect(CANONICAL_DEPARTURE_TIMES).toEqual([
      "00:00",
      "06:00",
      "09:00",
      "12:00",
      "15:00",
      "18:00",
      "21:00",
      "23:59",
    ]);
  });

  it("observed 時刻が canonical 外なら 9 件返す（8 canonical + observed、HH:mm sort）", () => {
    // departureValue が 13:54 (canonical 外) → merge 後 9 件
    const edge = parseDirectionsResult(
      fakeResult({
        durationSec: 600,
        transitLineName: "テスト線",
        vehicleType: "SUBWAY",
        departureValue: new Date("2026-06-01T13:54:00+09:00"),
      }),
      "A",
      "B",
      new Date("2026-06-01T09:00:00+09:00"),
      "TRANSIT",
    );
    expect(edge!.candidate_departures).toEqual([
      "00:00",
      "06:00",
      "09:00",
      "12:00",
      "13:54",
      "15:00",
      "18:00",
      "21:00",
      "23:59",
    ]);
  });

  it("observed 時刻が canonical (例 09:00) なら 8 件返す（dedup）", () => {
    const edge = parseDirectionsResult(
      fakeResult({
        durationSec: 600,
        transitLineName: "テスト線",
        vehicleType: "SUBWAY",
        departureValue: new Date("2026-06-01T09:00:00+09:00"),
      }),
      "A",
      "B",
      new Date("2026-06-01T09:00:00+09:00"),
      "TRANSIT",
    );
    expect(edge!.candidate_departures).toEqual([
      "00:00",
      "06:00",
      "09:00",
      "12:00",
      "15:00",
      "18:00",
      "21:00",
      "23:59",
    ]);
  });

  it("transit step なし (walk only) は requestedDeparture を observed として merge", () => {
    const edge = parseDirectionsResult(
      fakeResult({ durationSec: 600 }),
      "A",
      "B",
      new Date("2026-06-01T08:30:00+09:00"),
      "TRANSIT",
    );
    expect(edge!.candidate_departures).toContain("08:30");
    expect(edge!.candidate_departures).toContain("00:00");
    expect(edge!.candidate_departures).toContain("23:59");
    expect(edge!.candidate_departures.length).toBe(9);
  });

  it("候補配列は HH:mm 順 sort されている (辞書順 = 時刻順)", () => {
    const edge = parseDirectionsResult(
      fakeResult({
        durationSec: 600,
        transitLineName: "テスト線",
        vehicleType: "SUBWAY",
        departureValue: new Date("2026-06-01T13:54:00+09:00"),
      }),
      "A",
      "B",
      new Date("2026-06-01T09:00:00+09:00"),
      "TRANSIT",
    );
    const sorted = [...edge!.candidate_departures].sort();
    expect(edge!.candidate_departures).toEqual(sorted);
  });

  it("max 10 要素以内 (Pydantic ClientTransitEdge.candidate_departures max_length=10)", () => {
    const edge = parseDirectionsResult(
      fakeResult({
        durationSec: 600,
        transitLineName: "テスト線",
        vehicleType: "SUBWAY",
        departureValue: new Date("2026-06-01T13:54:00+09:00"),
      }),
      "A",
      "B",
      new Date("2026-06-01T09:00:00+09:00"),
      "TRANSIT",
    );
    expect(edge!.candidate_departures.length).toBeLessThanOrEqual(10);
  });
});

describe("formatHHmm (JST 固定)", () => {
  it("ブラウザ TZ に関係なく JST の HH:mm を返す", async () => {
    // 2026-06-01T00:00:00Z は JST で 09:00 → canonical (09:00 含む) と一致 → 8 件
    const utcMidnight = new Date("2026-06-01T00:00:00Z");
    const edge = parseDirectionsResult(
      fakeResult({ durationSec: 600 }),
      "A",
      "B",
      utcMidnight,
      "TRANSIT",
    );
    expect(edge!.candidate_departures).toContain("09:00");
    expect(edge!.candidate_departures.length).toBe(8);
  });

  it("transit step の departure_time を JST でフォーマット", () => {
    // UTC 23:00 は JST 翌日 08:00（canonical 外） → merge 後 9 件
    const transitDeparture = new Date("2026-06-01T23:00:00Z");
    const edge = parseDirectionsResult(
      fakeResult({
        durationSec: 600,
        transitLineName: "線",
        vehicleType: "SUBWAY",
        departureValue: transitDeparture,
      }),
      "A",
      "B",
      new Date("2026-06-01T10:00:00Z"),
      "TRANSIT",
    );
    expect(edge!.candidate_departures).toContain("08:00");
    expect(edge!.candidate_departures.length).toBe(9);
  });
});

describe("leg.fare fallback", () => {
  it("route.fare 欠損時は leg.fare を使う（@types に無いが runtime には存在）", () => {
    const result = {
      routes: [
        {
          legs: [
            {
              duration: { value: 1200, text: "" },
              fare: { currency: "JPY", value: 480 },
              steps: [
                {
                  travel_mode: "TRANSIT",
                  transit: {
                    line: { name: "バス", vehicle: { type: "BUS" } },
                  },
                },
              ],
            },
          ],
        },
      ],
    } as unknown as google.maps.DirectionsResult;
    const edge = parseDirectionsResult(result, "A", "B", new Date(), "TRANSIT");
    expect(edge!.fare_jpy).toBe(480);
    expect(edge!.mode).toBe("bus");
  });
});

// ==============================
// fetchTransitMatrix — fallback chain (TRANSIT → WALKING / DRIVING)
// ==============================

describe("fetchTransitMatrix — fallback chain", () => {
  beforeEach(() => {
    _resetLoaderForTests();
    process.env.NEXT_PUBLIC_GOOGLE_MAPS_BROWSER_KEY = "pk-fake";
  });

  afterEach(() => {
    uninstallMockGoogle();
    delete process.env.NEXT_PUBLIC_GOOGLE_MAPS_BROWSER_KEY;
  });

  it("TRANSIT 即成功 → WALKING / DRIVING は呼ばない、edges mode='train'", async () => {
    const calls: string[] = [];
    installMockGoogle(async (req) => {
      const mode = String(req.travelMode);
      calls.push(mode);
      // TRANSIT で必ず成功
      return fakeResult({
        durationSec: 1200,
        transitLineName: "小田急線",
        vehicleType: "HEAVY_RAIL",
      });
    });
    const result = await fetchTransitMatrix(
      [place("a", 35.0, 139.0), place("b", 35.001, 139.0)],
      new Date("2026-06-01T09:00:00+09:00"),
    );
    expect(result.stats.succeeded).toBe(2);
    expect(calls).toEqual(["TRANSIT", "TRANSIT"]);
    expect(result.edges.every((e) => e.mode === "train")).toBe(true);
  });

  it("距離 ≤ 2km で TRANSIT 失敗 → WALKING にフォールバック、edges mode='walk'", async () => {
    const calls: string[] = [];
    installMockGoogle(async (req) => {
      const mode = String(req.travelMode);
      calls.push(mode);
      if (mode === "TRANSIT") throw new Error("DIRECTIONS_ROUTE: ZERO_RESULTS");
      // WALKING で成功
      return fakeResult({ durationSec: 600 });
    });
    const result = await fetchTransitMatrix(
      [place("a", 35.0, 139.0), place("b", 35.001, 139.0)], // ~0.1km
      new Date("2026-06-01T09:00:00+09:00"),
    );
    expect(result.stats.attempted).toBe(2);
    expect(result.stats.succeeded).toBe(2);
    expect(calls.filter((c) => c === "TRANSIT")).toHaveLength(2);
    expect(calls.filter((c) => c === "WALKING")).toHaveLength(2);
    expect(result.edges.every((e) => e.mode === "walk")).toBe(true);
  });

  it("距離 ≤ 2km で TRANSIT, WALKING 失敗 → DRIVING、edges mode='car'", async () => {
    const calls: string[] = [];
    installMockGoogle(async (req) => {
      const mode = String(req.travelMode);
      calls.push(mode);
      if (mode === "TRANSIT" || mode === "WALKING") {
        throw new Error("ZERO_RESULTS");
      }
      // DRIVING
      return fakeResult({ durationSec: 1800 });
    });
    const result = await fetchTransitMatrix(
      [place("a", 35.0, 139.0), place("b", 35.001, 139.0)],
      new Date("2026-06-01T09:00:00+09:00"),
    );
    expect(result.stats.succeeded).toBe(2);
    expect(calls.filter((c) => c === "DRIVING")).toHaveLength(2);
    expect(result.edges.every((e) => e.mode === "car")).toBe(true);
    expect(result.edges.every((e) => e.route_summary === "車")).toBe(true);
  });

  it("距離 > 2km で TRANSIT 失敗 → DRIVING にフォールバック、WALKING 呼ばれない", async () => {
    const calls: string[] = [];
    installMockGoogle(async (req) => {
      const mode = String(req.travelMode);
      calls.push(mode);
      if (mode === "TRANSIT") throw new Error("ZERO_RESULTS");
      return fakeResult({ durationSec: 1800 });
    });
    // ~5km (lat 差 0.045 ≈ 5km)
    const result = await fetchTransitMatrix(
      [place("a", 35.0, 139.0), place("b", 35.045, 139.0)],
      new Date("2026-06-01T09:00:00+09:00"),
    );
    expect(result.stats.succeeded).toBe(2);
    expect(calls.filter((c) => c === "TRANSIT")).toHaveLength(2);
    expect(calls.filter((c) => c === "DRIVING")).toHaveLength(2);
    expect(calls.filter((c) => c === "WALKING")).toHaveLength(0);
    expect(result.edges.every((e) => e.mode === "car")).toBe(true);
  });

  it("3 mode 全部 reject → stats.errors++、edges 空", async () => {
    installMockGoogle(async () => {
      throw new Error("ZERO_RESULTS");
    });
    const result = await fetchTransitMatrix(
      [place("a", 35.0, 139.0), place("b", 35.001, 139.0)],
      new Date("2026-06-01T09:00:00+09:00"),
    );
    expect(result.stats.attempted).toBe(2);
    expect(result.stats.succeeded).toBe(0);
    expect(result.stats.errors).toBe(2);
    expect(result.edges).toEqual([]);
  });

  it("3 mode 全部 timeout → stats.timedOut のみ +2、errors は 0", async () => {
    // 全 mode で永遠に resolve しない → per-mode timeout で打ち切り、
    // callDirectionsWithFallback は最後の result（kind: "timeout"）を返す
    installMockGoogle(
      () =>
        new Promise<google.maps.DirectionsResult>((resolve) => {
          setTimeout(() => resolve(fakeResult({ durationSec: 60 })), 5_000);
        }),
    );
    const result = await fetchTransitMatrix(
      [place("a", 35.0, 139.0), place("b", 35.001, 139.0)],
      new Date("2026-06-01T09:00:00+09:00"),
      { perCallTimeoutMs: 30, globalDeadlineMs: 1_000 },
    );
    expect(result.stats.attempted).toBe(2);
    expect(result.stats.succeeded).toBe(0);
    expect(result.stats.timedOut).toBe(2);
    expect(result.stats.errors).toBe(0);
  });

  it("TRANSIT が timeout の後でも WALKING を試す（per-mode timeout 適用）", async () => {
    const calls: string[] = [];
    installMockGoogle((req) => {
      const mode = String(req.travelMode);
      calls.push(mode);
      if (mode === "TRANSIT") {
        // 永遠に resolve しない（per-mode timeout で打ち切られる想定）
        return new Promise<google.maps.DirectionsResult>((resolve) => {
          setTimeout(() => resolve(fakeResult({ durationSec: 60 })), 5_000);
        });
      }
      return Promise.resolve(fakeResult({ durationSec: 600 }));
    });
    const result = await fetchTransitMatrix(
      [place("a", 35.0, 139.0), place("b", 35.001, 139.0)],
      new Date("2026-06-01T09:00:00+09:00"),
      { perCallTimeoutMs: 50, globalDeadlineMs: 5_000 },
    );
    expect(result.stats.succeeded).toBe(2);
    expect(calls.filter((c) => c === "TRANSIT")).toHaveLength(2);
    expect(calls.filter((c) => c === "WALKING")).toHaveLength(2);
  });

  it("globalDeadline 到達中に fallback 試行を停止する", async () => {
    installMockGoogle(
      () =>
        new Promise<google.maps.DirectionsResult>((resolve) => {
          setTimeout(() => resolve(fakeResult({ durationSec: 60 })), 80);
        }),
    );
    const result = await fetchTransitMatrix(
      [place("a", 35.0, 139.0), place("b", 35.001, 139.0)],
      new Date("2026-06-01T09:00:00+09:00"),
      { perCallTimeoutMs: 200, globalDeadlineMs: 50 },
    );
    expect(result.stats.deadlineReached || result.stats.timedOut > 0).toBe(true);
  });

  it("距離分岐の境界値 (~ 2.0km, ≤) は WALKING を 2 段目に採用", async () => {
    const calls: string[] = [];
    installMockGoogle(async (req) => {
      calls.push(String(req.travelMode));
      if (String(req.travelMode) === "TRANSIT") throw new Error("ZERO_RESULTS");
      return fakeResult({ durationSec: 1500 });
    });
    // lat 差 0.01798 は haversine で約 1.999 km（境界値 2km の直下）
    await fetchTransitMatrix(
      [place("a", 35.0, 139.0), place("b", 35.01798, 139.0)],
      new Date("2026-06-01T09:00:00+09:00"),
    );
    // 境界値 (≤ 2km) → WALKING を採用
    expect(calls.filter((c) => c === "WALKING").length).toBeGreaterThan(0);
  });

  it("WALKING 呼び出し時は transitOptions を渡さない（近距離 ≤ 2km）", async () => {
    const requests: google.maps.DirectionsRequest[] = [];
    installMockGoogle(async (req) => {
      requests.push(req);
      const mode = String(req.travelMode);
      if (mode === "TRANSIT") throw new Error("ZERO_RESULTS");
      return fakeResult({ durationSec: 600 });
    });
    // 近距離 (~0.11km) なので fallback 順序は TRANSIT → WALKING
    await fetchTransitMatrix(
      [place("a", 35.0, 139.0), place("b", 35.001, 139.0)],
      new Date("2026-06-01T09:00:00+09:00"),
    );
    const transitReqs = requests.filter((r) => String(r.travelMode) === "TRANSIT");
    const walkingReqs = requests.filter((r) => String(r.travelMode) === "WALKING");
    expect(transitReqs.length).toBeGreaterThan(0);
    expect(walkingReqs.length).toBeGreaterThan(0);
    expect(transitReqs.every((r) => r.transitOptions !== undefined)).toBe(true);
    expect(walkingReqs.every((r) => r.transitOptions === undefined)).toBe(true);
  });

  it("DRIVING 呼び出し時は transitOptions を渡さない（遠距離 > 2km）", async () => {
    const requests: google.maps.DirectionsRequest[] = [];
    installMockGoogle(async (req) => {
      requests.push(req);
      const mode = String(req.travelMode);
      if (mode === "TRANSIT") throw new Error("ZERO_RESULTS");
      return fakeResult({ durationSec: 1800 });
    });
    // 遠距離 (~5km > 2km) なので fallback 順序は TRANSIT → DRIVING、WALKING は呼ばれない
    await fetchTransitMatrix(
      [place("a", 35.0, 139.0), place("b", 35.045, 139.0)],
      new Date("2026-06-01T09:00:00+09:00"),
    );
    const transitReqs = requests.filter((r) => String(r.travelMode) === "TRANSIT");
    const drivingReqs = requests.filter((r) => String(r.travelMode) === "DRIVING");
    const walkingReqs = requests.filter((r) => String(r.travelMode) === "WALKING");
    expect(transitReqs.length).toBeGreaterThan(0);
    expect(drivingReqs.length).toBeGreaterThan(0);
    expect(walkingReqs).toHaveLength(0); // 遠距離なので WALKING は試さない
    expect(transitReqs.every((r) => r.transitOptions !== undefined)).toBe(true);
    expect(drivingReqs.every((r) => r.transitOptions === undefined)).toBe(true);
  });

  it("距離分岐の上側境界 (~ 2.0015km, > 2km) は DRIVING を 2 段目に採用、WALKING は呼ばれない", async () => {
    // Codex review 2 Minor 1 反映: 閾値が 2 ではなく例えば 3 に変わったら DRIVING ではなく
    // WALKING が呼ばれてこの test が落ちる。「閾値値そのもの」を境界 test pair で固定する。
    const calls: string[] = [];
    installMockGoogle(async (req) => {
      calls.push(String(req.travelMode));
      if (String(req.travelMode) === "TRANSIT") throw new Error("ZERO_RESULTS");
      return fakeResult({ durationSec: 1500 });
    });
    // lat 差 0.018 は haversine で約 2.0015 km（境界値 2km の直上）
    await fetchTransitMatrix(
      [place("a", 35.0, 139.0), place("b", 35.018, 139.0)],
      new Date("2026-06-01T09:00:00+09:00"),
    );
    expect(calls.filter((c) => c === "DRIVING").length).toBeGreaterThan(0);
    expect(calls.filter((c) => c === "WALKING")).toHaveLength(0);
  });

  it("最初から deadline 超過なら service.route を 1 度も呼ばないか最大 1 batch 以内", async () => {
    let callCount = 0;
    // 50ms 遅延の mock。globalDeadlineMs を超える遅延にして fallback chain 内の
    // per-mode timeout で確実に timedOut になることを誘発する。
    installMockGoogle(
      () =>
        new Promise<google.maps.DirectionsResult>((resolve) => {
          callCount++;
          setTimeout(() => resolve(fakeResult({ durationSec: 600 })), 50);
        }),
    );
    const result = await fetchTransitMatrix(
      [place("a", 35.0, 139.0), place("b", 35.001, 139.0)],
      new Date("2026-06-01T09:00:00+09:00"),
      { perCallTimeoutMs: 5, globalDeadlineMs: 5 }, // 即座に deadline 超過
    );
    // 1 batch (2 pair) 以内に収まる
    expect(callCount).toBeLessThanOrEqual(2);
    expect(result.stats.deadlineReached || result.stats.timedOut > 0).toBe(true);
  });
});


// ==============================
// WALKING の長距離上限撤廃（旧 30 分 hard cap を削除済の挙動 documenting）
// ==============================

describe("parseDirectionsResult — WALKING long-walk allowed (30 min cap 撤廃)", () => {
  it("WALKING で duration = 60 分の長距離徒歩でも edge として返る (30 分 hard cap 撤廃の挙動 documenting)", () => {
    // 旧実装は WALKING かつ duration > 30 min → null drop していたが、
    // transport_mode toggle 削除に伴い WALKING 上限を撤廃。fallback chain は
    // 距離分岐で WALKING / DRIVING を選ぶため、長距離徒歩が edge として残っても
    // ペア距離 > 2km では DRIVING が優先されるので副作用は最小。
    const result = {
      routes: [
        {
          legs: [
            // 60 分 = 3600 秒、旧上限 (30 分) を超えても drop されないことを assert
            { duration: { value: 3600, text: "" }, steps: [{ travel_mode: "WALKING" }] },
          ],
        },
      ],
    } as unknown as google.maps.DirectionsResult;
    const edge = parseDirectionsResult(
      result,
      "A",
      "B",
      new Date("2026-06-01T09:00:00+09:00"),
      "WALKING",
    );
    expect(edge).not.toBeNull();
    expect(edge!.duration_min).toBe(60);
    expect(edge!.mode).toBe("walk");
  });
});
