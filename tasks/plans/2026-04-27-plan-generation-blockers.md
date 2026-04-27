# Plan generation 422 真因 全塞ぎ計画 (Phase 1.10 後段)

**ステータス**: Codex review 2 回目 完了 (review 1: Blocker 2 / Major 4 / Minor 1、review 2 (本計画書 review): Blocker 2 / Major 3 / Minor 1) → 全反映済、実装着手準備完了
**ブランチ**: `fix/plan-generation-blockers`
**スコープ**: 本番 Run 10 で確定した 2 つの真因 + Codex 追加発見の Major を網羅的に塞ぐ
**想定 LOC**: フロント +30 / API +60 / test +120 = 約 +210
**想定時間**: 2〜3 時間
**OpenAI コスト**: 0（unit test のみ）、本番 Run 11 で ~$0.05

## 1. 背景: 本番 Run 10 (2026-04-27 04:54-04:55) で確定した 2 真因

logging.basicConfig(INFO) 反映後の Render Live tail から取得した 4 attempts の breakdown:

| attempt | model | error | 該当 IssueKind |
|---|---|---|---|
| 1 | gpt-4.1 | `unknown_place_id` (day1_lunch、`ChIJJS7EfYgChGWARNW9YGF4jb0I`) | UNKNOWN_PLACE_ID |
| 2 | gpt-4.1 | `unknown_transit_edge` (`candidate_departures=['13:54']` で required `start_hhmm='16:30'` カバー不能) | UNKNOWN_TRANSIT_EDGE |
| 3 | gpt-4.1 | `unknown_place_id` (day1_dinner、attempt 1 と同じ `ChIJJS7EfYgChGWARNW9YGF4jb0I` 再出現) | UNKNOWN_PLACE_ID |
| 4 | gpt-4.1-mini | `unknown_transit_edge` (別 edge、同じく `candidate_departures=['13:54']` で `'16:30'` カバー不能) | UNKNOWN_TRANSIT_EDGE |

詳細は `tasks/lessons.md` 「2026-04-27: 本番 Run 10 で 422 真因判明」エントリ。

## 2. 真因の全体像（Codex review 反映後）

### 真因 A (Blocker, 構造): `candidate_departures` が 1 件しか入らない + Codex 追加発見

`apps/web/src/lib/transit.ts:311-320` の `parseDirectionsResult`:

```typescript
const candidate = formatHHmmJST(departureDate ?? requestedDeparture);
return { ..., candidate_departures: [candidate] };  // 常に 1 件
```

`verify_hallucination_rate.py` では `["09:00","12:00","15:00","18:00","21:00"]` の 5 点で test していたが、本番フロント (Phase 1.3b) は 1 点。**Phase 1.3b ↔ 1.3e の contract drift**。

**Codex 追加発見**: 5 点だけだと **宿→翌朝の遷移 (start_hhmm ≥ 22:00) で再 fail**。具体的には lodging slot が `20:00-22:00` 等で次日 morning slot への transit が `start_hhmm >= '22:00'` を要求すると、`21:00` 候補は不適合 → unknown_transit_edge。**`00:00` / `23:59` が必須**。

### 真因 B (Major, hallucination): gpt-4.1 が unknown place_id を 2 回繰り返し

attempt 1 + 3 で同じ `ChIJJS7EfYgChGWARNW9YGF4jb0I`。Phase 1.3e で 0% 達成済みのはずが本番再発。
- model: gpt-4.1 (Phase 1.3e と同じ)
- prompt v2.0.0 (Phase 1.3e と同じ)
- self-healing: ineligible_place（pack 内、間違った category）には swap、**unknown_place_id (pack 外) には対応なし**

Codex 推奨: `c (A 解消後再測) → b (prompt 強化、retry 時に unknown_id 禁止リスト) → a (deterministic fallback)` の順で対処。本計画では b まで投入する。

### 追加 Major 1 (Codex Major): unknown_place_id の self-healing 不在

