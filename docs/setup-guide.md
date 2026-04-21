# Setup Guide

## 前提

- Node.js 20 以上
- pnpm 9 以上（`npm install -g pnpm`）
- Python 3.12 以上
- Git
- Claude Code（Manato さんは既にインストール済み）

## 1. リポジトリ取得と依存インストール

```bash
git clone <repo-url>
cd routeful
pnpm install

# Python 仮想環境（apps/api 用）
cd apps/api
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cd ../..
```

## 2. 各 API キーの取得

### 2.1 OpenAI API キー

1. https://platform.openai.com/ にログイン
2. API keys ページから新規キー発行
3. 課金設定を有効化（$5 程度課金しておけばハッカソン期間は持つ）

### 2.2 Google Maps Platform

1. https://console.cloud.google.com/ で新規プロジェクト作成
2. 以下の API を有効化:
   - Places API (New)
   - Routes API
   - Geocoding API
   - **Maps JavaScript API**（フロントで DirectionsService を使って日本 transit を取るため必須、Phase 1.3 以降）
3. 認証情報 > API キーを **2 つ**作成:
   - **サーバーキー** (`GOOGLE_MAPS_API_KEY`): API 制限＝Places / Routes / Geocoding、本番運用では Application restriction = IP addresses（Render の outbound IP）
   - **ブラウザキー** (`NEXT_PUBLIC_GOOGLE_MAPS_BROWSER_KEY`): API 制限＝Maps JavaScript API、本番運用では Application restriction = HTTP referrers（`https://<your-vercel>.vercel.app/*` と `http://localhost:3000/*`）
   - ⚠️ **1 つのキーで referrer と IP の両方を絞ることはできない**（Google の仕様）。本番では必ず 2 つに分離
4. 各キーに割り当て（Quotas）で日次上限を設定（Places 1000/day, Routes 500/day, Geocoding 500/day, Maps JS 10000 loads/day 程度が目安）
5. **予算とアラート** で月 $10 の通知を設定

月の無料枠（ハッカソン時点）: Places/Routes/Geocoding ともに 5,000〜10,000 リクエスト/月、Maps JS は 月 28,500 loads。

⚠️ **JP transit の制約**: Google の Directions / Routes サーバー API は日本国内の公共交通データを返さない。電車便名・発車時刻・運賃はフロントの Maps JS SDK DirectionsService 経由で取得する（`tasks/lessons.md` 参照）。

### 2.3 Mapbox トークン

1. https://account.mapbox.com/ にサインアップ
2. Default public token をコピー（`pk.*`）
3. 必要なら新規トークンを発行しスコープを限定

無料枠: 月 50,000 マップロード。

### 2.4 Supabase

1. https://supabase.com/ でプロジェクト新規作成
2. Settings > API から `URL` と `anon public key` をコピー
3. Settings > API から `service_role` キーをコピー（**絶対に公開しない**）
4. SQL Editor で `docs/data-model.md` の DDL を実行
5. Authentication > Providers で「匿名サインイン」を有効化

### 2.5 楽天トラベル API（Phase 2 用、早めに申請）

1. https://webservice.rakuten.co.jp/ でアプリ登録
2. `applicationId` と `affiliateId` をコピー
3. 承認に時間がかかる場合があるので Phase 1 着手時に申請しておく

## 3. 環境変数設定

```bash
cp .env.example .env.local
# .env.local を開いて各キーを埋める
```

## 4. Supabase DDL 実行

`docs/data-model.md` の「PostgreSQL DDL」セクションをまるごと Supabase SQL Editor に貼り付けて Run。
テーブルとポリシーが作成されたことを確認。

## 5. Claude Code の初期設定

### 5.1 MCP サーバー接続

```bash
# Codex MCP（レビュー用。導入は推奨、レビュー実行は依頼ベース）
claude mcp add codex -- codex mcp-server

# Context7（古い API を防ぐ、必須）
claude mcp add context7 -s user -- npx -y @upstash/context7-mcp

# Playwright（E2E テスト、Phase 1.10 で使用）
claude mcp add playwright -s project -- npx -y @playwright/mcp@latest
```

### 5.2 Claude Code 起動確認

```bash
cd routeful
claude
```

最初のプロンプト例:

```
このプロジェクトの CLAUDE.md と tasks/todo.md を読んで、現在の状況を把握してください。その後、Phase 0.1 のモノレポ初期化から始めましょう。計画を立てて実装を進めてください（Codex レビューが必要そうなら都度相談してください）。
```

## 6. 開発サーバー起動

```bash
# ルートで実行
pnpm dev

# フロント: http://localhost:3000
# バック:   http://localhost:5000
```

## 7. デプロイ

### 7.1 Vercel（フロント）

1. https://vercel.com/ で新規プロジェクト作成、GitHub リポジトリを接続
2. Root Directory に `apps/web` を指定
3. Environment Variables に `.env.local` の `NEXT_PUBLIC_*` 系と `NEXT_PUBLIC_API_BASE_URL`（Render の URL）を設定
4. Deploy

### 7.2 Render（バック）

1. https://render.com/ で新規 Web Service 作成、GitHub リポジトリを接続
2. Root Directory: `apps/api`
3. Runtime: Python 3
4. Build Command: `pip install -r requirements.txt`
5. Start Command: `gunicorn 'src.app:create_app()' --bind 0.0.0.0:$PORT`
6. Environment Variables に `.env.local` の非 `NEXT_PUBLIC_*` 系を設定
7. Deploy

## トラブルシュート

### Supabase の匿名認証が効かない

- Authentication > Providers で Anonymous サインインが有効になっているか確認
- RLS ポリシーが `auth.uid()` を使っているか確認

### Google Maps API が 403 を返す

- API キーの制限で HTTP referrer や IP を絞りすぎていないか確認
- 該当の API（Places, Routes, Geocoding）が有効化されているか確認
- 課金アカウントが紐付いているか確認（無料枠も課金アカウントが必要）

### OpenAI API が 429（rate limit）

- 同時リクエスト数を絞る
- プラン生成はユーザー操作なので 1 セッションあたり同時 1 に制限
- テスト実行時はモックを使う（`.claude/rules/testing.md` 参照）
