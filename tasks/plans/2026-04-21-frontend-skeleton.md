# Frontend Skeleton Implementation Plan — Phase 1.4〜1.9 骨組み

> **Revision history:**
> - 2026-04-21 v1: 初版
> - 2026-04-21 v2: Codex レビュー反映（生成フロー契約確定 / モック戦略厳格化 / ブランチ 4 分割 / 依存漏れ修正 / Zustand 責務明確化 / handoff 資料の状態表示修正 / 共有 API の認可方針確定）
> - 2026-04-21 v3: Codex v2 re-review 反映（`PlanGenerationPayload.plan_id` 追加で 1.3c に小修正 + 3 点同期 / Task 2 の Zustand 責務修正 / Task 6 の不一致ルール整理 / Task 7 の initialData 撤廃 / ブランチを 6 分割（Branch 0〜5）に / handoff-db の説明文整合化 / plans.status カラム追加）

**Goal:** メンバー C（デザイン担当）にデザイン作業だけに集中してもらうため、API 接続・状態管理・ルーティング・コンポーネント Props 定義など **配線まわりを全て先行実装** する。デザイナーは `className` / レイアウト / アニメーションを触るだけでよい状態にする。

**Architecture:** Next.js 15 App Router + Tailwind v4（Design Tokens は `@theme` 済）+ shadcn/ui（公式 Tailwind v4 対応 CLI を使う）+ TanStack Query + Zustand + react-hook-form + zod。Mapbox / react-qr-code / framer-motion は該当ページでのみ使用。

**Tech Stack:** Next.js 15 / React 19 / TypeScript / Tailwind v4 / shadcn/ui / @tanstack/react-query + @tanstack/react-query-devtools / zustand / react-hook-form / zod / @phosphor-icons/react / mapbox-gl / react-map-gl / react-qr-code / framer-motion / vitest + happy-dom + @testing-library/react

**Branches（v3 で 6 段階に分割、Branch 0〜5。Codex v2 re-review 指摘に対応）:**
0. `feat/plan-generation-plan-id` — **Task 0**: `PlanGenerationPayload` に `plan_id` フィールドを追加し 3 点同期。1.3c 実装に小修正を入れる（Critical）
1. `feat/frontend-foundation` — Task 1〜3（依存導入・基盤・共通コンポーネント）
2. `feat/frontend-core-flow` — Task 4〜6（1.4 / 1.5 / 1.6）
3. `feat/frontend-plan-view` — Task 7（1.7 プラン閲覧、分離することでレビュー可読性を上げる）
4. `feat/frontend-extra-pages` — Task 8〜9（1.8 / 1.9）**Branch 2-3 依存**（Task 8 は 1.7 に差し込むため）
5. `feat/frontend-handoff` — Task 10（handoff 資料 + todo.md + architecture.md 最終化）

前提:
- Branch 0 は 1.3c の `develop` マージ後に着手（既存コード修正のため）
- Branch 1 は依存ゼロなので Branch 0 を待たず先行可
- Branch 2 以降は Branch 0 + Branch 1 マージ後に着手

---

## 方針 / 判断確定（v2 改訂）

### 生成フロー契約 — **v2 の最重要確定事項**

Codex re-review Must-fix #1: plan_id の発行タイミング / places の受け渡しが未定義だったため、明文化する。

**フロー（1.5 → 1.6 → 1.7）**:
1. **1.5 希望入力画面 submit 時**:
   1. `crypto.randomUUID()` で **フロント側が plan_id を発行**
   2. Supabase に `plans` レコード（session_id, title, region, 予算, start_mode, ...）を **plan_id を明示指定して INSERT**
   3. `participants` を INSERT（plan_id 紐付け）
   4. `postEvidencePlaces(form)` で evidence_pack_id + places を取得
   5. Zustand の `generationSessionStore` に `{ plan_id, evidence_pack_id, places }` を stash
   6. `router.push("/plan/<plan_id>/generating")` へ遷移
2. **1.6 プラン生成中画面 mount 時**:
   1. Zustand から `{ plan_id, evidence_pack_id, places }` を取り出す（無ければ 1.5 へリダイレクト）
   2. `fetchTransitMatrix(places, depTime)` で transit_matrix 取得
   3. `postPlanGenerate({ plan_id, evidence_pack_id, transit_matrix })` を kick（**plan_id はフロントで発行した UUID、Task 0 で payload に追加済み**）
   4. 完了したら `router.push("/plan/<plan_id>")`（plan_id は既に Zustand にある同じ UUID）
3. **1.3d で `/api/plans/generate` の挙動**: `payload.plan_id` を **そのまま使って** Supabase の該当 Plan を特定 → owner 検証（`plans.session_id = g.owner_session_id` 確認）→ plan_items を INSERT → 最終レスポンス `{ plan_id: <payload と同じ UUID> }`。session の最新 plan を推測するロジックは**持たない**（競合回避、Codex Critical 対応済）
4. **1.3c 時点（LLM 未接続）**: `/api/plans/generate` は payload.plan_id を受け取るだけで `{ plan_id: null }` を返す。フロントは:
  - `NEXT_PUBLIC_USE_MOCKS=1` の場合は Zustand の plan_id で `/plan/<plan_id>` へ遷移（デザイン確認用）
  - それ以外は `plan_id: null` を「LLM 未接続」として表示し、1.3d 完成まで遷移しない
5. **ゴミデータ対策（Codex v3 Medium 指摘）**: `plans` テーブルに `status TEXT CHECK (status IN ('draft', 'generating', 'succeeded', 'failed'))` を追加（**Task 0 と同じコミットで DDL 変更**）。

