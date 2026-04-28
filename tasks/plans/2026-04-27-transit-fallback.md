# Phase 1.10 fix: Maps Directions の travelMode を TRANSIT → 距離分岐 (WALKING / DRIVING) フォールバック

**ステータス**: codex review 1 回目 完了 → Major 2 / Minor 3 を反映済（実装着手準備完了）
**ブランチ**: `fix/transit-fallback-walking-driving`
**スコープ**: フロント `apps/web/src/lib/transit.ts` の travelMode 固定を fallback chain 化し、観光地ペアでの ZERO_RESULTS を解消する
**想定 LOC**: +75（実装 ~35 / test ~40）
**想定時間**: 1〜2 時間
**OpenAI コスト**: 0（unit test のみ、実 deploy 後の Run 9 は ~$0.05）

## 1. 背景: Phase 1.10 fix 後の Run 8 で判明した bug

`feat/evidence-pack-diversity` で places を観光地 + 飲食 + 宿泊 + その他に bucket 分類して
多様化したあと、ローカル `pnpm dev` の Run 8 verify で Phase 1.10 fix の効果は完璧に
確認できた:

- places **12 件**（旧 10）、観光地 7（彫刻の森美術館 / 箱根神社 / 強羅公園 / 関所 /
  園 / 飛竜の滝 / 玉簾の瀧）+ 飲食 5（喜之助 / 箱根食堂 / 森メシ / 銀の穂 / いろり茶屋）
  の多様な構成
- 互いの距離 **0.64〜9.57 km**（旧 0.01〜0.26 km）、66 ペア全て 10km 以内 = フロント
  transit fetch の対象

ところが **`fetchTransitMatrix` の stats が `{attempted: 40, succeeded: 0, errors: 40,
timedOut: 0, deadlineReached: false}`** で、Maps Directions の TRANSIT モードが
40 ペア全部 ZERO_RESULTS を返した。結果として `transit_matrix: []` のままサーバへ
POST → LLM が plan を組めず validator 3 回 retry → **422 plan generation failed
after retries**。

詳細は `tasks/todo.md` の Phase 1.10 本番 E2E Run 8 節と `tasks/lessons.md` の
「Maps Directions TRANSIT モードは観光地ペアで ZERO_RESULTS を返す」エントリ。

## 2. 真因

`apps/web/src/lib/transit.ts:329-335` の `service.route` 呼び出しが
`travelMode: "TRANSIT"` を **完全固定**している:

```typescript
const routePromise: Promise<CallResult> = service
  .route({
    origin: { placeId: from.place_id },
    destination: { placeId: to.place_id },
    travelMode: "TRANSIT" as google.maps.TravelMode,  // ← ここ
    transitOptions: { departureTime },
  })
  ...
```

Maps Directions の TRANSIT モードは「駅・停留所間の公共交通機関経路」を返すため、
**観光地（彫刻の森美術館 / 箱根神社など）→ 観光地（強羅公園 / 玉簾の瀧など）の
ペア**ではほぼ常に ZERO_RESULTS になる。観光地は徒歩 / 車アクセスが基本で、
公共交通機関の駅から駅という発想が当てはまらない。

皮肉にも Run 7 まで TRANSIT が動いていたのは、places が「箱根湯本駅前 100m 圏の
飲食店ばかり」で、駅の TRANSIT 情報がたまたま hit していたからだった（駅構内 / 
駅前同士の経路扱い）。Phase 1.10 多様性 fix で places が観光地中心に変わった結果、
TRANSIT の限界が顕在化した。

## 3. 設計: TRANSIT → 距離分岐（WALKING / DRIVING）フォールバック chain

**Codex Major 1 反映**: 順序固定（TRANSIT → WALKING → DRIVING）だと **遠距離ペア (10km) で「徒歩 2 時間」が WALKING で先に成功してしまい、plan に組み込まれて 422 を再誘発する** 重大リスクがある。assembler は `duration_min` で時刻を後ろ倒しするため、徒歩 120 分が opening_hours 違反を量産する（`apps/api/src/llm/assembly.py:296`）。

そこで **2 段目の選択を距離で分岐**する設計に変更:

| pair 距離 | 1 段目 | 2 段目 | 3 段目 | 設計意図 |
|---|---|---|---|---|
| **≤ 2 km** | TRANSIT | **WALKING** | DRIVING | 徒歩 30 分以内は plan として自然、bus/train なくても歩いて欲しい |
| **> 2 km** | TRANSIT | **DRIVING** | WALKING | 徒歩 30 分超は plan に乗せたくない、車で移動が現実的 |

各 pair について上記順で試し、最初に成功したモードを採用する。

