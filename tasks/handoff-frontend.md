# フロント引き継ぎ資料 — デザイン担当向け

**ステータス（2026-04-25 更新）**: Phase 1.4〜1.9 の**骨組み実装は develop にマージ完了**。
デザイン作業を開始できる状態です。
骨組み時点からの主な追加情報:
- `/api/plans/generate` は Phase 1.3d で本配線完了（LLM 生成 → plan_items 保存まで動く）。ただし実環境検証でハルシネーション 10% 発生中、Manato がプロンプトチューニング予定（デザイン作業と独立、UI の動作確認には影響なし）
- `POST /api/plans/:id/share` と `GET /api/plans/shared/:token` の契約型（`ShareResponse` / `SharedPlanResponse`）は shared-types / Pydantic に **3 点同期済み**。DB 担当が Flask 実装すれば 1.9 共有画面がフル機能になる

骨組みは以下の 6 ブランチに分けて順次実装されました:

1. `feat/plan-generation-plan-id` — `PlanGenerationPayload.plan_id` + `plans.status` 追加
2. `feat/frontend-foundation` — 依存導入 + shadcn/ui + API クライアント + Zustand + zod + 共通コンポーネント
3. `feat/frontend-core-flow` — 1.4 ランディング + 1.5 希望入力 + 1.6 生成中
4. `feat/frontend-plan-view` — 1.7 プラン閲覧
5. `feat/frontend-extra-pages` — 1.8 Mapbox + 1.9 共有
6. `feat/frontend-handoff` — 本資料 + 仕上げ修正

## 担当範囲

- **触ってよい**: 見た目（`className` / レイアウト / アニメーション / スペーシング）、Design Tokens 微調整、shadcn/ui コンポーネントのスタイル、画像/アイコン差し替え、Framer Motion によるアニメ追加
- **触らないでほしい**: API クライアント (`lib/api.ts`) / Zustand ストア (`stores/`) / zod スキーマ (`lib/schemas/`) / モックデータ (`lib/mocks/`) / shared-types / Pydantic スキーマ

API や型を変えたい場合は **Manato に相談**。`docs/data-model.md` と `docs/evidence-pack.md` は Manato 管轄で、勝手に変えるとフロント・バック両方が壊れます。

## 画面一覧と骨組み状態

| 画面 | パス | 状態 | 主な責務 |
|---|---|---|---|
| ランディング | `/` | ✅ 配線済み | CTA「旅を計画する」→ `/plan/new` |
| 希望入力 | `/plan/new` | ✅ フォーム配線完了 | 2〜5 人の希望 + 予算配分 + 期間 → plans INSERT (status=draft) → `/api/evidence/places` → 成功時 status=generating / 失敗時 status=failed → Zustand stash → `/plan/<uuid>/generating` |
| プラン生成中 | `/plan/[id]/generating` | ✅ 配線済み | Zustand から session 取得 → transit 取得 → `/api/plans/generate` kick → 完了時 `/plan/[id]` へ遷移（成功時 session を clear） |
| プラン閲覧 | `/plan/[id]` | ✅ データ取得配線完了 | タイムライン / 予算 / マップの 3 カラム、shadcn Tabs で切替 |
| 地図ビュー | プラン閲覧のマップタブ | ✅ Mapbox 初期化済み | マーカー表示、ポリラインは Phase 1.8 本実装で追加 |
| プラン共有 | `/plan/[id]/share` | 🟡 UI のみ | QR + URL コピー表示。`POST /api/plans/:id/share`（DB-4）と `GET /api/plans/shared/:token`（DB-5）は DB 担当実装待ち。契約型は 2026-04-25 に 3 点同期済みなのでフロント側の `lib/api.ts` 追加は contract 通りに書けば通る |

**plan_id のライフサイクル**: フロントが `crypto.randomUUID()` で発行し、`/plan/new` submit 時に Supabase の `plans` テーブルへ INSERT する。Flask の `/api/plans/generate` は payload.plan_id をそのまま使い、1.3d で `plan_items` を後から INSERT する。詳細は @docs/architecture.md / @docs/data-model.md 参照。

**plans.status の遷移**:

| きっかけ | status | 更新主体 |
|---|---|---|
| `plans` INSERT（1.5 submit 直後） | `draft` | フロント（1.5） |
| `/api/evidence/places` 成功 | `generating` | フロント（1.5） |
| `/api/evidence/places` 失敗 / `/api/plans/generate` 失敗 | `failed` | フロント（1.5 / 1.6） |
| LLM 生成成功 + plan_items INSERT（Phase 1.3d） | `succeeded` | サーバー |
| 1.6 中断・放置 | `generating` のまま | なし → DB-3 で 1h 後清掃 |

## Design Tokens の変更手順

ファイル: [apps/web/src/app/globals.css](apps/web/src/app/globals.css)

```css
@theme {
  --color-primary: #d97757;   /* ← 変えれば全 UI の primary が変わる */
  --color-secondary: #2c5f5d;
  --color-background: #faf7f2;
  --color-evidence-verified: #3a7d44;
  --color-evidence-estimated: #e8a951;
  --color-evidence-unknown: #c54b4b;
  ...
}
```