**status の状態遷移（フロント + サーバー）**:
| きっかけ | 更新後の status | 更新タイミング | 更新主体 |
|---|---|---|---|
| `plans` INSERT（1.5 submit 直後） | `draft` | INSERT と同時 | フロント（1.5） |
| `/api/evidence/places` 成功 | `generating` | Zustand stash の前 | フロント（1.5） |
| `/api/evidence/places` 失敗 | `failed` | エラーハンドラ | フロント（1.5） |
| `/api/plans/generate` 失敗 | `failed` | エラーハンドラ | フロント（1.6） |
| 1.6 中断（ユーザがタブを閉じた等） | `generating` のまま | — | なし → DB-3 で清掃 |
| 1.3d の LLM 生成成功 + plan_items INSERT | `succeeded` | Flask 側 | サーバー（1.3d） |
| 1.3d の LLM 生成失敗 | `failed` | Flask 側 | サーバー（1.3d） |

**清掃対象（DB-3 に反映）**:
- `status = 'draft' AND created_at < now() - INTERVAL '24 hours'` — submit したが evidence/places が呼ばれる前に離脱
- `status = 'failed' AND created_at < now() - INTERVAL '24 hours'` — 明示的失敗
- `status = 'generating' AND updated_at < now() - INTERVAL '1 hour'` — 生成中に中断され放置（LLM は 60 秒以内に完了する前提なので 1 時間は十分長いマージン）
- `succeeded` は削除しない（ユーザの成果物なので保全）

**理由**:
- フロントが plan_id を先に発行する: Architecture ドキュメントの「`/plan/[id]` に遷移、Supabase から plan_items を直接読み取り描画」と整合
- 1.3c が `plan_id: null` 返してもフロントは遷移可能（自分が持ってる）
- 1.3d 改修時は「既存 plan_id を使う」ロジックを Flask 側に追加するだけで済む（エンドポイント契約は不変）

**副産物**: `docs/architecture.md` に「5. [API] LLM Plan Generator」周辺を **plan_id は Web 側で発行、API は plan_items のみ INSERT** として追記する必要あり。Task 10 でフォロー。

### スコープ
- 1.4 / 1.5 / 1.6 / 1.7 / 1.8 / 1.9 の **6 画面分** の骨組み
- 骨組みの定義 = 「型付き props / API 接続 / 状態管理 / ルーティング / 最小 JSX（機能が動く最低限の描画）」が揃っている
- デザイナー担当 = 「className、レイアウト、Motion、スクショからの再現、グローバル Design Tokens 微調整」

### テスト方針
- **Vitest smoke test**: 各ページが crash せず描画されること（1 件/画面、最低保証）
- **ロジック持ちコンポーネント**: `EvidenceBadge`（バッジ判定）/ `PlanTimeline`（日付グルーピング）/ `BudgetSummary`（数値整形）/ `BudgetBreakdownSlider`（合計 100% 保持）に unit テスト
- **API クライアント**: `lib/api.ts` の `fetch` モックでリクエスト形状を検証（1 件/エンドポイント）
- **E2E (Playwright)**: スコープ外（Phase 1.10 の時に 1 シナリオだけ追加）
- **視覚回帰**: スコープ外（frontend-design.md 記載通り）

### モックデータ戦略（v2 厳格化: Codex Must-fix #2）

- `NEXT_PUBLIC_USE_MOCKS=1` の場合、**`queryFn` 自体を差し替える**（`initialData` + 裏 fetch の混在を避ける）
- 実装パターン（`lib/api.ts` 側で分岐）:

```typescript
const USE_MOCKS = process.env.NEXT_PUBLIC_USE_MOCKS === "1";

export async function getPlan(planId: string): Promise<Plan> {
  if (USE_MOCKS) return mockPlan;
  const { data, error } = await supabase.from("plans")...;
  // ...
}
```

- 1.5 の `postEvidencePlaces` もモック時は `mockEvidencePlacesResponse` を直接返す（Flask API に到達しない）
- 1.6 の `postPlanGenerate` もモック時は `{ plan_id: <Zustand の plan_id> }` を即 resolve（transit は `fetchTransitMatrix` が SDK 未ロードで空配列を返すのでそのまま）
- 1.7 の `getPlan` / `getPlanItems` / `getParticipants` もモック時は fixture を返す
- 本番移行: `NEXT_PUBLIC_USE_MOCKS=0`（または unset）で全箇所が実 API に切り替わる

### shadcn/ui 運用
- CLI (`pnpm dlx shadcn@latest init`) で Tailwind v4 対応のセットアップ
- 初期コピー対象: `button` / `card` / `input` / `label` / `slider` / `select` / `dialog` / `badge` / `separator` / `progress` / `tabs`
- `components/ui/*.tsx` は frontend-design.md の Design Tokens を使う形にその場で書き換える（デフォルトテーマ禁止ルール準拠）
- 新コンポーネント追加はデザイナー判断で OK、Design Tokens だけは守る

### API クライアント設計
- `lib/api.ts` に以下を export:
  - `postEvidencePlaces(req: GeneratePlanRequest): Promise<EvidencePlacesResponse>`
  - `postPlanGenerate(req: PlanGenerationPayload): Promise<{ plan_id: string | null }>` ※1.3d 完成後は UUID が入る
  - `getPlan(planId: string): Promise<Plan>` ※ Supabase クライアント経由（直接 DB 読み、RLS でガード）
  - `getPlanItems(planId: string): Promise<PlanItem[]>` ※ 同上
  - `getParticipants(planId: string): Promise<Participant[]>` ※ 同上
- JWT は `lib/supabase.ts` の `getSession()` 相当から取得し、`Authorization: Bearer ...` を自動付与
- Flask API のベース URL は `NEXT_PUBLIC_API_URL` 環境変数

### Zustand ストア設計（v2 責務明確化: Codex Must-fix #5）

**責務境界**:
- **react-hook-form**: 1.5 のフォーム state（入力中の値、バリデーションエラー、touched）を **一手に管理**。Zustand には入れない
- **Zustand `generationSessionStore`**: 1.5 submit 後 → 1.6 → 1.7 の **ルート跨ぎ一時 state** のみ
  - `{ plan_id: string, evidence_pack_id: string, places: EvidencePlacesPlaceSummary[], createdAt: number } | null`
  - `setSession(session)` / `clearSession()` の 2 メソッドのみ
  - `createdAt` で 15 分以上古いセッションは無効化（evidence_pack_sessions の TTL と揃える）