`apps/api/src/llm/assembly.py:197-213`:
- `IneligiblePlaceForSlotError` (pack 内、間違った category) → swap で救済される (line 224-251)
- `UnknownPlaceInSlotError` (pack 外、完全に架空) → **救済なし、即 raise → retry**

真因 A 解消で hallucination 確率は下がるが、**真因 B が残る限り 4 attempts 内で再発しうる**。retry での prompt 強化 (b) を必ず追加する。

### 追加 Major 2 (Codex Major): retry の `previous_issues` が文脈弱い

`apps/api/src/llm/generator.py:268`:
```python
previous_issues = issues  # 直前 1 attempt の issue だけが残る
```

attempt 1 で `unknown_place_id 'ChIJJS7E...'` を出した後、attempt 2 では別 issue (unknown_transit_edge) が出ると、その後 attempt 3 で再び `'ChIJJS7E...'` を出してしまう。**「過去全 attempts の禁止 ID 累積」**を retry prompt に渡す必要がある。

### 追加 Major 3 (Codex Major): transit 全滅でもフロントが generate を続行

`apps/web/src/app/plan/[id]/generating/page.tsx:85, 99`:
```typescript
let transitMatrix = [];
try {
  const result = await fetchTransitMatrix(session.places, departureTime);
  transitMatrix = result.edges;
} catch { transitMatrix = []; }
// ↓
await postPlanGenerate({ ..., transit_matrix: transitMatrix });  // 空でも続行
```

**`stats.succeeded === 0` で早期エラー化** すべき。今回 fix のスコープに入れる（30 LOC 程度）。

### 追加 Major 4 (Codex Major): anchor 全不適合の事前 reject なし

`apps/api/src/llm/assembly.py:345`:
- anchor mode で anchor place が全 slot に対し ineligible (営業時間 / category 不適合) → assembler が anchor 不在で `ANCHOR_MISSING` raise → retry → 永遠に再発
- **本セッションでは anchor mode を verify せず、提出後の課題とする**（auto mode で提出する demo シナリオに影響なし）

### Minor (Codex Minor): `verify_hallucination_rate.py` の candidate が本番契約と乖離

5 点 fixed list を使っていたが、本番フロントが 1 点。**真因 A 反映後に同じ 8 点 canonical list に同期**して、test と本番を一致させる。

## 3. 設計

### 3a. 真因 A: フロント `parseDirectionsResult` で canonical 8 点 + observed をマージ

```typescript
// apps/web/src/lib/transit.ts
const CANONICAL_DEPARTURE_TIMES = [
  "00:00", "06:00", "09:00", "12:00", "15:00", "18:00", "21:00", "23:59",
] as const;
// 8 点。Codex 追加発見:
// - "00:00": 翌日 0 時 ~ 朝 (lodging → day_n_morning) の transit start_hhmm カバー
// - "06:00": 早朝 activity slot のカバー
// - "23:59": 夜遅い lodging → 翌朝 transit (start_hhmm >= 22:00) のカバー
// `verify_hallucination_rate.py` も同じ list に同期する。

export function parseDirectionsResult(
  result, fromPlaceId, toPlaceId, requestedDeparture, requestedMode,
): ClientTransitEdge | null {
  // ... duration / fare 抽出は既存のまま ...

  const observed = formatHHmmJST(departureDate ?? requestedDeparture);
  // observed が canonical に含まれない場合のみ merge、Set で重複排除、HH:mm sort
  const merged = Array.from(new Set([...CANONICAL_DEPARTURE_TIMES, observed])).sort();
  // ClientTransitEdge.candidate_departures は max 10 要素。observed が canonical 外なら 9 件。
  
  return {
    ..., candidate_departures: merged,
  };
}
```

**設計のポイント**:
- 8 canonical + observed = 最大 9 件（`max_length=10` の Pydantic 制約内に収まる）
- HH:mm 文字列 sort は辞書順 = 時刻順（"00:00" < "06:00" < ... < "23:59"）で正しい
- observed が canonical と一致する場合は 8 件のまま
- レイテンシ影響ゼロ（fetch 回数変わらず）
- 精度は落ちる（実際の transit 時刻は不確実）が、assembler は「duration_min を信じる」設計なので影響軽微

