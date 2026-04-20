# Routeful

> みんなで集まって1つの画面を囲みながら使う、AI旅行計画ツール。
> 実在するスポット・正確な電車の時刻・根拠ある価格まで提示する、evidence-based なプランニング体験。

「たびあい」からの発展版。性格診断を脱ぎ、**複数人の希望を合成したプラン生成** と **LLM出力のハルシネーション対策** を軸に再設計した。

## 新規性の3軸

1. **Evidence-based 生成** — Google Places API で実在確認、営業時間・距離を構造化データとして LLM に注入。根拠バッジで出力の確度を可視化
2. **交通の正確性** — Google Routes API (transit) で電車の便名・発車時刻・運賃まで表示。「行けないプラン」を終わらせる
3. **複数人の希望合成** — 2〜5人の希望と予算配分制約を構造化して LLM に渡し、合意可能な妥協点を探らせる

## 思想的背景

本プロジェクトは LCaMO 研究（GA × LLM のハイブリッド武器バランス最適化）で得た知見「**LLM は意味空間を、構造化データは数値空間を担当する**」を旅行ドメインに転写している。

| LCaMO | Routeful |
| --- | --- |
| GA が数値パラメータを探索 | Places API / Routes API が時間・距離・運賃を担う |
| LLM が「武器らしさ」を意味評価 | LLM が「その人たちらしい旅か」を意味評価し文章化 |
| フィードバックで更新 | 手動編集・部分再提案でプランを作り込む |

## 想定される使い方

旅行に行くメンバー（2〜5人程度）が**対面で集まり、1台の端末を囲みながら**使う。各人の希望を順に入力し、AIが生成したプランを全員で見ながら、「ここは変えたい」「この代替案がいい」とその場で調整していく。

リモート同時編集は Phase 3 以降の拡張として位置付ける（詳細は `docs/future-extensions.md`）。

## Tech Stack

- **Frontend**: Next.js 15 (App Router) + TypeScript + Tailwind CSS v4 + shadcn/ui + Zustand + Framer Motion + Mapbox GL JS
- **Backend**: Flask (Python 3.12) on Render (無料プラン)
- **DB / Auth**: Supabase (匿名認証 + PostgreSQL)
- **LLM**: OpenAI GPT-4o
- **External APIs**: Google Places API (New) / Google Routes API / Google Geocoding / 楽天トラベル API / Mapbox Tiles
- **Monorepo**: Turborepo + pnpm workspaces
- **Dev Workflow**: Claude Code + Codex MCP

## プロジェクト構成

```
routeful/
├── CLAUDE.md              # Claude Code の憲法（50行以下）
├── README.md              # このファイル
├── .env.example           # 必要な環境変数一覧
├── tasks/
│   ├── todo.md            # Phase 1→2→3 の TDD 実装計画
│   └── lessons.md         # 失敗と学習のステージング領域
├── docs/
│   ├── architecture.md    # システム全体構成
│   ├── data-model.md      # DB・TypeScript 型定義
│   ├── evidence-pack.md   # LLM プロンプト設計（正典）
│   ├── setup-guide.md     # 詳細セットアップ手順
│   ├── team-roles.md      # チーム役割分担・IF仕様
│   └── future-extensions.md # 将来の拡張方針（リアルタイム同期等）
├── .claude/
│   ├── settings.json      # 権限 + Codex MCP 自動許可
│   ├── rules/             # パス別の条件付きルール
│   ├── commands/          # スラッシュコマンド
│   └── agents/            # カスタムエージェント
├── apps/
│   ├── web/               # Next.js フロントエンド
│   └── api/               # Flask バックエンド
└── packages/
    └── shared-types/      # TS 型共有
```

## クイックスタート

詳細は `docs/setup-guide.md`。最小限の流れ：

```bash
# 1. リポジトリ取得
git clone <repo-url> && cd routeful

# 2. 依存インストール
pnpm install

# 3. 環境変数設定
cp .env.example .env.local
# → 各APIキーを埋める

# 4. Supabase プロジェクト作成 + DDL実行
# docs/setup-guide.md に従う

# 5. MCP サーバー接続（Manato さん用）
claude mcp add codex -- codex mcp-server
claude mcp add context7 -s user -- npx -y @upstash/context7-mcp

# 6. Claude Code 起動
claude

# 7. 開発サーバー起動
pnpm dev
```

## 実装の進め方

`tasks/todo.md` を参照。Phase 1 → 2 → 3 の順で TDD で進める。

- **Phase 1**: コアループ（希望入力 → Evidence-based生成 → タイムライン表示 → 地図 → 共有）
- **Phase 2**: 予算配分スライダー / 出発モード切替 / 手動編集 + 部分再提案 / 宿泊費API
- **Phase 3**: 飲食費精密化 / 入場料半自動 / 当日しおり / リモート同期対応

## チーム開発

3人チームでの役割分担は `docs/team-roles.md`。

- **Manato**: 全体統括 + LLM / Evidence Pack 担当
- **メンバーB**: バックエンド + Supabase + 外部 API 連携
- **メンバーC**: フロントエンド + UX + 地図

インターフェース仕様（Manatoさんが握る部分）は `docs/data-model.md` と `docs/evidence-pack.md` に集約。

## ライセンス

内部開発中 (Private)。ハッカソン出品後に決定。