- **TanStack Query**: サーバー状態（plan / plan_items / participants）。Zustand には入れない

**これで Zustand と RHF の重複、Query と Zustand の重複を回避**。

ルーティング遷移で state を保持するための最小限。localStorage 永続化は不要（1 端末/同一セッション前提、ブラウザリロードでは Zustand も消えてフォーム戻りは発生するが許容）。

### react-hook-form + zod
- `lib/schemas/planForm.ts` に `GeneratePlanRequest` を zod 化（`budget_breakdown` 合計 100% 検証、participants 2〜5 人検証）
- 1.5 ページで `useForm<GeneratePlanRequestForm>({ resolver: zodResolver(...) })`
- エラー表示は shadcn/ui の `FormMessage` 相当で

### 3 状態（ローディング / エラー / 成功）の統一
- 全 useQuery 利用箇所で `<LoadingState />` / `<ErrorState />` / 成功時の JSX を明示的に分岐
- `components/ui/states/` に共通コンポーネントを置く

---

## ファイル構造（完成形）

```
apps/web/src/
├── app/
│   ├── layout.tsx                  # 既存 + Providers 追加
│   ├── providers.tsx               # 新: QueryClient + SupabaseProvider
│   ├── page.tsx                    # 1.4 ランディング
│   ├── plan/
│   │   ├── new/page.tsx            # 1.5 希望入力
│   │   └── [id]/
│   │       ├── page.tsx            # 1.7 プラン閲覧
│   │       ├── generating/page.tsx # 1.6 プラン生成中
│   │       └── share/page.tsx      # 1.9 プラン共有
│   └── globals.css                 # 既存
├── components/
│   ├── ui/                         # shadcn/ui コピー（Design Tokens 済）
│   │   ├── button.tsx / card.tsx / input.tsx / label.tsx / slider.tsx
│   │   ├── select.tsx / dialog.tsx / badge.tsx / separator.tsx
│   │   ├── progress.tsx / tabs.tsx
│   │   └── states/
│   │       ├── LoadingState.tsx
│   │       ├── ErrorState.tsx
│   │       └── EmptyState.tsx
│   ├── EvidenceBadge.tsx           # shared-types の getEvidenceBadgeInfo を参照
│   ├── PlanTimeline.tsx            # PlanItem[] → 日付グルーピング
│   ├── PlanItem.tsx
│   ├── BudgetSummary.tsx
│   ├── BudgetBreakdownSlider.tsx   # 合計 100% を保つ 4 連スライダー
│   ├── ParticipantTabs.tsx
│   ├── ParticipantForm.tsx         # 単一参加者の入力
│   ├── MapView.tsx                 # 1.8 Mapbox 初期化
│   └── ShareQRCode.tsx             # 1.9 QR
├── lib/
│   ├── api.ts                      # 新: Flask API client
│   ├── supabase.ts                 # 既存
│   ├── transit.ts                  # 既存
│   ├── format.ts                   # 新: Intl.NumberFormat ラッパー、日時整形
│   ├── schemas/
│   │   └── planForm.ts             # zod + 型
│   └── mocks/
│       ├── plan.ts                 # Plan fixture
│       ├── planItems.ts            # PlanItem[] fixture
│       ├── participants.ts
│       └── evidencePlaces.ts
├── stores/
│   └── generationSessionStore.ts   # Zustand（ルート跨ぎ一時 state のみ、v3）
└── __tests__/                      # ページ smoke テストはここに集約
    ├── pages.smoke.test.tsx
    ├── EvidenceBadge.test.tsx      # コンポーネントと同階層でも可
    └── api.test.ts
```

---

## Task 0: `PlanGenerationPayload.plan_id` を追加 + `plans.status` カラム追加（1.3c 実装の小幅拡張、3 点同期 + DDL）

**Why（Codex v3 Critical + Medium 指摘）**:
1. フロントが plan_id を発行する設計にするなら、`/api/plans/generate` の payload に `plan_id` を含める必要がある。さもないと 1.3d 実装時に「session_id 単位で最新の未完了 plan を推測」するハメになり、同一セッションで複数生成が走った時に plan_items 誤挿入リスクがある。payload に plan_id を入れれば曖昧さなし。
2. ゴミデータ対策として `plans.status` カラム（`draft | generating | succeeded | failed`）を追加し、1.5 submit / 1.3d 完了 / 失敗で状態遷移させる。定期クリーンアップは DB 整理タスクで実装する。

**Files:**
- Modify: `docs/data-model.md` — (a) `PlanGenerationPayload` 型に `plan_id: string` 追加、(b) `plans` テーブル DDL に `status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'generating', 'succeeded', 'failed'))` を追加、(c) `Plan` 型に `status` フィールド追加
- Modify: `packages/shared-types/src/index.ts` — `Plan.status` 追加、`PlanStatus` enum 追加、`PlanGenerationPayload.plan_id` 追加
- Modify: `apps/api/src/schemas/__init__.py` — `Plan.status`、`PlanStatus` literal、`PlanGenerationPayload.plan_id: UUID` を追加
- Modify: `apps/api/tests/test_schema_parity.py` — `EXPECTED_FIELDS["Plan"]` に `"status"`、`EXPECTED_FIELDS["PlanGenerationPayload"]` に `"plan_id"`
- Modify: `apps/api/src/routes/plan_routes.py` — payload から plan_id を受け取れるようになる。1.3c 時点では validate するだけ、将来 1.3d で使う TODO コメント
- Modify: `apps/api/tests/test_routes_plans.py` — 正常系テストで `plan_id` を含めるように修正、`invalid_uuid` テストは `plan_id` も UUID 違反ケースを追加

**DDL（ユーザが Supabase SQL Editor で手動適用）:**
```sql
ALTER TABLE plans
  ADD COLUMN status TEXT NOT NULL DEFAULT 'draft'
  CHECK (status IN ('draft', 'generating', 'succeeded', 'failed'));
CREATE INDEX idx_plans_status ON plans(status);
```