### 3b. 真因 B: retry prompt 強化（unknown_place_id 禁止リスト、Codex Major 反映で regex 抽出に強化）

`split("'")` は脆弱（メッセージ format 変更で壊れる、validator 由来の別 format 混入）→ **regex で複数 pattern を試行**:

```python
# apps/api/src/llm/prompt.py に追加
import re

# IssueKind.UNKNOWN_PLACE_ID の message format（assembly.py:211 / validator.py:183 由来）を robust に拾う
_UNKNOWN_PLACE_ID_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"unknown place_id ['\"]([^'\"]+)['\"]"),  # assembly UnknownPlaceInSlotError
    re.compile(r"place_id=['\"]([^'\"]+)['\"]"),  # validator 由来
]

def _extract_unknown_place_ids(issues: list[Issue]) -> list[str]:
    extracted: set[str] = set()
    for i in issues:
        if i.kind != IssueKind.UNKNOWN_PLACE_ID:
            continue
        for pattern in _UNKNOWN_PLACE_ID_PATTERNS:
            for m in pattern.finditer(i.message):
                extracted.add(m.group(1))
    return sorted(extracted)


def _build_retry_guidance_md(previous_issues: list[Issue]) -> str:
    """retry 時に「過去 attempts で出した unknown_place_id を再使用するな」を明示。"""
    unknown_ids = _extract_unknown_place_ids(previous_issues)
    if not unknown_ids:
        return ""
    return (
        "# 前回失敗で出した place_id（**絶対に再使用するな**）\n"
        + "\n".join(f"- `{pid}` （pack に存在しない、これを選んだら拒否される）" for pid in unknown_ids)
        + "\n"
    )
```

`apps/api/src/llm/prompts/v2.0.0/user_template.md` に placeholder を追加:

```markdown
# 前回の生成で失敗した検証項目（あれば修正せよ。空配列なら初回試行）
{previous_issues_json}

{retry_guidance_md}

上記情報のみを使って slot 割当 JSON を生成せよ。
```

`build_user_prompt` で `format_kwargs["retry_guidance_md"] = _build_retry_guidance_md(previous_issues)` を追加。

**設計のポイント**:
- 初回 attempt (previous_issues 空) では空文字列 → template 形状変わらず
- attempt 2+ で過去全 attempts の unknown_id を累積（`previous_issues` に過去 issues が含まれる）

### 3c. Major 2: retry の `previous_issues` を累積化（Codex Major 反映で UNKNOWN_PLACE_ID は place_id 単位 dedup）

`apps/api/src/llm/generator.py` の retry loop で `previous_issues` を **過去全 attempts の累積**にする:

```python
# 現状（line 268付近）
previous_issues = issues  # 直前 1 attempt のみ

# 修正後（Codex review 2 反映: UNKNOWN_PLACE_ID は place_id ごとに dedup、それ以外は kind+message）
from .prompt import _extract_unknown_place_ids  # 新設 helper を再利用

def _issue_dedup_key(issue: Issue) -> tuple:
    """dedup key: UNKNOWN_PLACE_ID は place_id 単位、それ以外は kind+message。"""
    if issue.kind == IssueKind.UNKNOWN_PLACE_ID:
        ids = _extract_unknown_place_ids([issue])
        if ids:
            return (issue.kind, ids[0])  # place_id 単位
    return (issue.kind, issue.message)


all_previous_issues: list[Issue] = []
for attempt in range(MAX_ATTEMPTS):
    ...
    if issues:
        all_previous_issues.extend(issues)
        # dedup（dict は最後の write が勝つ → 最新 issue を保持）
        unique = {}
        for i in all_previous_issues:
            unique[_issue_dedup_key(i)] = i
        previous_issues = list(unique.values())[-MAX_RETAIN:]  # 直近 N 件
        ...
```

