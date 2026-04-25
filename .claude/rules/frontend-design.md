---
paths:
  - "apps/web/src/**/*.tsx"
  - "apps/web/src/**/*.ts"
  - "apps/web/**/*.css"
---

# Frontend Design Rules

## 前提

**ビジュアル詳細は実装中に調整する**。このファイルは「最低限守るべき骨格」と「絶対にやってはいけないこと」のみ定める。
カラートークン・フォントの微調整は、実際の画面を見ながら変更してよい（`app/globals.css` の CSS 変数を書き換える運用）。

## 基調: blue hour 和モダン

Routeful は対面で 2〜5 人が 1 画面を囲んで合意形成する場。派手さより「静けさ」と「情緒」を優先する。
- Deep Navy × Coral × 和紙クリーム = "blue hour"（夕暮れの青い時間帯）の配色
- 見出しは明朝体、本文はゴシック
- 英字ラベル（例: "ROUTEFUL" / "WHY ROUTEFUL" / "DAY 1"）を `letter-spacing: 0.18em` 程度で添えて余白にリズムを作る
- HTML モック `tabiai2_interactive_blue_hour.html`（ユーザ共有済み）が視覚基準

## Design Tokens（現行）

```css
/* apps/web/src/app/globals.css */
@theme {
  /* Colors — blue hour 和モダン */
  --color-primary: #042C53;        /* Deep Navy - 主役 CTA、見出し */
  --color-accent: #F0997B;         /* Coral - アクセント、旅情 */
  --color-secondary: #2C5F5D;      /* Deep Teal - 補助（旧 primary から降格、Evidence verified 近傍用途） */
  --color-background: #F5EFE6;     /* 和紙クリーム */
  --color-surface: #FFFFFF;        /* カード背景 */
  --color-text-primary: #042C53;   /* Deep Navy */
  --color-text-secondary: #3C5B8F; /* Blue Gray */
  --color-text-tertiary: #7A8AA8;  /* Lighter Blue Gray */
  --color-border: rgba(4, 44, 83, 0.12);

  /* Evidence バッジ専用（機能色、ブランドと独立で維持） */
  --color-evidence-verified: #3A7D44;   /* ✓ Places / Routes で検証済み */
  --color-evidence-estimated: #E8A951;  /* ~ 推定値 */
  --color-evidence-unknown: #C54B4B;    /* ? 検証不可 */

  /* Spacing (8px grid) */
  --spacing-1: 4px;  --spacing-2: 8px;  --spacing-3: 12px;
  --spacing-4: 16px; --spacing-5: 24px; --spacing-6: 32px;
  --spacing-7: 48px;

  /* Radius */
  --radius-sm: 4px;
  --radius-md: 8px;
  --radius-lg: 12px;

  /* Typography — next/font が注入する CSS 変数を優先 */
  --font-heading: var(--font-noto-serif-jp), "Hiragino Mincho ProN", "Noto Serif JP", serif;
  --font-body: var(--font-noto-sans-jp), "Hiragino Sans", "Noto Sans JP", system-ui, sans-serif;
  --font-mono: "DM Sans", "JetBrains Mono", monospace;

  /* Letter spacing（英字ラベル用） */
  --tracking-label: 0.18em;
  --tracking-wide: 0.08em;
}
```

**変更履歴**: 2026-04-25 に旧テラコッタ主導（`#D97757` / Zen Kaku Gothic）から現行の Deep Navy + Coral + Noto Serif JP（明朝体）に転換。HTML モック "blue hour" が基準。

## 表層のアンチパターン（AI感を消す）

デフォルトに戻ったAI生成UIは一目で見分けがつく。以下は**禁止**：

- **Interフォント禁止**。`--font-body` に Noto Sans JP、`--font-heading` に Noto Serif JP（明朝体）を使う。見出しゴシックへの回帰（Zen Kaku Gothic New 等）は blue hour 方針に反するので不可
- **Lucide アイコンのみの使用禁止**。Phosphor Icons をデフォルトとする（`@phosphor-icons/react`）
- **青→紫のAIグラデーション禁止**。グラデーション自体を最小限に
- **shadcn/ui のデフォルトテーマそのまま禁止**。必ず上記デザイントークンで上書き
- **汎用的なヒーロー**（中央揃えの巨大テキスト + 装飾的背景 + 曖昧なキャッチコピー）禁止
- **数字は必ず `Intl.NumberFormat('ja-JP')` で整形**。`¥48200` ではなく `¥48,200`
- **絵文字を UI の意味伝達に使わない**。Phosphor アイコンで統一

## 構造のアンチパターン（情報設計）

- **全要素を均一なサイズ・ウェイトで並べない**。画面の主役を 1 つ決めてメリハリをつけろ
  - メイン画面なら「タイムライン」が主役。予算サマリとマップは脇役
  - ランディングなら「旅を計画する」CTAが主役
- **UIパターンを機械的に当てはめない**。「この画面で何をさせたいか」を先に定義せよ
- **便利そうな要素を全部載せない**。迷ったら削れ
- **色は役割で分けろ**。同じ色に複数の意味を持たせるな
  - `--color-primary` = ブランド色、主要 CTA、選択状態
  - `--color-secondary` = サブアクション
  - `--color-evidence-*` = 根拠の確度、プランアイテム専用
  - `--color-danger` = エラー・削除、それ以外では使うな

## 耐久性のアンチパターン（実運用想定）

- 長文（30文字以上の名前、3行以上の説明）で崩れないか確認せよ
- 0件 / Empty State で画面が成立するようにせよ
- ローディング状態・エラー状態を必ず定義せよ
- 参加者が2人でも5人でも破綻しないレイアウトにせよ（タブ/カードの動的可変）

## コンポーネント実装規則

- **クライアントコンポーネントを最小限に**。デフォルトは Server Component、`"use client"` は状態や効果が必要な場所だけ
- **`key` prop に array index を使うな**。安定した id を使え
- **フォームは `react-hook-form` + `zod` で型安全に**
- **外部データ取得は `@tanstack/react-query`**。ローディング/エラー/成功の3状態を明示的に扱う
- **アニメーションは Framer Motion**。ページ遷移は fade、要素出現は spring

## ファイル配置

```
apps/web/src/
├── app/                     # Next.js App Router
│   ├── page.tsx            # ランディング (01)
│   ├── plan/
│   │   ├── new/page.tsx    # 希望入力 (04)
│   │   └── [id]/
│   │       ├── page.tsx    # プラン閲覧 (06)
│   │       ├── generating/page.tsx  # 生成中 (05)
│   │       └── share/page.tsx       # 共有 (08)
├── components/             # 再利用コンポーネント
│   ├── ui/                 # shadcn/ui ベース（トークン上書き済）
│   ├── PlanTimeline.tsx
│   ├── PlanItem.tsx
│   ├── EvidenceBadge.tsx
│   ├── BudgetSummary.tsx
│   ├── MapView.tsx
│   └── ParticipantTabs.tsx
├── lib/                    # ユーティリティ
│   ├── api.ts              # Flask API クライアント
│   ├── supabase.ts         # Supabase クライアント
│   └── format.ts           # 数値・日時フォーマッタ
└── stores/                 # Zustand ストア
    └── planStore.ts
```

## スクショが渡されたら

ユーザーがスクショを渡してきたら、**そのスタイルを模倣せよ**。想像で補完するな。
色・余白・フォントが指定と違う場合は、指定を優先し、このファイルを更新せよ。