- [ ] **Step 1: docs/data-model.md の `PlanGenerationPayload` を更新**

```typescript
export type PlanGenerationPayload = {
  plan_id: string;           // UUID。フロントが先に発行済みの Plan のレコード ID
  evidence_pack_id: string;  // UUID
  transit_matrix: ClientTransitEdge[];
};
```

- [ ] **Step 2: shared-types 同期**

- [ ] **Step 3: Pydantic 同期**

```python
class PlanGenerationPayload(_StrictBase):
    plan_id: UUID
    evidence_pack_id: UUID
    transit_matrix: list[ClientTransitEdge] = Field(max_length=200)
```

- [ ] **Step 4: test_schema_parity 更新**

```python
EXPECTED_FIELDS["PlanGenerationPayload"] = {"plan_id", "evidence_pack_id", "transit_matrix"}
```

- [ ] **Step 5: plan_routes.py は plan_id を受け取るだけ（1.3c 時点は無視）**

1.3c の挙動（Transit Validator + merged pack 返却）は変わらない。merged の model_dump に plan_id は載らないので debug レスポンスも無影響。

ただし `merged = pack.model_copy(update={"transit_matrix": validated})` 以外に plan_id の記録は残さない（1.3d で利用）。TODO コメントで 1.3d での使途を明記:

```python
# TODO(phase-1.3d): payload.plan_id を使って Supabase の plans テーブルから
# owner 検証 + plan_items 保存先を特定する
```

- [ ] **Step 6: test_routes_plans.py 既存テストの `_valid_body` を修正**

```python
def _valid_body(plan_id: str | None = None, pack_id: str | None = None, edges: list[dict] | None = None) -> dict:
    return {
        "plan_id": plan_id or str(uuid4()),
        "evidence_pack_id": pack_id or str(uuid4()),
        "transit_matrix": edges if edges is not None else [_edge("A", "B"), _edge("B", "A")],
    }
```

既存の `test_invalid_uuid_returns_400` は `plan_id` も UUID 違反で落ちるケースを 1 件追加。

- [ ] **Step 7: 全ユニットテスト PASS 確認**

```bash
cd apps/api && .venv/bin/python -m pytest -m "not integration" -v
```

- [ ] **Step 8: コミット提案（Branch 0）**

対象:
- `docs/data-model.md`
- `packages/shared-types/src/index.ts`
- `apps/api/src/schemas/__init__.py`
- `apps/api/src/routes/plan_routes.py`
- `apps/api/tests/test_schema_parity.py`
- `apps/api/tests/test_routes_plans.py`

メッセージ案: `feat(phase-1.3c+): PlanGenerationPayload に plan_id（フロント発行 UUID）を追加し 3 点同期`

---

## Task 1: 依存パッケージ導入 + Providers

**Files:** `apps/web/package.json` / `apps/web/src/app/providers.tsx` / `apps/web/src/app/layout.tsx`

- [ ] **Step 1: パッケージ追加（v2 で `@tanstack/react-query-devtools` を追加、Codex Must-fix #4）**

```bash
cd apps/web
pnpm add @tanstack/react-query @tanstack/react-query-devtools zustand \
  react-hook-form zod @hookform/resolvers \
  @phosphor-icons/react framer-motion react-qr-code \
  mapbox-gl react-map-gl class-variance-authority clsx tailwind-merge
pnpm add -D @testing-library/react @testing-library/dom @testing-library/user-event
```

- [ ] **Step 2: shadcn/ui を公式手順でセットアップ（Tailwind v4 対応済）**

公式ドキュメント https://ui.shadcn.com/docs/tailwind-v4 と https://ui.shadcn.com/docs/installation/next に従う。

```bash
pnpm dlx shadcn@latest init
# プロンプトに対する回答例:
# - Style: new-york (Default でも可、frontend-design.md に違反しない範囲で)
# - Base color: neutral（Design Tokens で上書きするのでここは暫定）
# - CSS variables: Yes
```

初期化後、以下を個別追加:
```bash
pnpm dlx shadcn@latest add button card input label slider select dialog badge separator progress tabs
```

追加後、`components/ui/*.tsx` の色 class（`bg-primary` など）は `globals.css` の `@theme` で再マッピング済みなので、追加編集は最小限。ただし:
- `--color-primary` 等がそのまま使われるはずだが、shadcn テンプレが `bg-zinc-*` を直書きしている場合だけ手動で `bg-[var(--color-primary)]` 的に差し替え
- frontend-design.md の「shadcn/ui のデフォルトテーマそのまま禁止」ルール遵守のため、差し替え忘れチェックを Task 2 Step 7（コミット前）に入れる

- [ ] **Step 3: Providers wrapper を追加**

```tsx
// apps/web/src/app/providers.tsx
"use client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ReactQueryDevtools } from "@tanstack/react-query-devtools";
import { useState, type ReactNode } from "react";

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(() => new QueryClient({
    defaultOptions: {
      queries: { staleTime: 30_000, retry: 1 },
    },
  }));
  return (
    <QueryClientProvider client={client}>
      {children}
      <ReactQueryDevtools initialIsOpen={false} />
    </QueryClientProvider>
  );
}
```

- [ ] **Step 4: layout.tsx で Providers を適用**

既存の `<body>` の中を `<Providers>{children}</Providers>` でラップ。

- [ ] **Step 5: コミット提案**

対象: `apps/web/package.json`, `pnpm-lock.yaml`, `apps/web/src/app/providers.tsx`, `apps/web/src/app/layout.tsx`, `apps/web/components.json`（追加時）
メッセージ案: `chore(frontend-skeleton): UI ライブラリ + React Query / Zustand / shadcn/ui の基盤導入`

---

## Task 2: API クライアント + Zustand + zod + mock fixtures

**Files:** `apps/web/src/lib/api.ts` / `apps/web/src/lib/format.ts` / `apps/web/src/lib/schemas/planForm.ts` / `apps/web/src/lib/mocks/*.ts` / `apps/web/src/stores/generationSessionStore.ts`

