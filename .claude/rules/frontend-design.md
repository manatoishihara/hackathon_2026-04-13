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

## Design Tokens（初期値）

```css
/* apps/web/src/app/globals.css */
:root {
  /* Colors */
  --color-primary: #D97757;        /* テラコッタ、CTAと強調 */
  --color-secondary: #2C5F5D;      /* Deep Teal、サブアクション */
  --color-background: #FAF7F2;     /* オフホワイト、ページ背景 */
  --color-surface: #FFFFFF;        /* カード背景 */
  --color-text-primary: #1A1A1A;
  --color-text-secondary: #6B6B6B;
  --color-text-tertiary: #9B9B9B;
  --color-border: rgba(0, 0, 0, 0.08);

  /* Evidence バッジ専用 */
  --color-evidence-verified: #3A7D44;   /* ✓ Places / Routes で検証済み */
  --color-evidence-estimated: #E8A951;  /* ~ 推定値 */
  --color-evidence-unknown: #C54B4B;    /* ? 検証不可 */

  /* Spacing (8px grid) */
  --space-1: 4px;  --space-2: 8px;  --space-3: 12px;
  --space-4: 16px; --space-5: 24px; --space-6: 32px;
  --space-7: 48px;

  /* Radius */
  --radius-sm: 4px;
  --radius-md: 8px;
  --radius-lg: 12px;

  /* Typography */
  --font-heading: "Zen Kaku Gothic New", system-ui, sans-serif;
  --font-body: "Noto Sans JP", system-ui, sans-serif;
  --font-mono: "DM Sans", "JetBrains Mono", monospace;
}
```

## 表層のアンチパターン（AI感を消す）

デフォルトに戻ったAI生成UIは一目で見分けがつく。以下は**禁止**：

- **Interフォント禁止**。`--font-body` に Noto Sans JP + Zen Kaku Gothic New を使う
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