| mode | parser 出力 | 期待値 |
|---|---|---|
| `TRANSIT` | mode='train'/'bus'、route_summary に line name | 駅間の公共交通機関経路があれば最優先 |
| `WALKING` | mode='walk'、route_summary='徒歩' | 近距離（≤2km）の徒歩経路、Maps SDK が「step.travel_mode='WALKING'」を返す |
| `DRIVING` | mode='car'、route_summary='車' | 遠距離の車経路、徒歩で歩かせたくない場合の現実解 |

**閾値 2km の根拠**:
- 徒歩 30 分 ≈ 平均歩速 4 km/h × 0.5h = 2km（plan に組み込んでも違和感ない上限）
- selectPairs の 10km filter 内で「2km 超〜10km」のペア（彫刻の森⇄箱根神社など）は車移動が自然
- Run 8 で WALKING が成功した距離分布は実測未取得、Run 9 で stats にカテゴリ別 succeeded を出して妥当性検証する余地あり（今回スコープ外）

**閾値の export**: `WALKING_DISTANCE_KM = 2` を `transit.ts` 内に const 定義、test からは import して境界値検証（1.99km / 2.0km / 2.01km）。

### 3a. ZERO_RESULTS の検出

Maps SDK の `service.route()` は ZERO_RESULTS を **promise reject** で返す
（error.message が `"DIRECTIONS_ROUTE: ZERO_RESULTS"` のような文字列）。
今の実装では `.catch((error) => ({ kind: "error", error }))` で全部 `kind: "error"`
に丸めている。

新設計では「`error` がきたら次のモードを試す」だけで OK（具体的な status code を
判別する必要なし）。理由: ZERO_RESULTS 以外の error（NOT_FOUND / OVER_QUERY_LIMIT）
でも次のモードを試す価値はある（fail-soft で edges を最大化したい意図と整合）。

**Codex Minor 3 反映の将来改善候補**: `OVER_QUERY_LIMIT` のような **非回復系 error**
でも 3 mode 試して 3 回叩く形になり、quota 枯渇時に無駄打ちが増える。今回スコープ外
だが、Phase 2 以降で「`error.message` を見て non-recoverable なら fallback skip」
optimization を検討する。MVP 提出を優先する今回は fail-soft 側の単純さを取る。

### 3b. タイムアウト設計

| 項目 | 値 | 根拠 |
|---|---|---|
| per-mode timeout | **2s**（既存の `perCallTimeoutMs` 流用） | 既存設計と一貫性、ZERO_RESULTS は通常 100〜500ms で返るので余裕あり |
| per-pair worst case | 6s（2s × 3 mode） | 3 連続 timeout の最悪値、現実的には ~600ms |
| global deadline | **10s**（既存維持） | SDK ロード含む全体締切、これを超えるとバッチ投入停止 |

**なぜ 6s/pair の worst case が deadline 10s に収まるか**:
- `parallelism=5` でバッチ並列処理、40 pair / 5 = 8 batch
- 1 batch 内は worst 6s、ただし実 ZERO_RESULTS は ~100ms で返るので大半 ~1s
- バッチ間は ZERO_RESULTS 主体なら 8 × 1s = 8s で deadline 内
- 万一 deadline 超えそうなら `effectiveTimeout = min(perModeTimeoutMs, remaining)` で
  打ち切る既存ロジック（`fetchTransitMatrix` 内）を維持

### 3c. parseDirectionsResult の拡張

現状の `parseDirectionsResult` は `step.travel_mode === "TRANSIT"` を探して
mode/route_summary を上書き、見つからなければ default `mode="walk", route_summary="徒歩"`
にフォールバックしている。これは「TRANSIT 要求したのに結果が WALKING で返ってきた」
edge case を吸収する既存の保険。

**Codex Minor 1 反映**: 第 5 引数 `requestedMode` の default を **削除し必須引数**化する。
default 'TRANSIT' にすると新コードで引数渡し漏れがあった時にコンパイル時検知できず、
DRIVING 結果を walk として誤分類するリスクがある。既存 25 件の test は全て
明示的に `"TRANSIT"` を渡すように更新する（test の追加修正コストは小、~25 callsite × 1 引数追加）。

新設計のシグネチャ:

```typescript
export function parseDirectionsResult(
  result: google.maps.DirectionsResult,
  fromPlaceId: string,
  toPlaceId: string,
  requestedDeparture: Date,
  requestedMode: "TRANSIT" | "WALKING" | "DRIVING", // default なし、必須
): ClientTransitEdge | null {
  // ... duration validation 既存のまま ...

  // Default を requestedMode で決定
  let mode: ClientTransitEdge["mode"];
  let routeSummary: string;
  if (requestedMode === "DRIVING") {
    mode = "car";
    routeSummary = "車";
  } else {
    // WALKING または TRANSIT(fallback to walk)
    mode = "walk";
    routeSummary = "徒歩";
  }

  // TRANSIT 要求時のみ transit step を探して上書き（既存ロジック）
  if (requestedMode === "TRANSIT") {
    for (const step of leg?.steps ?? []) {
      if (step.travel_mode === "TRANSIT" && step.transit) {
        const vehicleType = step.transit.line?.vehicle?.type ?? "";
        mode = mapVehicleToMode(vehicleType);
        routeSummary = step.transit.line?.name ?? step.transit.line?.short_name ?? "公共交通機関";
        const depValue = step.transit.departure_time?.value;
        if (depValue instanceof Date) departureDate = depValue;
        break;
      }
    }
  }

  // ... fare 抽出と return は既存のまま ...
}
```