- [ ] **Step 1: `lib/format.ts`**

```typescript
const JPY_FORMATTER = new Intl.NumberFormat("ja-JP", {
  style: "currency", currency: "JPY", maximumFractionDigits: 0,
});
export function formatJpy(value: number): string {
  return JPY_FORMATTER.format(value);
}

const DATE_FORMATTER = new Intl.DateTimeFormat("ja-JP", {
  month: "long", day: "numeric", weekday: "short",
});
export function formatMonthDay(iso: string): string {
  return DATE_FORMATTER.format(new Date(iso));
}

const TIME_FORMATTER = new Intl.DateTimeFormat("ja-JP", {
  hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Tokyo",
});
export function formatHHmmJst(iso: string): string {
  return TIME_FORMATTER.format(new Date(iso));
}
```

- [ ] **Step 2: `lib/schemas/planForm.ts`**

```typescript
import { z } from "zod";

export const participantSchema = z.object({
  display_name: z.string().min(1, "名前を入力してください").max(30),
  avatar_color: z.string().regex(/^#[0-9a-fA-F]{6}$/, "HEX カラーを指定"),
  wishes_text: z.string().min(1, "希望を入力してください").max(500),
  tags: z.array(z.string()).default([]),
  order_index: z.number().int().min(0),
});

export const budgetBreakdownSchema = z.object({
  lodging: z.number().int().min(0).max(100),
  meal: z.number().int().min(0).max(100),
  activity: z.number().int().min(0).max(100),
  transit: z.number().int().min(0).max(100),
}).refine(
  (b) => b.lodging + b.meal + b.activity + b.transit === 100,
  { message: "合計が 100% になるように調整してください" },
);

export const planFormSchema = z.object({
  title: z.string().min(1).max(60),
  region: z.string().min(1),
  start_date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
  end_date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
  departure_point: z.string().min(1),
  budget_per_person_jpy: z.number().int().min(1000).max(1_000_000),
  budget_breakdown: budgetBreakdownSchema,
  start_mode: z.enum(["auto", "anchor", "theme"]),
  mode_payload: z.record(z.string(), z.unknown()).nullable(),
  participants: z.array(participantSchema).min(2).max(5),
}).refine(
  (d) => d.start_date <= d.end_date,
  { message: "開始日は終了日より前に指定してください", path: ["end_date"] },
);

export type PlanFormValues = z.infer<typeof planFormSchema>;
```

- [ ] **Step 3: `lib/api.ts`**

```typescript
import type {
  EvidencePlacesResponse,
  GeneratePlanRequest,
  Plan,
  PlanItem,
  Participant,
  PlanGenerationPayload,
} from "shared-types";
import { getSupabaseAccessToken, supabase } from "./supabase";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:5000";

async function authedFetch<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const token = await getSupabaseAccessToken();
  if (!token) {
    throw new ApiError("認証情報がありません。再読み込みしてください。", 401);
  }
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      ...(init.headers ?? {}),
    },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(body.error ?? res.statusText, res.status, body);
  }
  return res.json() as Promise<T>;
}

export class ApiError extends Error {
  constructor(message: string, public status: number, public body?: unknown) {
    super(message);
  }
}

export function postEvidencePlaces(req: GeneratePlanRequest) {
  return authedFetch<EvidencePlacesResponse>("/api/evidence/places", {
    method: "POST",
    body: JSON.stringify(req),
  });
}

export function postPlanGenerate(req: PlanGenerationPayload) {
  return authedFetch<{ plan_id: string | null }>("/api/plans/generate", {
    method: "POST",
    body: JSON.stringify(req),
  });
}

export async function getPlan(planId: string): Promise<Plan> {
  const { data, error } = await supabase
    .from("plans").select("*").eq("id", planId).single();
  if (error) throw new ApiError(error.message, 500, error);
  return data as Plan;
}

export async function getPlanItems(planId: string): Promise<PlanItem[]> {
  const { data, error } = await supabase
    .from("plan_items").select("*")
    .eq("plan_id", planId).order("order_index");
  if (error) throw new ApiError(error.message, 500, error);
  return data as PlanItem[];
}

export async function getParticipants(planId: string): Promise<Participant[]> {
  const { data, error } = await supabase
    .from("participants").select("*")
    .eq("plan_id", planId).order("order_index");
  if (error) throw new ApiError(error.message, 500, error);
  return data as Participant[];
}
```

`lib/supabase.ts` に `getSupabaseAccessToken()` がなければ追加（匿名サインインして token 返す）。

- [ ] **Step 4: Zustand store `stores/generationSessionStore.ts`（v3 で名称・責務修正）**

**責務**: ルート跨ぎの一時 state のみ。フォーム state は react-hook-form で完結するので Zustand には入れない。

```typescript
import { create } from "zustand";
import type { EvidencePlacesPlaceSummary } from "shared-types";

type GenerationSession = {
  plan_id: string;         // crypto.randomUUID() の値、Supabase にも INSERT 済み
  evidence_pack_id: string;
  places: EvidencePlacesPlaceSummary[];
  createdAt: number;       // Date.now()、15 分で無効化
};

type State = {
  session: GenerationSession | null;
  setSession: (session: GenerationSession) => void;
  clearSession: () => void;
};

const SESSION_TTL_MS = 15 * 60 * 1000;

export const useGenerationSessionStore = create<State>((set, get) => ({
  session: null,
  setSession: (session) => set({ session }),
  clearSession: () => set({ session: null }),
}));

export function getActiveSession() {
  const s = useGenerationSessionStore.getState().session;
  if (!s) return null;
  if (Date.now() - s.createdAt > SESSION_TTL_MS) return null;
  return s;
}
```

- [ ] **Step 5: mock fixtures `lib/mocks/*.ts`**

箱根の温泉旅行を題材にした `mockPlan` / `mockPlanItems` / `mockParticipants` / `mockEvidencePlacesResponse` を定義。PlanItem は 1 泊 2 日 × 6〜8 件程度（activity / meal / transit / lodging が混在）。

