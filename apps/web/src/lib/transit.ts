/**
 * Maps JavaScript API `DirectionsService` ラッパー（ブラウザ側実行前提）。
 *
 * 役割:
 * - フロントで `EvidencePlacesPlaceSummary[]` を受け取り、近接ペアに対して transit 経路を取得
 * - 結果を `ClientTransitEdge[]` に整形して `/api/plans/generate`（Phase 1.3c）に渡す
 *
 * 前提:
 * - 日本の transit は Google サーバー API (Routes/Directions) から取れないため
 *   フロント Maps JS SDK で取得する（tasks/lessons.md）
 * - `NEXT_PUBLIC_GOOGLE_MAPS_BROWSER_KEY` が HTTP referrer 制限付きで発行されている
 *   （サーバーキーとは別、`.env.example` 参照）
 *
 * 設計上の制約:
 * - DirectionsService の実リクエストは中断できない（`Promise.race` のタイムアウトは
 *   失敗判定のためだけに使う）。よってグローバル締切とバッチ単位の投入停止で
 *   暴走を抑える
 * - 失敗は fail-soft で個別エッジを欠損扱い、呼び出し側は `stats.succeeded === 0`
 *   等で全滅を検知してエラー表示する
 * - 有向エッジ: 選ばれた無向ペア (A, B) に対し A→B と B→A を両方取得
 * - ペア選定は「各 place が最低 1 接続」を保証してから距離順で上限まで埋める
 */

import { importLibrary, setOptions } from "@googlemaps/js-api-loader";
import type {
  ClientTransitEdge,
  EvidencePlacesPlaceSummary,
} from "shared-types";

// ==============================
// Defaults（options で上書き可）
// ==============================

const DEFAULT_MAX_PAIRS = 20; // undirected ペアの最大数（directed は ×2）
const DEFAULT_PARALLELISM = 5;
const DEFAULT_PER_CALL_TIMEOUT_MS = 2_000;
const DEFAULT_GLOBAL_DEADLINE_MS = 10_000;
const DEFAULT_DISTANCE_KM = 10;
const MAX_ROUTE_SUMMARY_CHARS = 120; // Pydantic 側の Field(max_length=120) と揃える

// この距離以下なら fallback の 2 段目を WALKING に、超えるなら DRIVING にする。
// 2km は徒歩 ~30 分相当で plan に組み込んでも違和感ない上限。
const WALKING_DISTANCE_KM = 2;

/**
 * candidate_departures の canonical 8 点（HH:mm 固定）。
 *
 * Phase 1.10 後段の本番 Run 10 で「1 件しか入らないため
 * assembler の `_pick_departure_time` がカバー不能 → unknown_transit_edge」が
 * 多発した（Phase 1.3b ↔ 1.3e contract drift）。
 *
 * 8 点の意義:
 * - "00:00" / "23:59": 翌朝への transit (lodging slot 後 / 22:00+ start_hhmm) をカバー
 * - "06:00": 早朝 activity slot
 * - "09:00" / "12:00" / "15:00" / "18:00" / "21:00": 主要時間帯
 *
 * **drift 注意**: `apps/api/scripts/verify_hallucination_rate.py:147` 周辺にも
 * 同じ 8 点を Python list で hardcode している（言語境界で共有 module 不可なため）。
 * **本 list を変更する時は必ず Python 側も更新する**。Python script 側のコメントにも
 * 双方向の drift 警告を残してある。
 */
export const CANONICAL_DEPARTURE_TIMES = [
  "00:00",
  "06:00",
  "09:00",
  "12:00",
  "15:00",
  "18:00",
  "21:00",
  "23:59",
] as const;

// ==============================
// Types
// ==============================

export type FetchTransitOptions = {
  maxPairs?: number;
  parallelism?: number;
  perCallTimeoutMs?: number;
  globalDeadlineMs?: number;
  distanceKm?: number;
};

export type FetchTransitStats = {
  attempted: number;
  succeeded: number;
  timedOut: number;
  errors: number;
  deadlineReached: boolean;
};