**設計のポイント**:
- 累積するが、prompt token 肥大化を避けるため `MAX_RETAIN = 10` で cap
- **`UNKNOWN_PLACE_ID` は同じ place_id が複数 slot で出た場合に 1 つに dedup**（Codex Major 反映）
- それ以外の IssueKind は (kind, message) で dedup（同じエラー文を重複させない）
- assembly_error の場合は `previous_issues` に該当 IssueKind の issue を 1 件加える既存設計を踏襲

### 3d. Major 3: transit 全滅時のフロントガード（Codex review 2 で Blocker 化、catch 経路も throw）

**Codex review 2 Blocker 1**: 現状の `try/catch` block は `catch { transitMatrix = []; }` で例外を握りつぶしている。
`fetchTransitMatrix` が SDK ロード失敗 / API 不到達 / 例外 throw した場合、**catch で空配列にして続行 → 422 へ流れる穴**。
両方の経路（成功＋空 / 例外）で early throw する必要がある。

`apps/web/src/app/plan/[id]/generating/page.tsx`:

```typescript
// 修正前
try {
  const result = await fetchTransitMatrix(session.places, departureTime);
  transitMatrix = result.edges;
} catch {
  transitMatrix = [];  // ← 例外を握りつぶして 422 へ流れる穴
}

// 修正後（Codex review 2 Blocker 1 反映）
try {
  const result = await fetchTransitMatrix(session.places, departureTime);
  transitMatrix = result.edges;
  // 成功経路で全 pair 失敗していたら早期エラー
  if (result.stats.attempted > 0 && result.stats.succeeded === 0) {
    throw new Error("経路情報を取得できませんでした。少し時間をおいてお試しください。");
  }
} catch (err) {
  // 例外経路: SDK ロード失敗 / API 不到達 / fetch 中の throw / 上の throw
  // どの場合も 422 へ流さず、外側の try で error 表示に流す
  throw err instanceof Error
    ? err
    : new Error("経路情報の取得中にエラーが発生しました");
}
```

**設計のポイント**:
- 内側 catch は **再 throw する**（握りつぶさない）
- `attempted === 0` (places 1 件以下で transit 不要) は許容（成功経路で transitMatrix=[] のまま続行 = 既存挙動）
- `succeeded === 0` で `attempted > 0` の場合のみ早期 throw → 外側 catch で `setStep("error")` に流れる既存パスに乗る
- SDK ロード失敗・例外も同じ error 経路に集約
- ユーザに 422 ではなく即時の意味のあるエラーが見える

### 3e. verify_hallucination_rate.py の同期 (Codex Minor)

```python
# apps/api/scripts/verify_hallucination_rate.py
candidate_departures=["00:00", "06:00", "09:00", "12:00", "15:00", "18:00", "21:00", "23:59"],
# 本番フロントの canonical 8 点と一致させて contract drift を防ぐ
```

## 4. 変更ファイル一覧

| ファイル | 変更内容 | 行数 |
|---|---|---|
| `apps/web/src/lib/transit.ts` | `parseDirectionsResult` で canonical 8 点 + observed merge | +15 |
| `apps/web/src/lib/transit.test.ts` | `candidate_departures` が 8 件以上、canonical 含む、observed merge の test | +50 |
| `apps/web/src/app/plan/[id]/generating/page.tsx` | transit 全滅時の早期 throw | +5 |
| `apps/api/src/llm/prompt.py` | `_build_retry_guidance_md` 新設 + format_kwargs に追加 | +25 |
| `apps/api/src/llm/prompts/v2.0.0/user_template.md` | `{retry_guidance_md}` placeholder 追加 | +2 |
| `apps/api/src/llm/generator.py` | retry の previous_issues を累積化 + dedup | +15 |
| `apps/api/scripts/verify_hallucination_rate.py` | canonical 8 点に同期 | +1 |
| `apps/api/tests/test_llm_prompt.py` | `_build_retry_guidance_md` の unit test | +35 |
| `apps/api/tests/test_llm_generator.py` | previous_issues 累積の test | +20 |
| `tasks/todo.md` / `tasks/lessons.md` | Run 11 結果の枠を確保（実施後に詳細追記） | +10 |

