# フロント引き継ぎ資料 — デザイン担当向け

**ステータス（2026-04-21 時点）**: Phase 1.4〜1.9 の**骨組み実装は計画フェーズ完了、実装は未着手**。
Claude/Manato 側で 6 ブランチに分割して順に実装予定:
`feat/plan-generation-plan-id`（Branch 0）→ `feat/frontend-foundation`（Branch 1）→ `feat/frontend-core-flow`（Branch 2）→ `feat/frontend-plan-view`（Branch 3）→ `feat/frontend-extra-pages`（Branch 4）→ `feat/frontend-handoff`（Branch 5）。
本資料は「骨組み完成時点の状態」を記述しており、実装完了 PR と一緒に最新化される。詳細は @tasks/plans/2026-04-21-frontend-skeleton.md を参照。

この資料は「デザイン担当として、何を触って、何を触らなくていいか」を示す。

## 担当範囲

- **触ってよい**: 見た目（`className` / レイアウト / アニメーション / スペーシング）、Design Tokens 微調整、shadcn/ui コンポーネントのスタイル、画像/アイコン差し替え
- **触らないでほしい**: API クライアント (`lib/api.ts`) / Zustand ストア (`stores/`) / zod スキーマ (`lib/schemas/`) / モックデータ (`lib/mocks/`) / shared-types / Pydantic スキーマ

もし「API を変えたい」「型を変えたい」と感じたら **Manato に相談**。`docs/data-model.md` と `docs/evidence-pack.md` は Manato 管轄で、他人が変えるとフロント・バック両方が壊れる。

## 画面一覧と状態（骨組み実装完了後の想定状態）

| 画面 | パス | 骨組み状態（予定） | 主な責務 |
|---|---|---|---|
| ランディング | `/` | 最小 JSX + smoke test | CTA「旅を計画する」→ `/plan/new` |
| 希望入力 | `/plan/new` | フォーム配線完了（react-hook-form + zod） | 2〜5 人の希望 + 予算配分 + 期間 → `plans` INSERT（status=draft）→ `/api/evidence/places` 呼び出し → 成功時 status=generating / 失敗時 status=failed → Zustand stash → `/plan/<uuid>/generating` へ遷移 |
| プラン生成中 | `/plan/[id]/generating` | transit 取得 + `/api/plans/generate` kick 完了 | 進捗アニメ + 完了時 `/plan/[id]` へ遷移 |
| プラン閲覧 | `/plan/[id]` | Supabase 直接読み取り配線完了 | タイムライン / 予算 / マップの 3 カラム |
| プラン共有 | `/plan/[id]/share` | 骨組みのみ、`POST /api/plans/:id/share` は DB 担当 B が実装中 | QR + 共有 URL |

**plan_id のライフサイクル**: フロントが `crypto.randomUUID()` で発行し、`/plan/new` submit 時に Supabase に plans レコードを INSERT する。Flask 側の `/api/plans/generate` は plan_items を後から INSERT するだけ（plan_id の発行責任はフロント、架空の id は生成しない）。詳細は @docs/architecture.md 参照。

## Design Tokens の変更手順

ファイル: [apps/web/src/app/globals.css](apps/web/src/app/globals.css)

```css
@theme {
  --color-primary: #D97757;   /* ← ここを変えれば全 UI の primary が変わる */
  ...
}
```

- `--color-*` / `--spacing-*` / `--radius-*` / `--font-*` は Tailwind v4 の `@theme` ディレクティブで定義
- 色を変えたら `.claude/rules/frontend-design.md` の Design Tokens 節もあわせて更新（Claude が今後参照するルールなので、ずれると変な提案をしてくる）
- Phosphor Icons の色は `style={{ color: "var(--color-primary)" }}` で指定（Tailwind クラスで書くなら `text-primary` だが shadcn/ui のデフォルト text クラスは Design Tokens 経由で設定済）

## 絶対に守ってほしいルール（`.claude/rules/frontend-design.md` より）

- **Inter フォント禁止** → Noto Sans JP + Zen Kaku Gothic New（既に layout.tsx で設定済）
- **Lucide のみの使用禁止** → Phosphor Icons をデフォルトに（`@phosphor-icons/react`）
- **青→紫の AI グラデーション禁止**
- **shadcn/ui のデフォルトテーマそのまま禁止** → Design Tokens で上書き済。新規コンポーネントを追加する時もトークン参照を守る
- **汎用ヒーロー禁止**（中央揃えの巨大テキスト + 装飾的背景 + 曖昧なキャッチコピー）
- **数字は `Intl.NumberFormat('ja-JP')`**。`lib/format.ts` の `formatJpy()` / `formatMonthDay()` / `formatHHmmJst()` を使う
- **絵文字禁止**（UI の意味伝達は Phosphor アイコンで）

## 耐久性チェック（納品前に必ず）

- 長文（30 文字以上のスポット名、3 行以上の説明）で崩れない
- 0 件 / Empty State で画面が成立（特に 1.7 プラン閲覧）
- ローディング / エラー状態を用意（`components/ui/states/` の `<LoadingState />` / `<ErrorState />` / `<EmptyState />` を使う）
- 参加者 2 人でも 5 人でも破綻しないレイアウト（タブ/カードは動的可変）

## 動作確認コマンド

```bash
# フロント + API 同時起動
pnpm dev

# フロントのみ（モックデータ使用）
cd apps/web
NEXT_PUBLIC_USE_MOCKS=1 pnpm dev

# テスト
pnpm --filter web test

# ビルドチェック（本番形式で描画確認）
pnpm --filter web build
pnpm --filter web start
```

`NEXT_PUBLIC_USE_MOCKS=1` を付けると `/plan/[id]` が 1.3d 完成を待たずに描画できる（箱根 1 泊 2 日の fixture）。

## 配置ルール（frontend-design.md 抜粋）

```
apps/web/src/
├── app/                  # Next.js App Router（ページ）
├── components/
│   ├── ui/               # shadcn/ui ベース（Design Tokens 済）
│   └── その他            # プロジェクト固有コンポーネント
├── lib/                  # API クライアント / フォーマッタ / schema / mock
└── stores/               # Zustand
```

- `"use client"` はデフォルト禁止。状態 / 効果が必要な場所だけ付与
- `key` prop に array index を使わない（安定した id を使う）
- 外部データ取得は `@tanstack/react-query`、フォームは `react-hook-form + zod`、アニメは `framer-motion`

## スクショ運用

スクショをデザイン基準として渡してもらったら「そのスタイルを模倣する」のがルール。
色・余白・フォントが Design Tokens と違う場合はスクショを優先し、`globals.css` と `frontend-design.md` を更新する。

## 困ったら

- 型の質問: Manato（`docs/data-model.md` / `packages/shared-types/src/index.ts` 参照）
- API の質問: Manato（`docs/architecture.md` / `docs/evidence-pack.md` 参照）
- デザインの方針: `.claude/rules/frontend-design.md` が正典。変えたいならその場で更新 OK（ただし理由を commit message に残す）
- 何をやるか迷った時: `tasks/todo.md` の Phase 1.4〜1.9 のチェックリスト参照