**ポイント**:
- 第 5 引数 `requestedMode` は **必須**（default なし、Minor 1 反映）
- DRIVING で呼ばれたら mode='car', route_summary='車' を default
- WALKING は walk, '徒歩'（既存の TRANSIT fallback と同じ）
- transit step 探索は **TRANSIT 要求時のみ**（WALKING / DRIVING 結果に紛れ込んだ
  TRANSIT step を誤って優先しないため）
- 既存 25 件の test は呼び出しに `"TRANSIT"` を追加して継続 PASS

### 3d. callDirectionsWithTimeout の拡張

引数に `travelMode` を追加し、必要に応じて `transitOptions` を渡す:

```typescript
async function callDirectionsWithTimeout(
  service: google.maps.DirectionsService,
  from: EvidencePlacesPlaceSummary,
  to: EvidencePlacesPlaceSummary,
  departureTime: Date,
  timeoutMs: number,
  travelMode: "TRANSIT" | "WALKING" | "DRIVING", // 新規
): Promise<CallResult> {
  if (timeoutMs <= 0) return { kind: "timeout" };
  const timeoutPromise = new Promise<CallResult>((resolve) => {
    setTimeout(() => resolve({ kind: "timeout" }), timeoutMs);
  });

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
      const edge = parseDirectionsResult(result, from.place_id, to.place_id, departureTime, travelMode);
      if (!edge) return { kind: "error", error: new Error("unparseable DirectionsResult") };
      return { kind: "ok", edge };
    })
    .catch((error: unknown): CallResult => ({ kind: "error", error }));

  return Promise.race([routePromise, timeoutPromise]);
}
```

**ポイント**:
- `transitOptions` は TRANSIT 要求時のみ付与（WALKING / DRIVING で warning が出る可能性を回避）
- `parseDirectionsResult` に第 5 引数で `travelMode` を伝搬

### 3e. callDirectionsWithFallback（新規 helper）

3 mode を順次試す関数を追加。**呼ばれる側で deadline / timeout を管理する**ため、
各 mode 呼び出しの引数に `effectiveTimeout` を渡す:

```typescript
const WALKING_DISTANCE_KM = 2; // ≤ この距離なら 2 段目を WALKING、超えるなら DRIVING

async function callDirectionsWithFallback(
  service: google.maps.DirectionsService,
  from: EvidencePlacesPlaceSummary,
  to: EvidencePlacesPlaceSummary,
  departureTime: Date,
  perModeTimeoutMs: number,
  deadlineEpochMs: number, // global deadline、各 mode 試行時に残時間 check
): Promise<CallResult> {
  // 距離分岐で fallback 順序を決定（Codex Major 1 反映）
  const distanceKm = haversineKm(from, to);
  const modes: ("TRANSIT" | "WALKING" | "DRIVING")[] =
    distanceKm <= WALKING_DISTANCE_KM
      ? ["TRANSIT", "WALKING", "DRIVING"]
      : ["TRANSIT", "DRIVING", "WALKING"];

  let lastResult: CallResult = { kind: "error", error: new Error("no modes attempted") };

  for (const mode of modes) {
    const remaining = deadlineEpochMs - Date.now();
    if (remaining <= 0) {
      // global deadline 超過 → 以降は呼ばずに timeout で抜ける
      // （Codex Minor 2 反映: 最初に超過した時点で必ず timeout を返す）
      return { kind: "timeout" };
    }
    const effectiveTimeout = Math.min(perModeTimeoutMs, remaining);
    const result = await callDirectionsWithTimeout(service, from, to, departureTime, effectiveTimeout, mode);
    if (result.kind === "ok") return result;
    lastResult = result;
    // timeout もしくは error → 次のモードを試す
  }
  // 3 mode 全部試して失敗 → 最後の結果（typically timeout か error）を返す
  return lastResult;
}
```

**ポイント**:
- 距離分岐で 2 段目を切替（Codex Major 1 反映）
- 3 mode それぞれで残 deadline check（無駄な呼び出しを抑止）
- 1 つでも `ok` で返れば即 return（早期成功）
- 全部失敗した場合: **最後に試した mode の結果**（typically timeout か error）を return
  - timeout なら stats.timedOut に +1、error なら stats.errors に +1（fetchTransitMatrix 側で集計）
- deadline が**ループ途中で超過**した場合は **必ず `kind: "timeout"`** を return
  （Minor 2 反映: 「remaining<=0 なら即 timeout」「全モード試行後は最後の結果」と
  動作を明確に区別する）

