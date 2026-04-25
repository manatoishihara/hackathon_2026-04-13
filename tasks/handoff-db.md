# DB / バックエンド 整理タスク — メンバー B 向け

**前提（2026-04-25 更新、夜の β 実装後）**: Phase 1.3a〜1.3d まで実装完了 + Phase 1.3e (Structured Plan Assembly, LCaMO 応用) も develop マージ済み（hallucination 構造的 0% 達成、success rate は別軸の残課題）。RLS E2E は rate limit クールダウン後に 8/8 PASS、`test_routes_plans.py` integration の 2/3 のみ RLS 42501 violation で残るが Manato 側で本番 policy drift 解消の SQL Editor 実行で吸収予定。**DB 担当のタスクは完全に独立して進められる**ので、本資料の DB-1 / DB-4〜6 / DB-7 / DB-8 に集中してほしい。

## 着手前の軽い注意点（2026-04-25 夜、Manato 申し送り）

1. **`SITE_BASE_URL` env 追加について**: 本資料 DB-4 で「`apps/api/src/config.py` に追加」と書いているが、**現状 `apps/api/src/config.py` は未作成**（既存コードは `os.environ.get(...)` を各ファイルで直接読む構成）。DB 担当の選択肢:
   - (a) `share_routes.py` 内で直接 `os.environ.get("SITE_BASE_URL")` を読む（既存パターン踏襲、最小変更）
   - (b) `apps/api/src/config.py` を新規作成して env 集約をスタートさせる（`.claude/rules/api-rules.md` の原則に沿う、ただし他ファイル retrofit は別タスク）
   どちらでも OK。MVP 提出優先なら (a) で進めて、Phase 2 で (b) に集約する判断もあり
2. **RLS 42501 問題は DB-5 の設計に影響しない**: `test_routes_plans.py` の anon INSERT 失敗は本番 policy drift 由来で Manato 側で解消予定。**DB-5 は Flask + service_role 経由なので RLS をバイパス**するため、この問題を踏まずに済む（handoff-db.md 既存の方針通り）
3. **Phase 1.3e (β) の影響範囲**: `apps/api/src/llm/prompt.py` のみで、DB 担当が触る `routes/` / `supabase_client.py` / `migrations/` には触れていない。安心して着手して OK

**1.3d と噛み合うタスク（DB-2 RLS E2E、DB-3 pg_cron クリーンアップ）は Manato が Phase 1.3d Branch D で実装済み**（@supabase/migrations/20260424_03_cleanup_cron.sql、@apps/api/tests/test_rls.py）。本資料からは「done」として触らなくて OK。

## 担当範囲

- **触ってよい**: `apps/api/src/routes/` / `apps/api/src/supabase_client.py` / `apps/api/src/config.py`（env 追加用）/ Supabase ダッシュボード / `supabase/migrations/` / `apps/api/tests/`
- **触らないでほしい**: `apps/api/src/evidence/` / `apps/api/src/llm/` / `packages/shared-types/` / `docs/data-model.md` / `apps/api/src/schemas/__init__.py`

型や Evidence Pack 仕様を変えたくなったら Manato に相談。
**DB-4 / DB-5 のレスポンス型（ShareResponse / SharedPlanResponse 系）は 2026-04-25 に Manato が事前 3 点同期済み**なので、Flask 実装時は contract に沿うだけで OK（shared-types / schemas に追加は不要）。

## 分業の前提（2026-04-25 整理）

| 担当 | タスク |
|---|---|
| Manato | ✅ Phase 1.3d 実装本体 / ✅ DB-2 RLS E2E テスト / ✅ DB-3 pg_cron クリーンアップ。残: Phase 1.3d ハルシネーション率チューニング + integration テスト完走 |
| **メンバー B（本資料）** | **DB-1 migrations / DB-4〜6 共有 API / DB-7 楽天 App ID / DB-8 Supabase ログ** |
| メンバー C | フロント 1.4〜1.9 の見た目仕上げ（`tasks/handoff-frontend.md`） |

## 優先度付きタスク一覧

### 🔴 優先度 高: DB 運用の土台

#### DB-1: Migrations ディレクトリ化 ✅ **2026-04-25 に Manato 先行実施**

既存 DDL は以下 5 ファイルに **冪等化して配置済み**（本番再適用しても何も壊れない）:

| 連番 | ファイル | 内容 |
|---|---|---|
| 00 | `20260401_00_init.sql` | sessions / plans / participants / plan_items + RLS policies + shared_plans view（Phase 0.2） |
| 01 | `20260419_01_evidence_pack_sessions.sql` | evidence_pack_sessions テーブル + RLS（Phase 1.3a） |
| 02 | `20260424_02_plans_status.sql` | plans.status カラム + CHECK + idx_plans_status（Phase 1.3c+） |
| 03 | `20260424_03_cleanup_cron.sql` | pg_cron による定期クリーンアップ（Phase 1.3d Branch D） |
| 04 | `20260424_04_plan_generation_rpcs.sql` | acquire_plan_generation_lock / mark_plan_failed / finalize_plan RPC（Phase 1.3d Branch B） |

冪等性の担保:
- `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS` / `ADD COLUMN IF NOT EXISTS`
- `pg_constraint` を参照して CHECK 制約の重複追加を回避
- `DROP POLICY IF EXISTS` → `CREATE POLICY` で最新内容に上書き
- `CREATE OR REPLACE VIEW` / `CREATE OR REPLACE FUNCTION`
- `cron.unschedule` → `cron.schedule` で冪等登録