**型変更なし**、API 契約変更なし、3 点同期不要。

## 5. TDD 手順

### Step 1: フロント canonical 8 点 + observed merge

#### Test 先行（apps/web/src/lib/transit.test.ts）

```typescript
describe("parseDirectionsResult — canonical candidate_departures", () => {
  it("observed 時刻が canonical 外なら 9 件返す（8 canonical + observed）", () => {
    const edge = parseDirectionsResult(
      fakeResult({
        durationSec: 600,
        transitLineName: "テスト線",
        vehicleType: "SUBWAY",
        departureValue: new Date("2026-06-01T13:54:00+09:00"),  // 13:54 = canonical 外
      }),
      "A", "B", new Date(), "TRANSIT",
    );
    expect(edge!.candidate_departures).toEqual([
      "00:00", "06:00", "09:00", "12:00", "13:54", "15:00", "18:00", "21:00", "23:59",
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
      "A", "B", new Date(), "TRANSIT",
    );
    expect(edge!.candidate_departures).toEqual([
      "00:00", "06:00", "09:00", "12:00", "15:00", "18:00", "21:00", "23:59",
    ]);
  });

  it("transit step なし (walk only) の場合 requestedDeparture を observed として扱う", () => {
    const edge = parseDirectionsResult(
      fakeResult({ durationSec: 600 }),  // transit step なし
      "A", "B", new Date("2026-06-01T08:30:00+09:00"), "TRANSIT",
    );
    expect(edge!.candidate_departures).toContain("08:30");
    expect(edge!.candidate_departures).toContain("00:00");
    expect(edge!.candidate_departures).toContain("23:59");
    expect(edge!.candidate_departures.length).toBe(9);
  });

  it("候補配列は HH:mm 順 sort されている", () => {
    const edge = parseDirectionsResult(
      fakeResult({ durationSec: 600 }),
      "A", "B", new Date("2026-06-01T13:54:00+09:00"), "TRANSIT",
    );
    const sorted = [...edge!.candidate_departures].sort();
    expect(edge!.candidate_departures).toEqual(sorted);
  });

  it("max 10 要素以内 (Pydantic 制約)", () => {
    const edge = parseDirectionsResult(
      fakeResult({ durationSec: 600 }),
      "A", "B", new Date("2026-06-01T13:54:00+09:00"), "TRANSIT",
    );
    expect(edge!.candidate_departures.length).toBeLessThanOrEqual(10);
  });
});
```

#### 実装

`apps/web/src/lib/transit.ts` の `parseDirectionsResult` 内で merge ロジック追加。

→ `pnpm --filter web test apps/web/src/lib/transit.test.ts` 全 PASS 確認。

### Step 2: 早期エラー（フロント transit 全滅ガード、Codex review 2 Major 3 反映で test 必須化）

#### Test 先行（apps/web/src/app/plan/[id]/generating/page.test.tsx 新規 / または既存 test に追加）

**Codex review 2 Major**: 例外経路の test なしだと Blocker 1 (catch 経路 throw) を見逃す。

```typescript
import { vi, describe, it, expect } from "vitest";
import { render, waitFor } from "@testing-library/react";
import { MemoryRouter, useRouter } from "next/navigation";
import GeneratingPage from "./page";

vi.mock("@/lib/transit", () => ({
  fetchTransitMatrix: vi.fn(),
}));

describe("/plan/[id]/generating — transit 全滅時の早期エラー", () => {
  it("succeeded === 0 で error 状態に遷移（成功経路で全 pair 失敗）", async () => {
    const { fetchTransitMatrix } = await import("@/lib/transit");
    vi.mocked(fetchTransitMatrix).mockResolvedValueOnce({
      edges: [],
      stats: { attempted: 40, succeeded: 0, errors: 40, timedOut: 0, deadlineReached: false },
    });
    // ... render → waitFor → 「プラン生成に失敗しました」表示を assert
  });

  it("fetchTransitMatrix 例外も error 状態に流れる（catch 経路も throw）", async () => {
    const { fetchTransitMatrix } = await import("@/lib/transit");
    vi.mocked(fetchTransitMatrix).mockRejectedValueOnce(new Error("SDK ロード失敗"));
    // ... render → waitFor → 「経路情報の取得中にエラーが発生しました」or 同等の error 表示を assert
  });

  it("attempted === 0 (places 1 件以下) なら transit 空のまま続行", async () => {
    const { fetchTransitMatrix } = await import("@/lib/transit");
    vi.mocked(fetchTransitMatrix).mockResolvedValueOnce({
      edges: [],
      stats: { attempted: 0, succeeded: 0, errors: 0, timedOut: 0, deadlineReached: false },
    });
    // ... render → エラーにならず「プランを生成中」step まで進む
  });
});
```

