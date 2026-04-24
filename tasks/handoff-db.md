# DB / バックエンド 整理タスク — メンバー B 向け

**前提**: Phase 1.3c（サーバー側 Transit Validator + `/api/plans/generate` 骨組み）までで、Supabase 連携と evidence_pack_sessions キャッシュは動作している。
この資料は、**DB 運用の整理** と **Phase 1.9 共有機能の前倒し** を中心に、1.3d（LLM 接続）と並行して進められるタスクを列挙する。

## 担当範囲

- **触ってよい**: `apps/api/src/routes/` / `apps/api/src/supabase_client.py` / Supabase ダッシュボード / `supabase/migrations/`（新設予定） / `apps/api/tests/`
- **触らないでほしい**: `apps/api/src/evidence/` / `apps/api/src/llm/`（1.3d で新設予定） / `packages/shared-types/` / `docs/data-model.md`

型や Evidence Pack 仕様を変えたくなったら Manato に相談。

## 優先度付きタスク一覧

### 🔴 優先度 高: DB の整理（スキーマ運用の土台）

#### DB-1: Migrations ディレクトリ化

**現状の課題**: DDL が `docs/data-model.md` にベタ書きで、Supabase SQL Editor に手で貼り付け運用。誰がどの順で実行したか不明、rollback も手動。

**やること**:
- `supabase/migrations/` ディレクトリを作成
- 既存の DDL を `supabase/migrations/20260401_00_init.sql`, `20260419_01_evidence_pack_sessions.sql` のようにファイル分割（日付 + 連番）
- 今後の ALTER は新しいファイルで追加していく運用に
- `docs/data-model.md` には「DDL の正典は `supabase/migrations/` 配下、ドキュメントは概念モデルのみ」と明記
- （オプション）Supabase CLI (`supabase db push`) 導入を検討

**完了条件**: 既存の本番スキーマを新規 Supabase プロジェクトに「migrations フォルダから順に実行」で再現できる

#### DB-2: RLS の E2E テスト

**現状の課題**: DDL に RLS ポリシーは書いてあるが、「他セッションから自分のプランにアクセスできない」動作確認テストがない。

**やること**:
- `apps/api/tests/test_rls.py` を新規作成
- 2 人の匿名ユーザ（user A / user B）を作成
- user A が plan / participants / plan_items を作成
- user B のトークンで A のプランにアクセス → 0 件 or 403 を期待
- `evidence_pack_sessions` についても同様（B が A の pack_id を知っても load_pack で None が返る、という 1.3c の挙動を live で確認）
- `pytest -m integration` で動くようにマーキング

**完了条件**: 他セッションからのアクセス遮断が自動テストで担保される

#### DB-3: evidence_pack_sessions の定期クリーンアップ + 失敗 plans 清掃

**現状の課題**:
1. `store_pack` で opportunistic cleanup しているが、1 日に 1 回も書き込みがないとゴミが溜まり続ける可能性
2. 1.5 で plan_id 発行 + plans INSERT したが、その後のフローで失敗（`/api/evidence/places` 失敗、ユーザがリロードで放棄、LLM 生成失敗等）すると `status = 'draft'` or `'failed'` で `plan_items = 0` のゴミ plan が残る

**やること**:
- Supabase の pg_cron でも Edge Function の scheduled でも可
- 1 時間毎: `DELETE FROM evidence_pack_sessions WHERE expires_at < now()`
- 1 時間毎: `DELETE FROM plans WHERE status = 'generating' AND updated_at < now() - INTERVAL '1 hour'`（生成中のまま中断・放置された plan、LLM は 60 秒以内完了前提なので 1 時間は十分長いマージン）
- 1 日毎: `DELETE FROM plans WHERE status IN ('draft', 'failed') AND created_at < now() - INTERVAL '24 hours'`（plan_items / participants は CASCADE DELETE される前提）
- **`succeeded` は削除しない**（ユーザの成果物、保全）
- 実装場所は `supabase/functions/cleanup_expired_sessions/` or `supabase/migrations/` の cron 設定

**完了条件**: pg_cron 設定が migrations に入り、手動なしでゴミが消える

### 🟡 優先度 中: Phase 1.9 プラン共有の前倒し

#### DB-4: `share_token` 生成と保存

- `plans` テーブルに `share_token TEXT UNIQUE` は既にある
- バックエンドで `POST /api/plans/:id/share` を実装:
  - 認証必須、`plan_id` の owner 検証
  - `secrets.token_urlsafe(16)` で 22 文字程度の共有トークン生成
  - `UPDATE plans SET share_token = ... WHERE id = :id AND session_id = :owner`
  - 既に token があれば既存を返す（再生成は別エンドポイント `DELETE` 想定、今回スコープ外）
