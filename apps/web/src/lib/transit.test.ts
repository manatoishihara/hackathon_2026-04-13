import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  ClientTransitEdge,
  EvidencePlacesPlaceSummary,
} from "shared-types";

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
    );
    expect(edge).not.toBeNull();
    expect(edge!.duration_min).toBe(90);
    expect(edge!.fare_jpy).toBe(2330);
    expect(edge!.mode).toBe("train");
    expect(edge!.route_summary).toBe("小田急線 特急はこね");
    // departure_time を優先使用（09:15）
    expect(edge!.candidate_departures).toEqual(["09:15"]);
  });

  it("transit step が無ければ walk + 徒歩 + requested departure にフォールバック", () => {
    const edge = parseDirectionsResult(
      fakeResult({ durationSec: 600 }),
      "A",
      "B",
      new Date("2026-06-01T08:30:00+09:00"),
    );
    expect(edge).not.toBeNull();
    expect(edge!.mode).toBe("walk");
    expect(edge!.route_summary).toBe("徒歩");
    expect(edge!.candidate_departures).toEqual(["08:30"]);
  });

  it("duration 欠損 / 負数 / 24h 超は null", () => {
    expect(
      parseDirectionsResult(
        { routes: [{ legs: [{ duration: undefined }] }] } as any,
        "A",
        "B",
        new Date(),
      ),
    ).toBeNull();
    expect(
      parseDirectionsResult(
        { routes: [{ legs: [{ duration: { value: -10, text: "" } }] }] } as any,
        "A",
        "B",
        new Date(),
      ),
    ).toBeNull();
    expect(
      parseDirectionsResult(
        { routes: [{ legs: [{ duration: { value: 100_000, text: "" } }] }] } as any,
        "A",
        "B",
        new Date(),
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
    );
    expect(edge!.route_summary.length).toBe(120);
  });
});

// ==============================
// fetchTransitMatrix — 並列 / タイムアウト / 締切 / fail-soft
// ==============================

type RouteFn = (req: google.maps.DirectionsRequest) => Promise<google.maps.DirectionsResult>;

function installMockGoogle(routeFn: RouteFn) {
  (globalThis as unknown as { google: unknown }).google = {
    maps: {
      TravelMode: { TRANSIT: "TRANSIT" },
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

describe("formatHHmm (JST 固定)", () => {
  it("ブラウザ TZ に関係なく JST の HH:mm を返す", async () => {
    // 2026-06-01T00:00:00Z は JST で 09:00
    const utcMidnight = new Date("2026-06-01T00:00:00Z");
    const edge = parseDirectionsResult(
      fakeResult({ durationSec: 600 }),
      "A",
      "B",
      utcMidnight,
    );
    expect(edge!.candidate_departures).toEqual(["09:00"]);
  });

  it("transit step の departure_time を JST でフォーマット", () => {
    // UTC 23:00 は JST 翌日 08:00
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
    );
    expect(edge!.candidate_departures).toEqual(["08:00"]);
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
    const edge = parseDirectionsResult(result, "A", "B", new Date());
    expect(edge!.fare_jpy).toBe(480);
    expect(edge!.mode).toBe("bus");
  });
});
