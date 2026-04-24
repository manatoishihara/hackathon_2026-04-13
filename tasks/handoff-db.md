# DB / バックエンド 整理タスク — メンバー B 向け

**前提**: Phase 1.3c（サーバー側 Transit Validator + `/api/plans/generate` 骨組み）までで、Supabase 連携と evidence_pack_sessions キャッシュは動作している。
この資料は、**1.3d（LLM 接続）と完全に独立して進められる** DB / API 整理タスクと、**Phase 1.9 共有機能の前倒し**を列挙する。

**1.3d と噛み合うタスク（DB-2 RLS E2E、DB-3 pg_cron クリーンアップ）は Manato が 1.3d 実装と一緒に対応する**ので、本資料からは除外した。メンバー B は下記タスクだけに集中してよい。

## 担当範囲

- **触ってよい**: `apps/api/src/routes/` / `apps/api/src/supabase_client.py` / Supabase ダッシュボード / `supabase/migrations/`（新設予定） / `apps/api/tests/`
- **触らないでほしい**: `apps/api/src/evidence/` / `apps/api/src/llm/`（1.3d で新設予定） / `packages/shared-types/` / `docs/data-model.md`

型や Evidence Pack 仕様を変えたくなったら Manato に相談。

## 分業の前提（2026-04-24 整理）

| 担当 | タスク |
|---|---|
| Manato（1.3d と合流） | Phase 1.3d 本体 / DB-2 RLS E2E テスト / DB-3 pg_cron クリーンアップ |
| **メンバー B（本資料）** | **DB-1 migrations / DB-4〜6 共有 API / DB-7 楽天 App ID / DB-8 Supabase ログ** |
| メンバー C | フロント 1.4〜1.9 の見た目仕上げ（`tasks/handoff-frontend.md`） |

## 優先度付きタスク一覧

### 🔴 優先度 高: DB 運用の土台

#### DB-1: Migrations ディレクトリ化

**現状の課題**: DDL が `docs/data-model.md` にベタ書きで、Supabase SQL Editor に手で貼り付け運用。誰がどの順で実行したか不明、rollback も手動。

**やること**:
- `supabase/migrations/` ディレクトリを作成
- 既存の DDL を `supabase/migrations/20260401_00_init.sql`, `20260419_01_evidence_pack_sessions.sql`, `20260424_02_plans_status.sql` のようにファイル分割（日付 + 連番）
- 既存適用済み DDL（2026-04-24 時点の accumulated changes）:
  - sessions / plans / participants / plan_items テーブル（初期）
  - evidence_pack_sessions テーブル（1.3a で追加）
  - plans.status カラム（1.3c+ で追加、`NEXT_PUBLIC_API_BASE_URL` 後に適用）
- 今後の ALTER は新しいファイルで追加していく運用に
- `docs/data-model.md` には「DDL の正典は `supabase/migrations/` 配下、ドキュメントは概念モデルのみ」と明記
- （オプション）Supabase CLI (`supabase db push`) 導入を検討

**完了条件**: 既存の本番スキーマを新規 Supabase プロジェクトに「migrations フォルダから順に実行」で再現できる

### 🟡 優先度 中: Phase 1.9 プラン共有の前倒し

**スコープ**: フロント骨組みは完成済み（`apps/web/src/app/plan/[id]/share/page.tsx`）で、API 待ちの状態。以下 3 つを揃えれば共有機能が完成する。

#### DB-4: `share_token` 生成 API

- `plans` テーブルに `share_token TEXT UNIQUE` は既にある
- バックエンドで `POST /api/plans/:id/share` を実装:
  - 認証必須（`require_session`）、`plan_id` の owner 検証（`plans.session_id = g.owner_session_id`）
  - `secrets.token_urlsafe(16)` で 22 文字程度の共有トークン生成
  - `UPDATE plans SET share_token = ... WHERE id = :id AND session_id = :owner`
  - 既に token があれば既存を返す（再生成は別エンドポイント `DELETE` 想定、今回スコープ外）
- レスポンス: `{ share_token: string, share_url: string }`
- **`packages/shared-types` に `ShareResponse` 型を追加する必要あり** → **Manato に相談**（型変更は Manato 管轄ルール）

#### DB-5: 共有閲覧 API — 認可方針: Flask + service role 経由に確定

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

#### DB-6: 共有用 RLS ポリシー監査 — RLS 追加不要の方針で確定

DB-5 を Flask + service role に固定したため、共有専用 RLS ポリシーは不要。既存の `plans.session_id = auth.uid()` を維持するだけ。

代わりに以下を監査（Manato の DB-2 テストと重複しないよう、共有固有の動作確認に絞る）:
- Supabase anon key で直接 `SELECT * FROM plans WHERE share_token = ...` しても結果が返らないこと（RLS が働いている確認）
- Flask service role 経由でのみ `share_token` ベース取得が通ること
- Flask 経由でも `share_token IS NULL` の Plan は読めないこと（404 を返す）

### 🟢 優先度 低: 将来タスクの先行準備

#### DB-7: 楽天トラベル API App ID 取得（Phase 2 用、申請に時間がかかる）

**今すぐ依頼したい**: 審査・承認で数日〜数週かかる可能性があるので、手が空いているうちに申請だけ投げる。

- 楽天ウェブサービスに新規登録、Affiliate ID も取得
- 取得後、`.env` と Render の環境変数に登録（値は Manato に共有）
- 疎通テスト `apps/api/src/external/rakuten.py` は Phase 2 で書くが、キーだけは先に用意

#### DB-8: Supabase の Row-Level Logging

- Manato が Phase 1.3d で `plans` / `plan_items` に書き込みを本格化させる前に、DB の insert/update を Supabase のログで追える状態にしておく
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

## 現状の Supabase テーブル一覧（2026-04-24 時点）

- `sessions`（匿名セッション）
- `plans`（旅行プラン、`status` カラム追加済み）
- `participants`（2〜5 人）
- `plan_items`（時系列アイテム）
- `evidence_pack_sessions`（Evidence Pack 短期キャッシュ、TTL 15 分）

詳細は `docs/data-model.md` の DDL セクション参照。