export type FetchTransitMatrixResult = {
  edges: ClientTransitEdge[];
  stats: FetchTransitStats;
};

export class TransitConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "TransitConfigError";
  }
}

// ==============================
// SDK loader（singleton + test hook）
// ==============================

let routesLibraryPromise: Promise<google.maps.RoutesLibrary> | null = null;

async function loadRoutesLibrary(): Promise<google.maps.RoutesLibrary> {
  if (typeof window === "undefined") {
    throw new TransitConfigError(
      "fetchTransitMatrix must run in the browser (typeof window === 'undefined')",
    );
  }
  if (routesLibraryPromise) return routesLibraryPromise;

  const apiKey = process.env.NEXT_PUBLIC_GOOGLE_MAPS_BROWSER_KEY;
  if (!apiKey) {
    throw new TransitConfigError(
      "NEXT_PUBLIC_GOOGLE_MAPS_BROWSER_KEY is not set. Configure it in .env.local and reload.",
    );
  }

  setOptions({ key: apiKey, v: "weekly" });
  const attempt = importLibrary("routes");
  routesLibraryPromise = attempt;
  // 失敗した promise が singleton に残ると再試行不能になるため、reject を検知して
  // nullify する。成功した場合は cached されたまま reuse される。
  attempt.catch(() => {
    if (routesLibraryPromise === attempt) {
      routesLibraryPromise = null;
    }
  });
  return attempt;
}

/** テスト専用: singleton を破棄する。production では呼ばない。 */
export function _resetLoaderForTests(): void {
  routesLibraryPromise = null;
}

// ==============================
// Pure helpers (export してテスト可能にする)
// ==============================

type LatLng = { lat: number; lng: number };