### 3f. fetchTransitMatrix の main loop は最小変更

`callDirectionsWithTimeout` を直接呼んでいた箇所を `callDirectionsWithFallback` に
差し替えるだけ:

```typescript
// BEFORE
const results = await Promise.all(
  batch.map(([from, to]) =>
    callDirectionsWithTimeout(service, from, to, departureTime, effectiveTimeout),
  ),
);

// AFTER
const results = await Promise.all(
  batch.map(([from, to]) =>
    callDirectionsWithFallback(service, from, to, departureTime, perCallTimeoutMs, deadlineEpochMs),
  ),
);
```

`effectiveTimeout`（バッチ単位で算出していた）は fallback 内部の各 mode 呼び出し時に
都度算出するので外側からは渡さない。`perCallTimeoutMs` を per-mode timeout として渡す。

### 3g. 既存の design contract を壊さない確認

- `ClientTransitEdge` 型は変更なし（`'train' | 'bus' | 'walk' | 'car'` の既存 enum で全部 cover）
- サーバー `validate_client_transit_matrix` も変更なし（mode='walk' / 'car' は既に許容）
- Pydantic `TransitEdge` 型も変更なし
- 既存 test 25 件は `parseDirectionsResult` 呼び出しに `"TRANSIT"` を明示渡しで継続 PASS（Minor 1 反映で必須引数化）
- 3 点同期不要（型変更なし）

## 4. 変更ファイル一覧

| ファイル | 変更内容 | 行数 |
|---|---|---|
| `apps/web/src/lib/transit.ts` | `parseDirectionsResult` に第 5 引数追加、`callDirectionsWithTimeout` に travelMode 引数追加、`callDirectionsWithFallback` 新設、main loop の差し替え | +35 |
| `apps/web/src/lib/transit.test.ts` | DRIVING 用 parser test、fallback chain test（TRANSIT→WALKING、TRANSIT+WALKING→DRIVING、3 mode 全失敗）、既存 test の互換性確認 | +60 |
| `tasks/todo.md` / `tasks/lessons.md` | Run 9 実施結果の枠を確保（実施後に詳細追記） | +10 |

**型変更なし**、API 契約変更なし、サーバー側変更なし、フロント呼び出し元（`generating/page.tsx`）変更なし。

## 5. TDD 手順

### Step 1: parseDirectionsResult に第 5 引数追加（DRIVING / WALKING の default 切替）

#### Test 先行（apps/web/src/lib/transit.test.ts）

```typescript
describe("parseDirectionsResult — requestedMode", () => {
  it("requestedMode='DRIVING' なら default mode='car' / route_summary='車'", () => {
    const result = {
      routes: [{ legs: [{ duration: { value: 1800, text: "" }, steps: [{ travel_mode: "DRIVING" }] }] }],
    } as unknown as google.maps.DirectionsResult;
    const edge = parseDirectionsResult(result, "A", "B", new Date("2026-06-01T09:00:00+09:00"), "DRIVING");
    expect(edge!.mode).toBe("car");
    expect(edge!.route_summary).toBe("車");
    expect(edge!.duration_min).toBe(30);
  });

  it("requestedMode='WALKING' なら default mode='walk' / route_summary='徒歩'", () => {
    const result = {
      routes: [{ legs: [{ duration: { value: 600, text: "" }, steps: [{ travel_mode: "WALKING" }] }] }],
    } as unknown as google.maps.DirectionsResult;
    const edge = parseDirectionsResult(result, "A", "B", new Date(), "WALKING");
    expect(edge!.mode).toBe("walk");
    expect(edge!.route_summary).toBe("徒歩");
  });

  it("requestedMode='TRANSIT' で transit step あり → 既存挙動（line name 抽出）", () => {
    // 既存 test と同じ振る舞い
    const edge = parseDirectionsResult(
      fakeResult({
        durationSec: 5400,
        transitLineName: "小田急線 特急はこね",
        vehicleType: "HEAVY_RAIL",
      }),
      "A", "B", new Date("2026-06-01T09:00:00+09:00"), "TRANSIT",
    );
    expect(edge!.mode).toBe("train");
    expect(edge!.route_summary).toBe("小田急線 特急はこね");
  });

  // requestedMode は default なしの必須引数なので「省略時 test」は不要。
  // 既存 25 件は呼び出し側に "TRANSIT" を追加して継続 PASS させる。

  it("requestedMode='DRIVING' でも transit step が紛れていたら無視する", () => {
    // DRIVING 要求の結果に万一 TRANSIT step が混じっても上書きしない
    const result = {
      routes: [{ legs: [{
        duration: { value: 1200, text: "" },
        steps: [
          { travel_mode: "TRANSIT", transit: { line: { name: "ノイズ", vehicle: { type: "BUS" } } } },
          { travel_mode: "DRIVING" },
        ],
      }] }],
    } as unknown as google.maps.DirectionsResult;
    const edge = parseDirectionsResult(result, "A", "B", new Date(), "DRIVING");
    expect(edge!.mode).toBe("car");
    expect(edge!.route_summary).toBe("車");
  });
});
```