**注意**: Next.js App Router の page component test は `next/navigation` mock が必要。既存 test の参考: `apps/web/src/app/plan/new/modeSwitch.test.tsx`。

実装が複雑なら、**`generating/page.tsx` のロジック部分を helper 関数に抽出して unit test** する形でも OK（ガード条件のみ test）:

```typescript
// apps/web/src/app/plan/[id]/generating/transit-guard.ts
export function shouldEarlyThrowOnTransit(stats: FetchTransitStats): boolean {
  return stats.attempted > 0 && stats.succeeded === 0;
}
```

→ こちらの方が test 簡素、推奨。

#### 実装

`generating/page.tsx` の `try` block 内で:
1. `result.stats.attempted > 0 && result.stats.succeeded === 0` チェック → `throw new Error(...)`
2. 内側 `catch` で **再 throw**（握りつぶさない）

→ test 全 PASS 確認。

### Step 3: バック retry guidance + previous_issues 累積

#### Test 先行（apps/api/tests/test_llm_prompt.py）

```python
def test_build_retry_guidance_md_empty():
    """previous_issues が空なら空文字列を返す。"""
    assert _build_retry_guidance_md([]) == ""

def test_build_retry_guidance_md_unknown_place_id():
    """UNKNOWN_PLACE_ID issues から place_id を抽出して禁止リストに。"""
    issues = [
        Issue(kind=IssueKind.UNKNOWN_PLACE_ID, message="LLM assigned unknown place_id 'ChIJ123' to slot 'day1_lunch'"),
        Issue(kind=IssueKind.UNKNOWN_PLACE_ID, message="LLM assigned unknown place_id 'ChIJ456' to slot 'day1_dinner'"),
    ]
    md = _build_retry_guidance_md(issues)
    assert "ChIJ123" in md
    assert "ChIJ456" in md
    assert "絶対に再使用するな" in md

def test_build_retry_guidance_md_dedup():
    """同じ unknown_place_id が複数 issue に含まれていても 1 つに dedup。"""
    issues = [
        Issue(kind=IssueKind.UNKNOWN_PLACE_ID, message="LLM assigned unknown place_id 'ChIJ123' to slot 'day1_lunch'"),
        Issue(kind=IssueKind.UNKNOWN_PLACE_ID, message="LLM assigned unknown place_id 'ChIJ123' to slot 'day1_dinner'"),
    ]
    md = _build_retry_guidance_md(issues)
    assert md.count("ChIJ123") == 1

def test_build_retry_guidance_md_ignores_other_kinds():
    """UNKNOWN_PLACE_ID 以外の IssueKind は無視。"""
    issues = [
        Issue(kind=IssueKind.OUTSIDE_OPENING_HOURS, message="..."),
        Issue(kind=IssueKind.BUDGET_EXCEEDED, message="..."),
    ]
    assert _build_retry_guidance_md(issues) == ""
```

#### 実装

`apps/api/src/llm/prompt.py` に `_build_retry_guidance_md` 追加 + `format_kwargs["retry_guidance_md"]` に注入。

`apps/api/src/llm/prompts/v2.0.0/user_template.md` に placeholder 追加。

→ `pytest tests/test_llm_prompt.py` PASS 確認。

### Step 4: バック retry loop の previous_issues 累積化