- `--color-*` / `--spacing-*` / `--radius-*` / `--font-*` は Tailwind v4 の `@theme` で定義
- shadcn/ui のデフォルト色（`--primary` / `--background` 等）は `:root` ブロックで Design Tokens の値にマッピング済み。こちらは触らなくても連動する
- 色を変えたら `.claude/rules/frontend-design.md` の Design Tokens 節もあわせて更新（Claude が参照するルール）

## 絶対に守ってほしいルール（`.claude/rules/frontend-design.md` より）

- **Inter フォント禁止** → Noto Sans JP + Zen Kaku Gothic New（既に layout.tsx で設定済み）
- **Lucide のみの使用禁止** → Phosphor Icons がデフォルト（shadcn のセレクト/ダイアログ等の内部は Lucide のまま。表に出る UI は Phosphor に寄せる）
- **青→紫の AI グラデーション禁止**
- **shadcn/ui のデフォルトテーマそのまま禁止** → globals.css で上書き済み
- **汎用ヒーロー禁止**（中央揃えの巨大テキスト + 装飾的背景 + 曖昧なキャッチコピー）
- **数字は `Intl.NumberFormat('ja-JP')`** → `lib/format.ts` の `formatJpy()` / `formatMonthDay()` / `formatHHmmJst()` / `formatDurationMin()` / `formatDateRange()` を使う
- **絵文字禁止**（UI の意味伝達は Phosphor アイコンで）

## 耐久性チェック（納品前に必ず）

- 長文（30 文字以上のスポット名、3 行以上の説明）で崩れない
- 0 件 / Empty State で画面が成立（特に 1.7 プラン閲覧、1.8 マップ）→ `<EmptyState />` を使う
- ローディング / エラー状態を用意 → `components/ui/states/` の `<LoadingState />` / `<ErrorState />` / `<EmptyState />` を使う
- 参加者 2 人でも 5 人でも破綻しないレイアウト（タブ/カードは動的可変）

## 動作確認コマンド

```bash
# フロント + API 同時起動
pnpm dev

# モックデータ使用（デザイン確認用、API 不要）
cd apps/web
NEXT_PUBLIC_USE_MOCKS=1 pnpm dev

# テスト
pnpm --filter web test

# 型チェック
pnpm --filter web exec tsc --noEmit

# ビルド
pnpm --filter web build
```

`NEXT_PUBLIC_USE_MOCKS=1` 時は:
- `/api/evidence/places` / `/api/plans/generate` を呼ばず即モック返却
- `/plan/[id]` は箱根 1 泊 2 日の fixture（8 アイテム + 3 参加者）で描画
- **ただし匿名サインインだけは実行される**（Supabase のテーブルには実書き込みしない）

## ファイル配置

```
apps/web/src/
├── app/
│   ├── layout.tsx / providers.tsx
│   ├── globals.css                  ← Design Tokens（ここを触れば全 UI に伝播）
│   ├── page.tsx                     ← 1.4 ランディング
│   ├── plan/new/page.tsx            ← 1.5 希望入力
│   └── plan/[id]/
│       ├── page.tsx                 ← 1.7 プラン閲覧
│       ├── generating/page.tsx      ← 1.6 生成中
│       └── share/page.tsx           ← 1.9 共有
├── components/
│   ├── ui/                          ← shadcn/ui ベース（Design Tokens 済）
│   ├── ui/states/                   ← LoadingState/ErrorState/EmptyState
│   ├── EvidenceBadge.tsx
│   ├── PlanTimeline.tsx / PlanItem.tsx
│   ├── BudgetSummary.tsx / BudgetBreakdownSlider.tsx
│   ├── ParticipantTabs.tsx / ParticipantForm.tsx
│   ├── MapView.tsx / ShareQRCode.tsx
├── lib/
│   ├── api.ts                       ← Flask + Supabase（NEXT_PUBLIC_API_BASE_URL）
│   ├── supabase.ts                  ← ensureAnonymousSession など
│   ├── transit.ts                   ← Maps JS SDK ラッパー（Phase 1.3b）
│   ├── format.ts                    ← Intl フォーマッタ
│   ├── schemas/planForm.ts          ← zod
│   └── mocks/*.ts                   ← fixture（触らない）
└── stores/generationSessionStore.ts ← 15 分 TTL の一時セッション
```

## コンポーネント実装規則

- **`"use client"` は最小限に**。状態 / 効果 / イベントハンドラが必要な場所だけ付与
- **`key` prop に array index を使わない**（安定した id を使う）
- 外部データ取得は `@tanstack/react-query`、フォームは `react-hook-form + zod`、アニメは `framer-motion`
- 数字・日時は必ず `lib/format.ts` のフォーマッタ経由

## スクショ運用

スクショをデザイン基準として渡してもらったら「そのスタイルを模倣する」のがルール。
色・余白・フォントが Design Tokens と違う場合はスクショを優先し、`globals.css` と `.claude/rules/frontend-design.md` を更新する。

## 困ったら

- 型の質問: Manato（`docs/data-model.md` / `packages/shared-types/src/index.ts` 参照）
- API の質問: Manato（`docs/architecture.md` / `docs/evidence-pack.md` 参照）
- デザインの方針: `.claude/rules/frontend-design.md` が正典。変えたければその場で更新 OK（理由を commit message に残す）
- 共有機能の API: メンバー B（`tasks/handoff-db.md` DB-4〜DB-6）
- 何をやるか迷った時: `tasks/todo.md` の 1.4〜1.9 デザイン着地セクション