- [ ] **Step 6: API クライアントの unit テスト**

`lib/api.test.ts` で `fetch` を `vi.stubGlobal` モックし、リクエストパス・ヘッダ・body が期待通りか検証。ApiError の throw も確認。

- [ ] **Step 7: コミット提案**

メッセージ案: `feat(frontend-skeleton): API クライアント + Zustand / zod / mock fixtures の基盤実装`

---

## Task 3: 共通コンポーネント（ロジック持ち）

**Files:** `apps/web/src/components/EvidenceBadge.tsx` / `PlanItem.tsx` / `PlanTimeline.tsx` / `BudgetSummary.tsx` / `BudgetBreakdownSlider.tsx` / `ParticipantTabs.tsx` / `ParticipantForm.tsx` + テスト

- [ ] **Step 1: `EvidenceBadge.tsx`**

```tsx
import { getEvidenceBadgeInfo, type CostConfidence } from "shared-types";
import { CheckCircle, Warning, Question } from "@phosphor-icons/react/dist/ssr";

type Props = { confidence: CostConfidence; sources: readonly string[] };

export function EvidenceBadge({ confidence, sources }: Props) {
  const info = getEvidenceBadgeInfo(confidence, sources);
  const Icon = confidence === "verified" ? CheckCircle
    : confidence === "estimated" ? Warning : Question;
  return (
    <span
      className="inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full"
      style={{ color: `var(${info.colorToken})` }}
      data-variant={info.variant}
    >
      <Icon size={12} weight="fill" />
      {info.label}
    </span>
  );
}
```

テスト: `EvidenceBadge.test.tsx` で 3 variant × 描画 + variant 属性を検証。

- [ ] **Step 2: `PlanItem.tsx`**

Props: `{ item: PlanItem, participantColors?: Record<string, string> }`。`formatHHmmJst` / `formatJpy` / `<EvidenceBadge />` を組み合わせる。デザイナーが className を触れば見た目が変わる構造。

- [ ] **Step 3: `PlanTimeline.tsx`**

`PlanItem[]` を `start_time` の日付でグルーピングし、日付ヘッダ + `<PlanItem>` リストを縦並びで描画。

テスト: 2 日間の fixture を渡して、日付ヘッダが 2 個・アイテムが正しい日付下に配置されることを確認。

- [ ] **Step 4: `BudgetSummary.tsx`**

Props: `{ plan: Plan, planItems: PlanItem[] }`。`plan.budget_breakdown` と `planItems` の `cost_jpy` 合計からカテゴリ別の進捗を描画。`formatJpy` を使う。

- [ ] **Step 5: `BudgetBreakdownSlider.tsx`**

合計 100% を保つ 4 連スライダー。react-hook-form の `Controller` 経由で使う前提。1 つのスライダーを動かすと他が比例配分される実装。

テスト: 任意のスライダーを動かした後、合計が 100% であることを確認。

- [ ] **Step 6: `ParticipantTabs.tsx` + `ParticipantForm.tsx`**

Tabs は shadcn/ui の `Tabs`。2〜5 人を動的追加削除。`ParticipantForm` は display_name / wishes_text / tags の入力。

- [ ] **Step 7: コミット提案**

メッセージ案: `feat(frontend-skeleton): 共通コンポーネント骨組み（EvidenceBadge / PlanTimeline / BudgetSummary / ParticipantTabs 等）`

---

## Task 4: 1.4 ランディングページ

**Files:** `apps/web/src/app/page.tsx`

- [ ] **Step 1: 最小 JSX**

- ヒーロー（主役 CTA = 「旅を計画する」 → `/plan/new` へ遷移）
- 3 軸カード（実在するスポット / 時間的に成立 / 根拠ある予算）
- フッター的な小さい説明

デザイナー担当: className、レイアウト、アニメーション、フォント調整

- [ ] **Step 2: smoke test**

`pages.smoke.test.tsx` で `/` が crash せず render する。CTA に "旅を計画する" テキストが含まれる。

- [ ] **Step 3: コミット提案**

メッセージ案: `feat(frontend-skeleton): 1.4 ランディングページ骨組み`

---

## Task 5: 1.5 希望入力画面（配線フル実装、v2 で生成フロー契約を確定反映）

**Files:** `apps/web/src/app/plan/new/page.tsx` + 配下

- [ ] **Step 1: ページ実装**

- `useForm<PlanFormValues>({ resolver: zodResolver(planFormSchema) })`
- `ParticipantTabs` で参加者 2〜5 人
- `BudgetBreakdownSlider` で配分
- submit 時（v3 生成フロー契約 + status 遷移）:
  1. Supabase 匿名サインイン（未サインインなら）
  2. **フロントで `crypto.randomUUID()` で plan_id を発行**
  3. Supabase に `plans` レコードを INSERT（`id=<発行した UUID>`, session_id, title, region, dates, 予算, start_mode, **`status='draft'`**）。INSERT 失敗なら即エラー表示
  4. `participants` を bulk INSERT（plan_id 紐付け）
  5. `postEvidencePlaces(form)` で `{ evidence_pack_id, places }` 取得
      - **成功時**: `UPDATE plans SET status='generating' WHERE id=<plan_id>`（fire-and-forget で可、失敗しても UI はブロックしない）
      - **失敗時**: `UPDATE plans SET status='failed' WHERE id=<plan_id>` してエラー画面（`try/catch` + finally）
  6. `generationSessionStore.setSession({ plan_id, evidence_pack_id, places, createdAt: Date.now() })` で stash
  7. `router.push("/plan/${plan_id}/generating")` へ遷移（URL にはクエリパラメータ不要）

- [ ] **Step 2: smoke test**

`/plan/new` が render、参加者数が初期 2 人、ボタンラベル「プランを生成」が存在。

- [ ] **Step 3: コミット提案**