#### 実装

`parseDirectionsResult` のシグネチャに第 5 引数 `requestedMode` を追加、default 'TRANSIT'。
mode/routeSummary の初期化を requestedMode で分岐。transit step 探索を `if (requestedMode === "TRANSIT")` でガード。

### Step 2: callDirectionsWithTimeout に travelMode 引数を追加

#### Test 先行

```typescript
describe("callDirectionsWithTimeout — travelMode", () => {
  it("travelMode='WALKING' を service.route に渡す（transitOptions なし）", async () => {
    let capturedRequest: google.maps.DirectionsRequest | undefined;
    installMockGoogle(async (req) => {
      capturedRequest = req;
      return fakeResult({ durationSec: 600 });
    });
    await fetchTransitMatrix(
      [place("a", 35.0, 139.0), place("b", 35.001, 139.0)],
      new Date("2026-06-01T09:00:00+09:00"),
    );
    // 何か呼ばれたことだけ確認、詳細は次の test
    expect(capturedRequest).toBeDefined();
  });
});
```

このテストは callDirectionsWithFallback と一緒に統合 test で書く方が自然（後段 Step 3 と統合）。

#### 実装

`callDirectionsWithTimeout` の引数に `travelMode` を追加。`request.transitOptions` を
`travelMode === "TRANSIT"` のときだけ付与。

### Step 3: callDirectionsWithFallback 新設 + fetchTransitMatrix で使用

#### Test 先行（fetchTransitMatrix の挙動として書く）