#### Test 先行（apps/api/tests/test_llm_generator.py）

```python
def test_previous_issues_accumulated_across_attempts(monkeypatch):
    """retry で previous_issues が累積され、過去 attempts の issue が引き継がれる。"""
    # OpenAI client mock で 3 回連続 issue を返す
    # 最後の attempt の previous_issues に過去 3 attempts 全部の issue が含まれることを assert
    ...
```

#### 実装

`generator.py` の retry loop で `all_previous_issues.extend(issues)` + dedup + cap。

→ `pytest tests/test_llm_generator.py` PASS 確認。

### Step 5: verify_hallucination_rate.py の canonical 同期

`candidate_departures=["00:00","06:00","09:00","12:00","15:00","18:00","21:00","23:59"]` に書き換え。

### Step 6: 全体検証

```bash
# フロント
pnpm --filter web test
pnpm --filter web exec tsc --noEmit
pnpm --filter web build

# バック
cd apps/api && .venv/bin/pytest -m "not integration" -q
```

すべて PASS することを確認。

### Step 7: ローカル + 本番 verify

1. ローカル `pnpm dev` で /plan/new submit → console で stats / candidate_departures が 8 件以上を確認
2. 本番 push → Render auto deploy → **Run 11**:
   - 本番で 422 → 200 に変わるか確認
   - 422 のままなら Render Live tail で attempt 別 issue を確認、次の fix 候補に
3. anchor mode / theme mode は本セッションスコープ外（auto mode で demo 通せれば OK）

## 6. リスク

### Risk: canonical 8 点の精度不足

- 真の transit 時刻は `13:54` のような実 schedule に依存。canonical 8 点は固定 = LLM/assembler は不正確な start_time を信じる
- **影響**: plan の transit item の表示時刻は実際とずれる可能性。ただし duration_min は実 fetch 値、cost / route も実 fetch 値なので**運用上は許容範囲**
- 対処: 提出後に「実 schedule で複数 fetch する option」を実装する将来課題として記録

### Risk: retry guidance の prompt token 増加

- previous_issues 累積で 10 件、各 ~50 tokens = 500 tokens 増 → 12k 警告 threshold 内
- 対処: `MAX_RETAIN = 10` で cap、長文 issue は短縮版を作成

### Risk: 真因 B (hallucination) が retry guidance だけで解消しない

- gpt-4.1 の bias が強く、prompt 強化でも `ChIJJS7E...` を出し続ける可能性
- 対処: Run 11 で再現するか確認 → 必要なら deterministic fallback (Codex 案 a) を Phase 2 で実装

### Risk: 早期エラー throw でユーザに不親切なエラー

- ローカル / 本番で transit 全滅は dev 環境ノイズ起因が多い
- 対処: error message を「経路情報を取得できませんでした。少し時間をおいてお試しください」に統一、retry 導線は既存の「もう一度入力からやり直す」を活用

## 7. Codex review の反映状況

### Codex review 1 (本番 Run 10 ログ + 設計相談)
- ✅ **Blocker 1 (candidate_departures 1 件)**: フロント canonical 8 点 + observed merge で解消 (§3a)
- ✅ **Blocker 2 (5 点だと 22:00+ で再 fail)**: 8 点に `00:00` / `23:59` を含める (§3a)
- ✅ **Major 1 (unknown_place_id self-healing 不在)**: prompt 強化 (b) で対処、deterministic fallback (a) は Phase 2 (§3b)
- ✅ **Major 2 (previous_issues 文脈弱い)**: retry loop で累積化 + dedup (§3c)
- ✅ **Major 3 (transit 全滅時のフロント続行)**: 早期 throw 追加 (§3d)
- 🟡 **Major 4 (anchor 全不適合の事前 reject なし)**: 本セッションスコープ外、提出後課題 (§2 末尾)
- ✅ **Minor (verify_hallucination_rate 乖離)**: canonical 同期 (§3e)