メッセージ案: `feat(frontend-skeleton): 1.5 希望入力画面骨組み（フォーム + plan_id 発行 + /api/evidence/places 配線）`

---

## Task 6: 1.6 プラン生成中画面（v2 で Zustand 経由に変更）

**Files:** `apps/web/src/app/plan/[id]/generating/page.tsx`

- [ ] **Step 1: ページ実装**

- mount 時に `useGenerationSessionStore` から `{ plan_id, evidence_pack_id, places, createdAt }` を取り出す
- セッション無し or 15 分以上古い → `router.replace("/plan/new")`
- URL パラメータの `id` と Zustand の `plan_id` が不一致なら **Zustand を真実として扱う**（URL パラメータは単なる見た目、Zustand は session-scoped で書き換え不能）。不一致時は `router.replace("/plan/${session.plan_id}/generating")` で URL を揃える
- フロントの `fetchTransitMatrix(places, Date)` を呼ぶ（1.3b で実装済、SDK 未ロード or エラーは fail-soft で空配列扱い）
- 取得した `transit_matrix` + `evidence_pack_id` + Zustand の `plan_id` で `postPlanGenerate({ plan_id, evidence_pack_id, transit_matrix })` を呼ぶ（Task 0 で payload 拡張済み）
  - **失敗時**: `UPDATE plans SET status='failed' WHERE id=<plan_id>` してエラー画面（「もう一度試す」導線つき）
- 1.3c 時点のレスポンス `{ plan_id: null }` の扱い:
  - `NEXT_PUBLIC_USE_MOCKS=1`: Zustand の `plan_id` をそのまま使って `router.push("/plan/${plan_id}")` へ遷移（デザイン確認用）
  - それ以外（1.3d 完成後）: レスポンスの `plan_id` を信じる（常に Zustand と同じ UUID が返る想定）
- 進捗インジケーター: 5 段階のドットを表示、アニメーションは後付け（Framer Motion はデザイナー仕上げで実装）

- [ ] **Step 2: smoke test**

Zustand に session を事前投入した状態で `/plan/<uuid>/generating` が render、エラーなく描画される。

- [ ] **Step 3: コミット提案**

メッセージ案: `feat(frontend-skeleton): 1.6 プラン生成中画面骨組み（Zustand 経由で session 取得 + transit + /api/plans/generate kick）`

---

## Task 7: 1.7 プラン閲覧画面（v3 で `initialData` 撤廃）

**Files:** `apps/web/src/app/plan/[id]/page.tsx`

- [ ] **Step 1: ページ実装（モック切替は `lib/api.ts` 内側で完結、v3 修正）**

```typescript
// page.tsx 側は単に useQuery を呼ぶだけ。モック切替ロジックはここに書かない
const { data: plan, isLoading, error } = useQuery({
  queryKey: ["plan", id],
  queryFn: () => getPlan(id),  // getPlan が NEXT_PUBLIC_USE_MOCKS を見て分岐する
});
```

`lib/api.ts` 側:

```typescript
const USE_MOCKS = process.env.NEXT_PUBLIC_USE_MOCKS === "1";

export async function getPlan(planId: string): Promise<Plan> {
  if (USE_MOCKS) {
    // 実 fetch は走らず、mockPlan を即 resolve
    return mockPlan;
  }
  const { data, error } = await supabase.from("plans").select("*").eq("id", planId).single();
  if (error) throw new ApiError(error.message, 500, error);
  return data as Plan;
}
```

これで `initialData` を使わず、query 層はモック/実の違いを知らない。プロダクトコードは一貫して「実データ前提」に書ける。

- 3 カラム: タイムライン（主役）/ 予算サマリ / ミニマップ
- タブで「タイムライン / マップ / 予算」を切り替え（shadcn/ui `Tabs`）

- [ ] **Step 2: smoke test**

`NEXT_PUBLIC_USE_MOCKS=1` 下で `/plan/<any>` が render、少なくとも 1 件の `PlanItem` が描画される。

- [ ] **Step 3: コミット提案**

メッセージ案: `feat(frontend-skeleton): 1.7 プラン閲覧画面骨組み（タイムライン + 予算 + マップの 3 カラム、queryFn モック分岐）`

---

## Task 8: 1.8 地図ビュー

**Files:** `apps/web/src/components/MapView.tsx`（詳細実装）+ Task 7 で MapView を差し込み

- [ ] **Step 1: Mapbox 初期化**

```tsx
"use client";
import Map, { Marker } from "react-map-gl/mapbox";
import "mapbox-gl/dist/mapbox-gl.css";

type Props = { items: PlanItem[] };

export function MapView({ items }: Props) {
  const token = process.env.NEXT_PUBLIC_MAPBOX_TOKEN;
  if (!token) return <ErrorState message="Mapbox トークンが設定されていません" />;

  const positioned = items.filter(i => i.location.lat && i.location.lng);
  const center = positioned[0] ?? { location: { lat: 35.68, lng: 139.76 } };

  return (
    <Map
      mapboxAccessToken={token}
      initialViewState={{
        latitude: center.location.lat ?? 35.68,
        longitude: center.location.lng ?? 139.76,
        zoom: 11,
      }}
      style={{ width: "100%", height: "100%" }}
      mapStyle="mapbox://styles/mapbox/light-v11"
    >
      {positioned.map(i => (
        <Marker key={i.id} latitude={i.location.lat!} longitude={i.location.lng!} />
      ))}
    </Map>
  );
}
```

- [ ] **Step 2: 経路ポリラインは後付け**（1.8 本番実装時に polyline decode + Source/Layer 追加）

- [ ] **Step 3: コミット提案**

メッセージ案: `feat(frontend-skeleton): 1.8 地図ビュー骨組み（Mapbox 初期化 + マーカー描画）`

---

## Task 9: 1.9 プラン共有画面

**Files:** `apps/web/src/app/plan/[id]/share/page.tsx` / `apps/web/src/components/ShareQRCode.tsx`

- [ ] **Step 1: ページ実装**