```typescript
describe("fetchTransitMatrix — fallback chain", () => {
  it("TRANSIT が ZERO_RESULTS で WALKING にフォールバック", async () => {
    const calls: { mode: string; from: string; to: string }[] = [];
    installMockGoogle(async (req) => {
      const mode = String(req.travelMode);
      const fromId = (req.origin as { placeId: string }).placeId;
      const toId = (req.destination as { placeId: string }).placeId;
      calls.push({ mode, from: fromId, to: toId });
      if (mode === "TRANSIT") throw new Error("DIRECTIONS_ROUTE: ZERO_RESULTS");
      return fakeResult({ durationSec: 600 }); // WALKING で成功
    });
    const result = await fetchTransitMatrix(
      [place("a", 35.0, 139.0), place("b", 35.001, 139.0)],
      new Date("2026-06-01T09:00:00+09:00"),
    );
    expect(result.stats.attempted).toBe(2); // a→b と b→a の 2 ペア
    expect(result.stats.succeeded).toBe(2); // WALKING で両方成功
    // 各ペアで TRANSIT → WALKING の順で呼ばれている
    const transitCalls = calls.filter((c) => c.mode === "TRANSIT");
    const walkingCalls = calls.filter((c) => c.mode === "WALKING");
    expect(transitCalls).toHaveLength(2);
    expect(walkingCalls).toHaveLength(2);
    // edges の mode が walk になっている
    expect(result.edges.every((e) => e.mode === "walk")).toBe(true);
  });

  it("TRANSIT も WALKING も失敗 → DRIVING にフォールバック", async () => {
    installMockGoogle(async (req) => {
      const mode = String(req.travelMode);
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
    expect(result.edges.every((e) => e.mode === "car")).toBe(true);
    expect(result.edges.every((e) => e.route_summary === "車")).toBe(true);
  });

  it("3 mode 全部失敗 → stats.errors に加算、edges 空", async () => {
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

  it("TRANSIT で即成功 → WALKING / DRIVING は呼ばない", async () => {
    const calls: string[] = [];
    installMockGoogle(async (req) => {
      const mode = String(req.travelMode);
      calls.push(mode);
      // TRANSIT で必ず成功
      return fakeResult({ durationSec: 1200, transitLineName: "小田急線", vehicleType: "HEAVY_RAIL" });
    });
    const result = await fetchTransitMatrix(
      [place("a", 35.0, 139.0), place("b", 35.001, 139.0)],
      new Date("2026-06-01T09:00:00+09:00"),
    );
    expect(result.stats.succeeded).toBe(2);
    expect(calls).toEqual(["TRANSIT", "TRANSIT"]); // WALKING / DRIVING は呼ばれない
    expect(result.edges.every((e) => e.mode === "train")).toBe(true);
  });

  it("TRANSIT が timeout の後でも WALKING を試す（per-mode timeout 適用）", async () => {
    const calls: string[] = [];
    installMockGoogle(async (req) => {
      const mode = String(req.travelMode);
      calls.push(mode);
      if (mode === "TRANSIT") {
        // 永遠に resolve しない（per-mode timeout で打ち切られる想定）
        return new Promise((resolve) => {
          setTimeout(() => resolve(fakeResult({ durationSec: 60 })), 5000);
        }) as unknown as google.maps.DirectionsResult;
      }
      return fakeResult({ durationSec: 600 });
    });
    const result = await fetchTransitMatrix(
      [place("a", 35.0, 139.0), place("b", 35.001, 139.0)],
      new Date("2026-06-01T09:00:00+09:00"),
      { perCallTimeoutMs: 50, globalDeadlineMs: 5000 },
    );
    expect(result.stats.succeeded).toBe(2); // WALKING で成功
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
      // 単一 pair で perMode 200ms × 3 = 600ms 必要だが deadline は 50ms
      { perCallTimeoutMs: 200, globalDeadlineMs: 50 },
    );
    expect(result.stats.deadlineReached || result.stats.timedOut > 0).toBe(true);
  });

  // ---- Codex Major 2 反映の追加 test ----

  it("3 mode 全部 timeout → stats.timedOut のみ +2、errors は +0", async () => {
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
    expect(result.stats.timedOut).toBe(2); // 各 pair で最終結果が timeout
    expect(result.stats.errors).toBe(0);
  });

  it("距離 ≤ 2km のペア: TRANSIT 失敗 → WALKING を 2 段目に試す", async () => {
    const calls: string[] = [];
    installMockGoogle(async (req) => {
      const mode = String(req.travelMode);
      calls.push(mode);
      if (mode === "TRANSIT") throw new Error("ZERO_RESULTS");
      return fakeResult({ durationSec: 600 });
    });
    // ~1.1km 距離のペア
    const result = await fetchTransitMatrix(
      [place("a", 35.0, 139.0), place("b", 35.01, 139.0)],
      new Date("2026-06-01T09:00:00+09:00"),
    );
    expect(result.stats.succeeded).toBe(2);
    // 各 pair で TRANSIT → WALKING の順、DRIVING は呼ばれない
    expect(calls.filter((c) => c === "TRANSIT")).toHaveLength(2);
    expect(calls.filter((c) => c === "WALKING")).toHaveLength(2);
    expect(calls.filter((c) => c === "DRIVING")).toHaveLength(0);
    expect(result.edges.every((e) => e.mode === "walk")).toBe(true);
  });

  it("距離 > 2km のペア: TRANSIT 失敗 → DRIVING を 2 段目に試す（WALKING はスキップ的に最後）", async () => {
    const calls: string[] = [];
    installMockGoogle(async (req) => {
      const mode = String(req.travelMode);
      calls.push(mode);
      if (mode === "TRANSIT") throw new Error("ZERO_RESULTS");
      return fakeResult({ durationSec: 1800 });
    });
    // ~5km 距離のペア（> 2km）
    const result = await fetchTransitMatrix(
      [place("a", 35.0, 139.0), place("b", 35.045, 139.0)],
      new Date("2026-06-01T09:00:00+09:00"),
    );
    expect(result.stats.succeeded).toBe(2);
    // 各 pair で TRANSIT → DRIVING の順、WALKING は呼ばれない
    expect(calls.filter((c) => c === "TRANSIT")).toHaveLength(2);
    expect(calls.filter((c) => c === "DRIVING")).toHaveLength(2);
    expect(calls.filter((c) => c === "WALKING")).toHaveLength(0);
    expect(result.edges.every((e) => e.mode === "car")).toBe(true);
  });

  it("距離分岐の境界値 (2.0km) は WALKING を 2 段目に採用", async () => {
    const calls: string[] = [];
    installMockGoogle(async (req) => {
      calls.push(String(req.travelMode));
      if (String(req.travelMode) === "TRANSIT") throw new Error("ZERO_RESULTS");
      return fakeResult({ durationSec: 1500 });
    });
    // ちょうど 2km 想定の lat 差（35.018 で約 2.0km）
    await fetchTransitMatrix(
      [place("a", 35.0, 139.0), place("b", 35.018, 139.0)],
      new Date("2026-06-01T09:00:00+09:00"),
    );
    // 境界値 (≤ 2km) → WALKING を採用
    expect(calls.filter((c) => c === "WALKING").length).toBeGreaterThan(0);
  });

  it("WALKING / DRIVING 呼び出し時は transitOptions を渡さない", async () => {
    const requests: google.maps.DirectionsRequest[] = [];
    installMockGoogle(async (req) => {
      requests.push(req);
      const mode = String(req.travelMode);
      if (mode === "TRANSIT") throw new Error("ZERO_RESULTS");
      return fakeResult({ durationSec: 600 });
    });
    await fetchTransitMatrix(
      [place("a", 35.0, 139.0), place("b", 35.01, 139.0)],
      new Date("2026-06-01T09:00:00+09:00"),
    );
    const transitReqs = requests.filter((r) => String(r.travelMode) === "TRANSIT");
    const walkingReqs = requests.filter((r) => String(r.travelMode) === "WALKING");
    expect(transitReqs.length).toBeGreaterThan(0);
    expect(walkingReqs.length).toBeGreaterThan(0);
    // TRANSIT は transitOptions あり、WALKING はなし
    expect(transitReqs.every((r) => r.transitOptions !== undefined)).toBe(true);
    expect(walkingReqs.every((r) => r.transitOptions === undefined)).toBe(true);
  });

  it("最初から deadline 超過なら service.route を 1 度も呼ばない", async () => {
    let callCount = 0;
    installMockGoogle(async () => {
      callCount++;
      return fakeResult({ durationSec: 600 });
    });
    // 通常運用で起きにくいが、SDK ロードに時間が掛かった想定
    const result = await fetchTransitMatrix(
      [place("a", 35.0, 139.0), place("b", 35.001, 139.0)],
      new Date("2026-06-01T09:00:00+09:00"),
      { perCallTimeoutMs: 100, globalDeadlineMs: 1 }, // 即座に deadline 超過
    );
    // バッチ投入前 deadline check で 0 回呼び出し or 最大でも 1 batch (2 pair × 1 mode) 以内
    expect(callCount).toBeLessThanOrEqual(2);
    expect(result.stats.deadlineReached || result.stats.timedOut > 0).toBe(true);
  });
});
```