- レスポンス: `{ share_token: string, share_url: string }`
- **`packages/shared-types` に `ShareResponse` 型を追加する必要あり** → **Manato に相談**（型変更は Manato 管轄ルール）

#### DB-5: 共有閲覧 API — **認可方針: Flask + service role 経由に確定（v2）**

Codex re-review Must-fix #7 対応で、先に認可戦略を固定する。

**方針**: **Flask サーバーを必ず経由する。Flask は service role で RLS を跨いで読むが、Flask のクエリ条件で `share_token IS NOT NULL` を強制することで保護する**（service role を使う理由は、共有用の特別 RLS ポリシーを書かなくていい簡素さを優先。代わりにアクセス制御を Flask のコードロジックに閉じ込める）。

実装:
- `GET /api/plans/shared/:token` を実装（**JWT 認証不要**。URL の token が唯一の認可材料）
- Flask は `apps/api/src/supabase_client.py` の service role クライアントを使う（RLS を跨げるので、token だけでの読み取りが可能になる）
- クエリで `share_token = :token AND share_token IS NOT NULL` を必ず条件に入れる（ハードコード、リクエストパラメータで変えられないように）
- SELECT は plan / plan_items / participants の 3 テーブル（JOIN or 3 クエリ並列）
- `share_token` が NULL のプラン、または token が見つからない場合は 404（漏洩防止のため「存在するが share_token=NULL」と「存在しない」を区別しない）

**なぜ RLS ではなく Flask で絞るか**:
- Supabase 匿名クライアントを直接叩くと `share_token` をリクエスト側で任意に送れるので、Row Policy を書いても `USING (...)` の組み立てが複雑化する
- Flask 経由にすればロジックがサーバーコードに閉じる、レビュー容易
- Supabase client の anon role で読めないよう、通常の RLS `plans.session_id = auth.uid()` は維持

実装ファイル:
- `apps/api/src/routes/share_routes.py`（新規）
- `POST /api/plans/:id/share`（DB-4）と同じ blueprint でよい
- Pydantic レスポンス `SharedPlanResponse = { plan, participants, plan_items }` を `shared-types` と 3 点同期

#### DB-6: 共有用 RLS ポリシー監査 — **RLS 追加不要の方針で確定（v2）**

DB-5 を Flask + service role に固定したため、共有専用 RLS ポリシーは不要。既存の `plans.session_id = auth.uid()` を維持するだけ。

代わりに以下を監査:
- Supabase anon key で直接 `SELECT * FROM plans WHERE share_token = ...` しても結果が返らないこと（RLS が働いている確認）
- Flask service role 経由でのみ `share_token` ベース取得が通ること
- 監査テスト: `apps/api/tests/test_rls.py` に追加（DB-2 と合流してよい）

### 🟢 優先度 低: 将来タスクの先行準備

#### DB-7: 楽天トラベル API App ID 取得（Phase 2 用、申請に時間がかかる）

- 楽天ウェブサービスに新規登録、Affiliate ID も取得
- 取得後、`.env` と Render の環境変数に登録（値は Manato に共有）
- 疎通テスト `apps/api/src/external/rakuten.py` は Phase 2 で書くが、キーだけは先に用意

#### DB-8: Supabase の Row-Level Logging

- LLM 生成後に `plans` と `plan_items` に書き込む Phase 1.3d を迎える前に、DB の insert/update を Supabase のログで追える状態にしておく
- Supabase ダッシュボードの Logs から postgres ログのサンプリングを確認、必要なら `pg_stat_statements` を有効化

## 完了確認チェックリスト

タスク完了時は PR 説明に以下を書く:

- [ ] `pnpm --filter api test`（unit）が通る
- [ ] `pytest -m integration` も通る（自分のタスクに integration テストがある場合）
- [ ] `docs/data-model.md` / `docs/architecture.md` が実装と整合している
- [ ] 新規 API を生やした場合は `docs/team-roles.md` の API エンドポイント表を更新
- [ ] 型変更が必要になった場合は **Manato に相談してから** 3 点同期（docs / shared-types / Pydantic）

## 困ったら

- DDL の正典: `docs/data-model.md`（将来的には `supabase/migrations/`）
- RLS のドキュメント: Supabase 公式 + 既存の `plans` ポリシーを参考に
- 認証フロー: `apps/api/src/auth.py`（JWT 検証 + `g.owner_session_id` セット）
- キャッシュパターン: `apps/api/src/evidence/cache.py`（opportunistic cleanup + retry の実装例）

## 現状の Supabase テーブル一覧（2026-04-21 時点）

- `sessions`（匿名セッション）
- `plans`（旅行プラン）
- `participants`（2〜5 人）
- `plan_items`（時系列アイテム）
- `evidence_pack_sessions`（Evidence Pack 短期キャッシュ、TTL 15 分）

詳細は `docs/data-model.md` の DDL セクション参照。