**DB 担当に残っている仕事**:
- [ ] 今後の DDL 変更は **新しい連番ファイル**（例: `20260501_05_xxx.sql`）を追加する運用を徹底する。既存 5 ファイルは履歴なので編集しない
- [ ] （optional）Supabase CLI (`supabase db push`) の導入を検討。現状は SQL Editor 手動実行で運用
- [ ] 新規 Supabase プロジェクト立ち上げ時（Phase 2 環境 or staging）は 00 → 04 の順に SQL Editor で実行すれば本番同等になることを確認

**`docs/data-model.md` の位置づけ（2026-04-25 確定）**:
- 概念モデル + TS/Pydantic 型の正典（3 点同期の中心）
- 「PostgreSQL DDL」節は migrations の最新状態スナップショット（運用上の DDL 真実は `supabase/migrations/`）

### 🟡 優先度 中: Phase 1.9 プラン共有の前倒し

**スコープ**: フロント骨組みは完成済み（`apps/web/src/app/plan/[id]/share/page.tsx`）で、API 待ちの状態。以下 3 つを揃えれば共有機能が完成する。

#### DB-4: `share_token` 生成 API

- `plans` テーブルに `share_token TEXT UNIQUE` は既にある
- バックエンドで `POST /api/plans/:id/share` を実装:
  - 認証必須（`require_session`）、`plan_id` の owner 検証（`plans.session_id = g.owner_session_id`）
  - `secrets.token_urlsafe(16)` で 22 文字程度の共有トークン生成
  - `UPDATE plans SET share_token = ... WHERE id = :id AND session_id = :owner`（service_role クライアント経由で）
  - 既に token があれば既存を返す（再生成は別エンドポイント `DELETE` 想定、今回スコープ外）
  - **`plans.status = 'succeeded'` のものだけ共有を許可**（draft / generating / failed は 409 or 404 を返す想定）
- レスポンス型は **既に 3 点同期済み**: `ShareResponse = { share_token: string, share_url: string }`
  - `packages/shared-types/src/index.ts` / `apps/api/src/schemas/__init__.py` / `docs/data-model.md` で定義済み
  - `share_url` はサーバーで組み立てる（例: `f"{SITE_BASE_URL}/plan/shared/{token}"`、`SITE_BASE_URL` を `apps/api/src/config.py` に追加して env 経由で）

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
- レスポンス型は **既に 3 点同期済み**:
  - `SharedPlanSummary = Omit<Plan, "session_id" | "share_token">`
  - `SharedParticipant = Omit<Participant, "plan_id">`
  - `SharedPlanItem = Omit<PlanItem, "plan_id">`
  - `SharedPlanResponse = { plan, participants, plan_items }`
- **識別子漏洩防止のため、session_id / share_token / plan_id を公開ペイロードに含めない**（Pydantic で別クラスとして定義済み）。Flask 実装時は `model_dump(mode="json")` で JSON 化する
- 返却時の整形: `plan_items` は `order_index` で昇順ソート、`participants` も `order_index` で昇順（フロント側の実装簡素化のため）

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
- [ ] `pytest -m integration` も通る（自分のタスクに integration テストがある場合）。
      **注意: Supabase anon sign-in は IP あたり 30 signups/hour の rate limit があるので、
      integration テストを連続実行する場合は 1 時間のクールダウンを挟むか、テスト設計で
      sign-in 回数を最小化する（既存 test_rls.py は per-test 2 sign-in で 8 件あるため
      最悪 16 sign-in を消費する）**
- [ ] `docs/data-model.md` / `docs/architecture.md` が実装と整合している
- [ ] 新規 API を生やした場合は `docs/team-roles.md` の API エンドポイント表を更新
- [ ] 型変更が必要になった場合は **Manato に相談してから** 3 点同期（docs / shared-types / Pydantic）
      （DB-4 / DB-5 のレスポンス型は 2026-04-25 時点で Manato が事前に 3 点同期済み。
      実装時は contract に沿って Flask ルート + Pydantic validate をつけるだけでよい）

## 困ったら

- DDL の正典: `docs/data-model.md`（将来的には `supabase/migrations/`）
- RLS のドキュメント: Supabase 公式 + 既存の `plans` ポリシーを参考に
- 認証フロー: `apps/api/src/auth.py`（JWT 検証 + `g.owner_session_id` セット）
- キャッシュパターン: `apps/api/src/evidence/cache.py`（opportunistic cleanup + retry の実装例）

## 現状の Supabase テーブル一覧（2026-04-25 時点）

- `sessions`（匿名セッション）
- `plans`（旅行プラン、`status` カラム追加済み）
- `participants`（2〜5 人）
- `plan_items`（時系列アイテム）
- `evidence_pack_sessions`（Evidence Pack 短期キャッシュ、TTL 15 分）

RPC（Phase 1.3d Branch B、`20260424_04_plan_generation_rpcs.sql`）:
- `acquire_plan_generation_lock(plan_id, session_id) returns text` — draft → generating 遷移で排他制御
- `mark_plan_failed(plan_id) returns void` — 失敗時の後始末
- `finalize_plan(plan_id, items jsonb) returns void` — generating → succeeded + plan_items INSERT を 1 トランザクションで

cron ジョブ（Phase 1.3d Branch D、`20260424_03_cleanup_cron.sql`）:
- `cleanup-evidence-pack-sessions` — 1 時間毎、期限切れ pack 削除
- `cleanup-stuck-plans` — 1 時間毎、`generating` のまま 1 時間超の plan を削除
- `cleanup-abandoned-plans` — 1 日毎、`draft`/`failed` 状態で 24 時間超の plan を削除（`succeeded` は絶対に削除しない）

詳細は `docs/data-model.md` の DDL セクション + `supabase/migrations/` 参照。