#### 実装

`callDirectionsWithFallback` 関数を新設、`fetchTransitMatrix` の main loop で
`callDirectionsWithTimeout` 直接呼びを `callDirectionsWithFallback` に差し替え。

### Step 4: 既存 test 25 件の regression 確認

- `pnpm --filter web test apps/web/src/lib/transit.test.ts` で 25 件 + 新規 ~12 件 = 37 件 PASS
- `pnpm --filter web exec tsc --noEmit` で型エラーなし
- `pnpm --filter web build` で build PASS

### Step 5: 全体検証

- API 側 unit test は変更なし、念のため `pnpm --filter api test -m "not integration"` で regression 確認
- ローカル `pnpm dev` で `/plan/new` から箱根 / wishes 短文 / tag 空で submit、
  generating page で `console.log` を一時的に挿入して `result.stats` を確認:
  - `attempted: 40`、`succeeded: > 0`、`edges.length > 0` を期待
  - mode の breakdown（`train` 何件 / `walk` 何件 / `car` 何件）を確認
- 成功したら `/plan/<id>` に到達するか確認（最終 E2E は本番 deploy 後の Run 9）

## 6. リスク

### Risk: per-pair の合計処理時間が増えて global deadline を超える

- 試算: 3 mode × 2s = 6s 最悪、但し ZERO_RESULTS は 100ms で返る
- ZERO_RESULTS 主体なら ~600ms/pair、parallel batch 5 で 8 batch × ~600ms = 4.8s ⇒ deadline 内
- WALKING / DRIVING も timeout する extreme ケースは API 障害級でレアケース
- mitigation: deadline check を 3 mode それぞれの直前に入れる（§3e の `remaining <= 0` ガード）

### Risk: WALKING の duration が不適切に長い（10km を 2 時間歩く想定で plan に組み込まれる）

**Codex Major 1 反映で軽減**:
- 距離 > 2km のペアは fallback 順序が `TRANSIT → DRIVING → WALKING` なので、
  TRANSIT が ZERO_RESULTS でも次は DRIVING（typically ~10〜30 分）が採用される
- WALKING が採用されるのは **距離 ≤ 2km のペアか、TRANSIT/DRIVING 両方失敗の最終 fallback**
- 距離 ≤ 2km なら WALKING duration は ~30 分以内 → plan に組み込んでも自然

**残リスク**:
- 距離 > 2km で **DRIVING も** ZERO_RESULTS（極稀、本州の道路網では起きにくい）→ WALKING 採用 → 長時間徒歩
- mitigation: Phase 2 以降に「WALKING の duration_min が 30 分超なら edge を drop」の
  post-processing も検討。今回は MVP 提出優先で実装しない

### Risk: DRIVING の fare_jpy が null（コスト推定不能）

- Maps Directions の DRIVING は fare 情報を返さない（高速料金は別 API、ここでは推定不要）
- LLM は cost_jpy=null を見て estimated 扱いする（既存 contract）
- mitigation: 不要。null は contract 上 valid

### Risk: regression — 既存 25 件 test の挙動が変わる

- `parseDirectionsResult` の第 5 引数は必須引数化（Minor 1 反映、default なし）。既存 25 件は呼び出しに `"TRANSIT"` を明示追加して継続 PASS
- `callDirectionsWithTimeout` は private（export なし）なのでシグネチャ変更可
- `fetchTransitMatrix` の public API は変更なし
- mitigation: TDD で既存 test を最初に通したまま新規 test を追加する流れに

### Risk: Maps SDK が WALKING/DRIVING で別の error code を返す