- `useQuery` で `plan` を取得
- `share_token` が無ければ「共有を有効化」ボタン → `POST /api/plans/:id/share`（このエンドポイントは DB 担当メンバー B の 1.9 タスクで実装予定、骨組み時点は未接続で OK）
- ある場合は QR + URL 表示（`react-qr-code`）

- [ ] **Step 2: smoke test**

`/plan/<id>/share` が render。

- [ ] **Step 3: コミット提案**

メッセージ案: `feat(frontend-skeleton): 1.9 プラン共有画面骨組み（QR コード + 共有 URL）`

---

## Task 10: ハンドオフ資料と todo.md 更新

**Files:** `tasks/handoff-frontend.md` / `tasks/handoff-db.md` / `tasks/todo.md`

- [ ] **Step 1: `tasks/handoff-frontend.md`** — デザイナー向け。触ってよい場所/ダメな場所、Design Tokens 変更手順、各コンポーネントの Props、動作確認コマンドを記載
- [ ] **Step 2: `tasks/handoff-db.md`** — メンバー B 向け。DB/バックエンドの整理系タスクを列挙
- [ ] **Step 3: `tasks/todo.md`** — Phase 1.4〜1.9 の各項目を「骨組み済」と「デザイン担当に引き渡し」に分けて再記述

- [ ] **Step 4: コミット提案**

メッセージ案: `docs(frontend-skeleton): ハンドオフ資料 + todo.md の優先度再編`

---

## 実装フロー（v3 で 6 ブランチに分割: Branch 0〜5）

### Branch 0: `feat/plan-generation-plan-id`（Task 0、**1.3c マージ後に着手**）

`PlanGenerationPayload` 拡張 + 3 点同期 + `plans.status` カラム追加。1.3c の変更を前提にするので、必ず 1.3c を develop にマージした後に開始する。

1. `feat/plan-generation-plan-id` を `develop` から切る（1.3c マージ済み前提）
2. Task 0 を全ステップ実行 → コミット
3. `pnpm --filter api test`（unit）全 PASS 確認 → ユーザが develop にマージ

### Branch 1: `feat/frontend-foundation`（Task 1〜3、Branch 0 と並列可）

依存導入 + API 基盤 + 共通コンポーネント。Branch 0 の型変更に依存するのは API クライアントの `postPlanGenerate` シグネチャくらい。Branch 0 マージ後に shared-types を pull して再ビルドすれば問題なし。

1. `feat/frontend-foundation` を `develop` から切る
2. Task 1（依存導入 + Providers）→ コミット
3. Task 2（API クライアント + Zustand + zod + mocks）→ コミット
4. Task 3（共通コンポーネント）→ コミット
5. `pnpm --filter web test` 全 PASS 確認 → ユーザが develop にマージ

### Branch 2: `feat/frontend-core-flow`（Task 4〜6、**Branch 0 + 1 マージ後に着手**）

MVP 生成フロー 3 画面。Branch 0（`plan_id` 型）と Branch 1（API クライアント・Zustand・共通コンポーネント）に依存。

1. `feat/frontend-core-flow` を `develop` から切る
2. Task 4（1.4 ランディング）→ コミット
3. Task 5（1.5 希望入力、フォーム + plan_id 発行 + `/api/evidence/places` 配線）→ コミット
4. Task 6（1.6 生成中）→ コミット
5. `NEXT_PUBLIC_USE_MOCKS=1 pnpm dev` で `/` → `/plan/new` → `/plan/<id>/generating` の遷移確認 → Codex レビュー → ユーザが develop にマージ

### Branch 3: `feat/frontend-plan-view`（Task 7、Branch 2 マージ後）

プラン閲覧画面。Task 6 完了で「生成 → `/plan/[id]` へ遷移」が成立するので、そこから受ける側を独立ブランチとして実装。

1. `feat/frontend-plan-view` を `develop` から切る
2. Task 7（1.7 プラン閲覧）→ コミット
3. `NEXT_PUBLIC_USE_MOCKS=1 pnpm dev` で `/plan/<mock>` 描画確認 → ユーザが develop にマージ

### Branch 4: `feat/frontend-extra-pages`（Task 8〜9、**Branch 3 マージ後**）

地図と共有。Task 8 の Mapbox は 1.7 に差し込むため Branch 3 に依存。

1. Task 8（1.8 Mapbox + 1.7 への差し込み）→ コミット
2. Task 9（1.9 共有画面骨組み）→ コミット

### Branch 5: `feat/frontend-handoff`（Task 10、全 Branch マージ後）

handoff 資料 + todo.md + architecture.md 更新を最終化。

## 懸念 / 未決事項

- **`getSupabaseAccessToken` の匿名サインイン自動化**: 初回アクセス時にサインインして localStorage に保存する実装が必要（Next.js の SSR 前提を崩さずに）→ Task 2 の `lib/supabase.ts` で `useSession` 相当の hook 化を検討
- **Supabase の RLS**: 1.7 の `getPlan/getPlanItems` が RLS で空配列になる懸念 → メンバー B の DB-2 で E2E 確認（別タスク、ここでブロックしない）
- **1.3d 完成時の動作**: 現在は `/api/plans/generate` が `{plan_id: null}` を返すが 1.3d で `{plan_id: <payload.plan_id と同じ UUID>}` に変わる。payload の plan_id を直接 Supabase の plans テーブルで owner 検証する方針なので、競合曖昧さなし（Task 0 で確定）
- **zod スキーマのドリフト検出**: zod と shared-types は手動同期。将来 `zodToTs` 的なコード生成 or 逆向きの静的検査を入れるべきだが、今回は Nice-to-have（Codex 再レビューコメント）

## Nice-to-have（余力があれば）

- zod と shared-types のドリフト検出テスト（1 件、型レベルでの一致確認）
- Task 10 で `docs/architecture.md` 5 節のデータフローに「plan_id はフロント発行、API は plan_items のみ INSERT」を明記
- Storybook 導入（デザイナーが各コンポーネントのバリエーションを見る用）→ スコープ外、Phase 1.10 以降