export function haversineKm(a: LatLng, b: LatLng): number {
  const R = 6371;
  const toRad = (deg: number) => (deg * Math.PI) / 180;
  const dLat = toRad(b.lat - a.lat);
  const dLng = toRad(b.lng - a.lng);
  const lat1 = toRad(a.lat);
  const lat2 = toRad(b.lat);
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

const pairKey = (
  a: EvidencePlacesPlaceSummary,
  b: EvidencePlacesPlaceSummary,
): string => [a.place_id, b.place_id].sort().join("|");

/**
 * 近接ペアを選定する。
 *
 * ステップ 1: 各 place の「最近接の close neighbor」を 1 本ずつ確保
 *             （grid 被覆性、孤立 place を作らない）
 * ステップ 2: 残り枠を距離順で埋める
 *
 * - maxKm を超える距離のペアは無視
 * - 返値は無向エッジの配列（directed 化は呼び出し側でやる）
 */
export function selectPairs(
  places: EvidencePlacesPlaceSummary[],
  maxKm: number,
  maxPairs: number,
): [EvidencePlacesPlaceSummary, EvidencePlacesPlaceSummary][] {
  if (places.length < 2 || maxPairs <= 0) return [];

  const chosen = new Set<string>();
  const result: [EvidencePlacesPlaceSummary, EvidencePlacesPlaceSummary][] = [];

  for (const p of places) {
    if (result.length >= maxPairs) break;
    const nearest = places
      .filter((q) => q.place_id !== p.place_id)
      .map((q) => ({ place: q, dist: haversineKm(p, q) }))
      .filter((x) => x.dist <= maxKm)
      .sort((a, b) => a.dist - b.dist)[0];
    if (!nearest) continue;
    const key = pairKey(p, nearest.place);
    if (!chosen.has(key)) {
      chosen.add(key);
      result.push([p, nearest.place]);
    }
  }

  const allCloseSorted: {
    a: EvidencePlacesPlaceSummary;
    b: EvidencePlacesPlaceSummary;
    dist: number;
  }[] = [];
  for (let i = 0; i < places.length; i++) {
    for (let j = i + 1; j < places.length; j++) {
      const dist = haversineKm(places[i], places[j]);
      if (dist <= maxKm) {
        allCloseSorted.push({ a: places[i], b: places[j], dist });
      }
    }
  }
  allCloseSorted.sort((x, y) => x.dist - y.dist);

  for (const { a, b } of allCloseSorted) {
    if (result.length >= maxPairs) break;
    const key = pairKey(a, b);
    if (!chosen.has(key)) {
      chosen.add(key);
      result.push([a, b]);
    }
  }

  return result;
}

// ==============================
// Response parsing
// ==============================

/**
 * HH:mm 形式を **JST 固定**で返す。
 * ブラウザのローカルタイムゾーンに依存しない（例: ハワイで開いても日本の時刻）。
 * Phase 3+ で他地域対応する場合は `query_context.region` から IANA タイムゾーンを引く。
 */
function formatHHmmJST(d: Date): string {
  return new Intl.DateTimeFormat("ja-JP", {
    timeZone: "Asia/Tokyo",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(d);
}

const RAIL_VEHICLE_TYPES = new Set([
  "HEAVY_RAIL",
  "COMMUTER_TRAIN",
  "HIGH_SPEED_TRAIN",
  "LONG_DISTANCE_TRAIN",
  "METRO_RAIL",
  "MONORAIL",
  "RAIL",
  "SUBWAY",
  "TRAM",
]);

function mapVehicleToMode(vehicle: string): ClientTransitEdge["mode"] {
  if (vehicle === "BUS" || vehicle === "TROLLEYBUS" || vehicle === "INTERCITY_BUS") {
    return "bus";
  }
  if (RAIL_VEHICLE_TYPES.has(vehicle)) {
    return "train";
  }
  // 未知の乗り物は安全側で train 扱い（サーバー検証で弾かれない範囲）
  return "train";
}

/**
 * DirectionsResult を ClientTransitEdge に整形する。
 * 壊れたレスポンス（duration 欠損・24h 超過）は null を返す。
 *
 * candidate_departures は最初の transit step の departure_time を優先抽出し、
 * 取れないとき（walking-only 経路など）だけ requestedDeparture を fallback に使う。
 */
export function parseDirectionsResult(
  result: google.maps.DirectionsResult,
  fromPlaceId: string,
  toPlaceId: string,
  requestedDeparture: Date,
  requestedMode: "TRANSIT" | "WALKING" | "DRIVING",
): ClientTransitEdge | null {
  const route = result.routes?.[0];
  const leg = route?.legs?.[0];
  const durationValue = leg?.duration?.value;
  if (typeof durationValue !== "number" || durationValue < 0) {
    return null;
  }

  const durationMin = Math.round(durationValue / 60);
  if (durationMin > 1440) {
    return null;
  }

  let fareJpy: number | null = null;
  // @types/google.maps は DirectionsLeg に fare を持たないが、ランタイムでは
  // 存在する場合がある（transit 区間のみの運賃）。route.fare を優先、無ければ leg.fare にフォールバック。
  const fare =
    route?.fare ??
    (leg as unknown as { fare?: google.maps.TransitFare })?.fare;
  if (fare && fare.currency === "JPY" && typeof fare.value === "number" && fare.value >= 0) {
    fareJpy = Math.min(500_000, Math.round(fare.value));
  }

  // requestedMode で default の mode / route_summary を決める。
  // DRIVING は車、WALKING / TRANSIT は徒歩を default に。
  // TRANSIT 要求時のみ leg.steps を走査して transit step の line 名等で上書きする。
  let mode: ClientTransitEdge["mode"];
  let routeSummary: string;
  if (requestedMode === "DRIVING") {
    mode = "car";
    routeSummary = "車";
  } else {
    mode = "walk";
    routeSummary = "徒歩";
  }
  let departureDate: Date | null = null;

  if (requestedMode === "TRANSIT") {
    for (const step of leg?.steps ?? []) {
      if (step.travel_mode === "TRANSIT" && step.transit) {
        const vehicleType = step.transit.line?.vehicle?.type ?? "";
        mode = mapVehicleToMode(vehicleType);
        routeSummary =
          step.transit.line?.name ??
          step.transit.line?.short_name ??
          "公共交通機関";
        const depValue = step.transit.departure_time?.value;
        if (depValue instanceof Date) {
          departureDate = depValue;
        }
        break;
      }
    }
  }

  // routeSummary が空文字に落ちるのは TRANSIT で line.name が空文字の特殊ケースのみ。
  // (DRIVING='車' / WALKING='徒歩' / TRANSIT(transit step なし)='徒歩' は構造的に空にならない)
  const summary = routeSummary.slice(0, MAX_ROUTE_SUMMARY_CHARS) || "公共交通機関";
  const observed = formatHHmmJST(departureDate ?? requestedDeparture);

  // canonical 8 点 + observed を Set で dedup → HH:mm 文字列 sort（辞書順 = 時刻順）。
  // observed が canonical に含まれれば 8 件、外なら 9 件。
  // Pydantic ClientTransitEdge.candidate_departures は max_length=10 なので必ず収まる。
  const candidates = Array.from(
    new Set<string>([...CANONICAL_DEPARTURE_TIMES, observed]),
  ).sort();

  return {
    from_place_id: fromPlaceId,
    to_place_id: toPlaceId,
    mode,
    route_summary: summary,
    duration_min: Math.max(0, durationMin),
    fare_jpy: fareJpy,
    candidate_departures: candidates,
  };
}

// ==============================
// Directions 呼び出し + タイムアウト
// ==============================

type CallResult =
  | { kind: "ok"; edge: ClientTransitEdge }
  | { kind: "timeout" }
  | { kind: "error"; error: unknown };

async function callDirectionsWithTimeout(
  service: google.maps.DirectionsService,
  from: EvidencePlacesPlaceSummary,
  to: EvidencePlacesPlaceSummary,
  departureTime: Date,
  timeoutMs: number,
  travelMode: "TRANSIT" | "WALKING" | "DRIVING",
): Promise<CallResult> {
  // timeoutMs <= 0 は即時タイムアウト扱い（deadline を過ぎたバッチ内の残り呼び出しに使う）
  if (timeoutMs <= 0) {
    return { kind: "timeout" };
  }
  const timeoutPromise = new Promise<CallResult>((resolve) => {
    setTimeout(() => resolve({ kind: "timeout" }), timeoutMs);
  });

  // transitOptions は TRANSIT 要求時のみ付ける。WALKING / DRIVING に付けると
  // 一部 SDK バージョンで warning が出るのと、不要パラメータは送らないのが原則。
  const request: google.maps.DirectionsRequest = {
    origin: { placeId: from.place_id },
    destination: { placeId: to.place_id },
    travelMode: travelMode as google.maps.TravelMode,
  };
  if (travelMode === "TRANSIT") {
    request.transitOptions = { departureTime };
  }

  const routePromise: Promise<CallResult> = service
    .route(request)
    .then((result): CallResult => {
      const edge = parseDirectionsResult(
        result,
        from.place_id,
        to.place_id,
        departureTime,
        travelMode,
      );
      if (!edge) {
        return { kind: "error", error: new Error("unparseable DirectionsResult") };
      }
      return { kind: "ok", edge };
    })
    .catch((error: unknown): CallResult => ({ kind: "error", error }));

  return Promise.race([routePromise, timeoutPromise]);
}

/**
 * TRANSIT → 距離分岐 (WALKING / DRIVING) → 残りモード の順で fallback chain を試す。
 *
 * 距離 ≤ WALKING_DISTANCE_KM のペア: TRANSIT → WALKING → DRIVING
 *   (近距離は徒歩で plan として自然)
 * 距離 > WALKING_DISTANCE_KM のペア: TRANSIT → DRIVING → WALKING
 *   (遠距離は車を優先、最後の保険として徒歩)
 *
 * 各モード呼び出し前に global deadline を確認し、超過していれば即 timeout で抜ける。
 * 1 つでも `ok` で返れば即 return。全モード失敗なら最後に試した結果を return。
 */
async function callDirectionsWithFallback(
  service: google.maps.DirectionsService,
  from: EvidencePlacesPlaceSummary,
  to: EvidencePlacesPlaceSummary,
  departureTime: Date,
  perModeTimeoutMs: number,
  deadlineEpochMs: number,
): Promise<CallResult> {
  const distanceKm = haversineKm(from, to);
  const modes: ("TRANSIT" | "WALKING" | "DRIVING")[] =
    distanceKm <= WALKING_DISTANCE_KM
      ? ["TRANSIT", "WALKING", "DRIVING"]
      : ["TRANSIT", "DRIVING", "WALKING"];

  let lastResult: CallResult = {
    kind: "error",
    error: new Error("no modes attempted"),
  };

  for (const mode of modes) {
    const remaining = deadlineEpochMs - Date.now();
    if (remaining <= 0) {
      // global deadline 超過 → 以降は呼ばずに timeout で抜ける
      return { kind: "timeout" };
    }
    const effectiveTimeout = Math.min(perModeTimeoutMs, remaining);
    const result = await callDirectionsWithTimeout(
      service,
      from,
      to,
      departureTime,
      effectiveTimeout,
      mode,
    );
    if (result.kind === "ok") return result;
    lastResult = result;
    // timeout もしくは error → 次のモードを試す
  }
  // 3 mode 全部試して失敗 → 最後の結果（typically timeout か error）を返す
  return lastResult;
}

// ==============================
// Main API
// ==============================

export async function fetchTransitMatrix(
  places: EvidencePlacesPlaceSummary[],
  departureTime: Date,
  options: FetchTransitOptions = {},
): Promise<FetchTransitMatrixResult> {
  // 入力は防御的に補正（負数 / 0 / undefined）
  const maxPairs = Math.max(0, options.maxPairs ?? DEFAULT_MAX_PAIRS);
  const parallelism = Math.max(1, options.parallelism ?? DEFAULT_PARALLELISM);
  const perCallTimeoutMs = Math.max(1, options.perCallTimeoutMs ?? DEFAULT_PER_CALL_TIMEOUT_MS);
  const globalDeadlineMs = Math.max(1, options.globalDeadlineMs ?? DEFAULT_GLOBAL_DEADLINE_MS);
  const distanceKm = Math.max(0, options.distanceKm ?? DEFAULT_DISTANCE_KM);

  // 締切は SDK ロードも含めて「関数呼び出し開始から」10 秒で管理する。
  // バッチ投入時と per-call timeout の両方でこの deadline を参照する。
  const deadlineEpochMs = Date.now() + globalDeadlineMs;

  const undirected = selectPairs(places, distanceKm, maxPairs);
  const directed: [EvidencePlacesPlaceSummary, EvidencePlacesPlaceSummary][] = [];
  for (const [a, b] of undirected) {
    directed.push([a, b]);
    directed.push([b, a]);
  }

  const stats: FetchTransitStats = {
    attempted: 0,
    succeeded: 0,
    timedOut: 0,
    errors: 0,
    deadlineReached: false,
  };
  const edges: ClientTransitEdge[] = [];

  if (directed.length === 0) {
    return { edges, stats };
  }

  const routesLib = await loadRoutesLibrary();
  const service = new routesLib.DirectionsService();

  for (let i = 0; i < directed.length; i += parallelism) {
    const remaining = deadlineEpochMs - Date.now();
    if (remaining <= 0) {
      stats.deadlineReached = true;
      break;
    }

    const batch = directed.slice(i, i + parallelism);
    stats.attempted += batch.length;

    // 各 mode 呼び出しの effectiveTimeout は callDirectionsWithFallback 内で
    // 「per-mode timeout」と「残り deadline」の小さい方を都度算出する。
    // ここでは pair ごとに fallback chain（TRANSIT → 距離分岐 (WALKING / DRIVING)）を投入する。
    const results = await Promise.all(
      batch.map(([from, to]) =>
        callDirectionsWithFallback(
          service,
          from,
          to,
          departureTime,
          perCallTimeoutMs,
          deadlineEpochMs,
        ),
      ),
    );

    for (const r of results) {
      if (r.kind === "ok") {
        edges.push(r.edge);
        stats.succeeded++;
      } else if (r.kind === "timeout") {
        stats.timedOut++;
      } else {
        stats.errors++;
      }
    }
  }

  return { edges, stats };
}