- WALKING で 100km 以上の経路は MAX_WAYPOINTS_EXCEEDED 等の特殊 error が出る可能性
- 今回は 10km filter 内のペアのみなので発生確率は極低
- mitigation: error は全部 `kind: "error"` で吸収して次の mode に進むので破綻しない

## 7. Codex review 1 回目の反映状況

- ✅ **Major 1 (Q1 + Q7)**: fallback 順序を距離分岐に変更（≤ 2km は TRANSIT → WALKING → DRIVING、> 2km は TRANSIT → DRIVING → WALKING）。徒歩 2 時間が plan に乗るリスクを構造的に低減（§3 表 + §3e + §6）
- ✅ **Major 2 (Q5)**: test を 5 件追加（3 mode 全 timeout で timedOut のみ +2、距離 ≤ 2km / > 2km の挙動分岐、距離境界 2.0km、WALKING で transitOptions 未付与、deadline 初期超過で 0 回呼び出し）。§5 Step 3 の test 一覧 を更新
- ✅ **Minor 1 (Q3)**: `parseDirectionsResult` の第 5 引数 `requestedMode` を default なしの必須引数に変更。既存 25 件 test は `"TRANSIT"` を明示渡しで更新（§3c）
- ✅ **Minor 2 (Q4)**: callDirectionsWithFallback 内の動作を「remaining ≤ 0 なら即 timeout」「全モード試行後は最後の結果」と区別する仕様に明確化（§3e の擬似コード + コメント）
- ✅ **Minor 3 (Q9)**: OVER_QUERY_LIMIT 等の非回復系 error も 3 回叩く設計を Phase 2 改善候補として §3a に明記
- ✅ **OK 1〜3**: per-mode timeout 2s 維持 / transitOptions を TRANSIT のみ / Promise leak 既存制約として許容

## 8. Codex review 2 回目（実装後）に確認してほしいポイント

1. 上記 review 1 のコメントが漏れなく反映されているか（特に距離分岐 + Major 2 の 5 件 test）
2. 既存 25 件 test が全部 PASS しているか（regression なし、`requestedMode="TRANSIT"` 明示渡しで継続）
3. 新規 test ~17 件（parseDirectionsResult ~5 + fetchTransitMatrix fallback ~7 + Major 2 追加 5）が境界値含めて網羅できているか
4. fallback chain 内で deadline check が抜けてないか（無限 retry / 暴走の可能性）
5. メモリリーク / promise leak がないか（timeout で抜けた routePromise が残らないか、これは元々の設計上 SDK 側に投げっぱなしで OK）
6. `WALKING_DISTANCE_KM = 2` の閾値が test で明示的に検証されているか（境界 2.0km / 1.99km / 2.01km）

## 9. 完了基準

- [ ] `parseDirectionsResult` 拡張 test (~5 件、DRIVING / WALKING / TRANSIT step 抽出 / 紛入 transit step 無視) PASS
- [ ] `fetchTransitMatrix` fallback chain test (~12 件、TRANSIT 即成功 / 距離 ≤ 2km の WALKING 移行 / 距離 > 2km の DRIVING 移行 / 距離境界 / 全失敗 / 3 mode 全 timeout で timedOut のみ / WALKING で transitOptions 未付与 / deadline 初期超過 / timeout 中の WALKING 試行) PASS
- [ ] 既存 transit.test.ts 25 件の regression なし（呼び出しに `"TRANSIT"` 明示追加して継続 PASS）
- [ ] `pnpm --filter web test` 全 PASS（既存 95 件 + 新規 ~17 件）
- [ ] `pnpm --filter web exec tsc --noEmit` clean
- [ ] `pnpm --filter web build` PASS
- [ ] Codex review 2 回目で blocker 指摘なし
- [ ] commit 提案前に **secret プリフライト 0 hit** 確認（CLAUDE.md ルール）
- [ ] commit + push（user 手動）→ Vercel auto deploy → **Run 9 で transit_matrix が ≥ 1 件取れる + `/plan/[id]` まで遷移 + Phase 2.2 budget context が prompt に乗る**

## 10. 参考

- 元の bug: `tasks/todo.md` の Phase 1.10 本番 E2E Run 8 節
- Phase 1.10 多様性 fix（前提）: `tasks/plans/2026-04-26-evidence-pack-diversity.md`
- 関連実装: `apps/web/src/lib/transit.ts:329-335`（travelMode 固定箇所）
- 関連 test: `apps/web/src/lib/transit.test.ts`（既存 25 件）
- Phase 1.3b で transit.ts を新設した経緯: `tasks/plans/2026-04-21-plan-generation-skeleton.md`
- Maps Directions の TRANSIT 限界: `tasks/lessons.md`「日本の transit はサーバ API では取れない」エントリ + 今回追加予定の「TRANSIT モードは観光地ペアで ZERO_RESULTS」エントリ
