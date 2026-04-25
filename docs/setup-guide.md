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

### 4.1 Phase 1.3d 追加マイグレーション（必須）

以下の順で `supabase/migrations/` 配下の SQL を **Supabase ダッシュボードの SQL Editor で手動適用**する:

1. **Extensions で `pg_cron` を有効化**（Database > Extensions タブ）
   → DB-3 の cron ジョブが動作するための前提
2. `supabase/migrations/20260424_04_plan_generation_rpcs.sql`
   → `acquire_plan_generation_lock` / `mark_plan_failed` / `finalize_plan` の 3 RPC + enum を作成
3. （Branch D 完成後）`supabase/migrations/20260424_03_cleanup_cron.sql`
   → 期限切れ / stuck / abandoned のクリーンアップ cron を登録

各ファイルは冪等（DO ブロック / CREATE OR REPLACE）なので複数回実行しても安全。

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
3. Environment Variables に以下を設定:
   - `NEXT_PUBLIC_API_BASE_URL` — Render の URL（例: `https://routeful-api.onrender.com`）
   - `NEXT_PUBLIC_SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_ANON_KEY`
   - `NEXT_PUBLIC_GOOGLE_MAPS_BROWSER_KEY` — HTTP referrer 制限を `https://<your-vercel>.vercel.app/*` と `http://localhost:3000/*` に
   - `NEXT_PUBLIC_MAPBOX_TOKEN`
4. Deploy

### 7.2 Render（バック）

**推奨: `render.yaml` Blueprint を使う**（リポジトリ root に配置済み）。

1. https://render.com/ で「New > Blueprint」→ GitHub リポジトリ接続
2. `render.yaml` が自動認識され、`routeful-api` サービスが作成される
3. Dashboard で env 値を入力（`render.yaml` の `sync: false` 項目）:
   - `OPENAI_API_KEY` / `GOOGLE_MAPS_API_KEY`（サーバキー、Render の outbound IP で referrer 制限不要に設定）
   - `NEXT_PUBLIC_SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY`
   - `CORS_ALLOWED_ORIGINS` — Vercel 本番ドメインを CSV 指定（例: `https://routeful.vercel.app,https://routeful-git-main-xxx.vercel.app`）
   - （任意）`PROMPT_VERSION` — code default が v2.0.0、legacy v1 を試したい時のみセット
4. **HTTP Request Timeout を 180 秒に引き上げる**（Settings → HTTP Timeout、`render.yaml` では指定不可な Service-level 設定）
   → LLM 生成は最悪 ~150 秒（per-call 35s × 4 attempts + overhead）。Render の Free plan は 100 秒上限のため、Starter plan へ移行が必要な場合あり
5. Deploy

**手動セットアップする場合（Blueprint を使わない）**: Root Directory `apps/api` / Runtime Python 3.12 / Build `pip install -r requirements.txt` / Start `gunicorn 'src.app:create_app()' --bind 0.0.0.0:$PORT --workers 1 --timeout 180`

### 7.3 環境変数（追加）

Phase 1.10 で以下の変数が利用可能:

- `CORS_ALLOWED_ORIGINS`（**本番では必須**）: Flask が CORS の `Access-Control-Allow-Origin` をエコーバックする allowlist。CSV 指定。未設定だとローカル開発用 `http://localhost:3000` のみ許可される
- `PROMPT_VERSION`（optional、code default `v2.0.0`）: LLM プロンプトの切替。Phase 1.3e で実証された LCaMO 構造化版（hallucination 0% / success 100%）が default。`v1.0.0` は legacy

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