### Codex review 2 (本計画書 review)
- ✅ **Blocker 1 (catch 経路で例外を握りつぶす穴)**: §3d で内側 catch を再 throw 化、外側 catch で error 表示に集約
- ✅ **Blocker 2 (完了条件 200 OR 422 が弱い)**: §9 で「200 必須 + 画面遷移必須」に変更
- ✅ **Major 1 (dedup key (kind, message) だと UNKNOWN_PLACE_ID が複数 slot で残る)**: §3c で UNKNOWN_PLACE_ID は place_id 単位 dedup、それ以外は (kind, message)
- ✅ **Major 2 (split("'") 脆弱)**: §3b で regex 抽出に書き換え (`_UNKNOWN_PLACE_ID_PATTERNS` 2 種)
- ✅ **Major 3 (generating/page.tsx 例外経路 test 未計画)**: §5 Step 2 で test 計画追加（helper 関数抽出 + unit test 推奨）
- ✅ **Minor (lodging 例 21:00-23:00 が実装テンプレ 20:00-22:00 とズレ)**: §2 で修正

## 8. Codex review 2 回目（実装後）に確認してほしいポイント

1. canonical 8 点の境界値処理（`00:00` < `23:59` の sort 順、observed が `00:00` と一致する dedup）
2. `_build_retry_guidance_md` の正規表現抽出が `'XXX'` 形式の他のメッセージで誤動作しないか
3. retry の累積 issue が prompt token 12k threshold を超えないか
4. early throw が auto mode で `attempted === 0` を誤検知しないか
5. 既存 test の regression なし（特に transit.test.ts 145 件）

## 9. 完了基準

- [ ] フロント `parseDirectionsResult` test (~5 件) PASS
- [ ] バック `_build_retry_guidance_md` test (~4 件) PASS
- [ ] バック retry 累積 test (~1 件) PASS
- [ ] 既存 test の regression なし
  - [ ] `pnpm --filter web test` 全 PASS
  - [ ] `pnpm --filter api test -m "not integration"` 全 PASS（既知 env 依存 2 件失敗は本変更無関係）
- [ ] tsc clean / build PASS
- [ ] Codex review 2 回目で blocker 指摘なし
- [ ] commit 提案前に **secret プリフライト 0 hit** 確認
- [ ] commit + push（user 手動）→ Vercel/Render auto deploy → **本番 Run 11** で（Codex review 2 Blocker 2 反映で 200 必須化）:
  - [ ] `transit_matrix.candidate_departures` が 8 件以上含まれる
  - [ ] **`/api/plans/generate` が 200 で返る**（必須、422 は不可）
  - [ ] **`/plan/[id]` のプラン閲覧画面まで遷移する**（必須）
  - [ ] プラン閲覧画面でタイムライン / 予算 / マップが表示される

## 10. 参考

- 元の bug: `tasks/todo.md` の Phase 1.10 本番 Run 9 / Run 10 節
- 真因 A 構造調査: 並列 Explore agent 報告（Phase 1.3b ↔ 1.3e contract drift）
- 真因 B hallucination 調査: 並列 Explore agent 報告（pack 構成 / model bias / prompt 形式の脆弱性）
- Codex review 1 回目: thread `019dcd56-595c-7c82-8882-5d48305a0158`（Blocker 2 / Major 4 / Minor 1）
- 関連実装:
  - フロント: `apps/web/src/lib/transit.ts:243-303` (parseDirectionsResult)
  - フロント: `apps/web/src/app/plan/[id]/generating/page.tsx:83-99` (departureTime 生成 + transit fetch)
  - バック prompt: `apps/api/src/llm/prompt.py:60-130` (build_user_prompt)
  - バック retry: `apps/api/src/llm/generator.py:187-305` (retry loop)
  - バック assembler: `apps/api/src/llm/assembly.py:197-213, 689-709` (UnknownPlaceInSlotError, _pick_departure_time)
  - test fixture: `apps/api/scripts/verify_hallucination_rate.py:147` (5 点 candidate)
- Phase 1.3e の hallucination 0% 実績: `tasks/plans/2026-04-25-structured-plan-assembly.md` 末尾「本セッションの試行錯誤の物語」
