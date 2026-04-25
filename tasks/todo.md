# TODO: Routeful 実装計画

ハッカソン出品までの実装計画。Phase 1 は MVP として必ず完成させる。
各タスクは TDD 形式（テスト先行 → Red → Green → Refactor → 検証）で進める。

---

## 🏁 進捗サマリ（2026-04-25 更新）

**Phase 0**: ✅ 完了
**Phase 1.1〜1.3d (実装)**: ✅ コード完了（バック: データモデル、Evidence Pack Builder、Transit Validator、LLM 生成 + ハルシネーション検出 + plan_items 保存、RLS E2E、pg_cron）
**Phase 1.3d (実環境検証)**: ⚠️ **未達**。2026-04-25 に `verify_hallucination_rate.py` を計 3 回実行。10 runs × 2 回は hallucination 10%（`unknown_place_id` 主因）、その後 prompt token 圧縮（22,385→11,645、-48%）+ opening_hours 強調 + transit trim を施した 5 runs は hallucination 20% に悪化（`unknown_transit_edge` 7 件が新規噴出、**制約押し出し現象**）。詳細は @tasks/lessons.md 2026-04-25 エントリ

**Phase 1.3e (Structured Plan Assembly, LCaMO 応用)**: 🟢 **β は develop マージ済み・area exclude + case-insensitive + per-slot eligibility hint + hard self-healing は本セッションで実装（uncommitted、commit 提案待ち）**。schema v2 + assembly + prompts v2 + generator v2 分岐 + 代替選定第 1〜2 弾 + β（merged）+ area exclude + case-insensitive matching（曖昧一致は fail-fast）+ per-slot eligibility hint + hard self-healing（ineligible → 同カテゴリ eligible 自動差し替え）+ 全 266 件 unit test PASS。`verify` 反復履歴:
  - run 1〜3（β 前）: hallucination=0% / unknown_transit_edge=3→0 / departure_mismatch=18 等の押し出し
  - run 4: candidate 10 点で prompt 14.6k → hallucination 66.7%
  - run 5（candidate 10→3）: prompt 12,547 tok / hallucination 33.3%
  - **run 6（β 実装後、develop マージ済み）**: prompt < 12k / hallucination 0/3 / success 0/3
  - **run 7（area exclude 実装後）**: success **1/3 (+1 改善)** / hallucination 1/3（gpt-4o-mini case mismatch、3-run noise）
  - **run 8（+ case-insensitive matching、`--runs 5`）**: **success 2/5 (40%) / hallucination 0/5 = 0% PASS**、residual `outside_opening_hours=2/run`
  - **run 9（+ rule 5 強化試行）**: success 0/5 / hallucination 1/5 → **revert**
  - **run 10（run 8 同条件で再検証）**: success 2/5 / hallucination 1/5 → 5-run サンプリングノイズと判明
  - **run 11（per-slot eligibility hint 実装後、外乱含む）**: hallucination 0/5、outside_opening_hours=1（外乱で run 5 件中 2 件汚染）
  - **run 12（再検証、外乱なし）**: hallucination 0/5、outside_opening_hours=9 → soft hint だけでは LLM が rule を無視と判明
  - **run 13（hard self-healing 実装後）**: hallucination 0/5、**outside_opening_hours=6 (run 12 比 -33%)**、budget_exceeded=2。assembler が ineligible pick を 1 attempt あたり 3 件自動 swap

**主目的「hallucination 構造的 0%」+ 副次「success rate 100%」を本セッションで完遂**（11 段の累積改修 + Codex レビュー反映、試行錯誤の物語は @tasks/plans/2026-04-25-structured-plan-assembly.md 末尾「本セッションの試行錯誤の物語」参照）。**(ix) gpt-4.1 採用 + (x) Codex 深掘りレビュー反映で success 100% 到達**:
  - **hallucination 0% (50+ sample 累計 0% 維持)**、**success rate 100% (10/10、2 連続 5-run)**、平均 **4.4 秒/run**（gpt-5 から 38x 高速）
  - **Codex 指摘 3 件を修正**（同種「複数制約次元の一部のみ check」構造 bug の網羅）:
    - **Critical**: post-shift で start_dt が opening close 超え → `is_place_open_at_dt` helper 追加 + `IneligiblePlaceForSlotError` raise
    - **Major**: `_find_eligible_alternate_for_slot` が transit 到達可能性を見ない → `prev_place_id` 引数で reachable_ids 必須フィルタ
    - **Major**: `_pick_departure_time` max() fallback が過去出発時刻を返す → 過去のみなら `NoFeasibleTransitError` raise、verify の candidates を 5 点 (`["09:00","12:00","15:00","18:00","21:00"]`) に拡張
  - **以前の改修**: `_find_alternate_place` の eligibility check 漏れも本セッション内で発見・修正済み（同一パターン）
  - 詳細 issue ログを `verify_hallucination_rate.py` に永続化（再現性ある bug 検知の土台）
  - **次セッション候補（Codex 残課題）**: (latent) 営業時間 parser の日跨ぎ対応 / (Minor) item_type vs category 整合性 validator
  - 設計書 + 全 run 詳細 (run 4〜27) + Codex review 全文 + 工夫まとめは @tasks/plans/2026-04-25-structured-plan-assembly.md
**Phase 1.4〜1.9 骨組み**: ✅ 完了（フロントの配線層、デザイナーへ引き渡し済み）

**Phase 1.10 Render 先行デプロイ**: 🟢 2026-04-25 完了。`https://routeful-api.onrender.com/healthz` が `{"service":"routeful-api","status":"ok"}` を返す状態。Singapore region / NRT edge 経由 / cold start ~0.4s / CORS ヘッダ動作確認済（`access-control-allow-origin: http://localhost:3000` が env から正しく echo back）。次は RLS 42501 解消 → Vercel deploy → CORS_ALLOWED_ORIGINS を Vercel URL に書き換え。

**Phase 1.10 Vercel 設定とビルド修正**: 🟡 2026-04-25 セッションで Vercel ビルド成功まで到達（`pnpm --filter web build` ローカル PASS / Web test 61/61 PASS）、本番 deploy は user push 後に確認。経緯:
  - Vercel UI Root Directory picker が monorepo 中間 `apps/` を表示しない罠 → Plan B（root deploy → Settings 修正 → Redeploy）で迂回
  - 設定: Root Directory `apps/web` / Install Command `pnpm install` / Production Branch `develop` を Settings の `Build and Deployment` / `Environments` 配下で個別設定（旧 UI と場所違い）
  - Production Branch 切替後の Redeploy は元 deploy の branch を継ぐので、新規 deploy トリガーには `develop` への empty commit push が必要だった
  - **build 失敗 1**: pnpm strict isolation × `@hookform/resolvers@5.2.2` の peer 宣言漏れで `Module not found: zod/v4/core` → `.npmrc` の `public-hoist-pattern[]=*zod*` で解消
  - **build 失敗 2**: `transit.test.ts` の ESLint `no-explicit-any` 4 件（mock 用の意図的 any）→ file-level `eslint-disable` 1 行で解消
  - 残: `develop` push → Vercel auto deploy → URL 確定 → Render の `CORS_ALLOWED_ORIGINS` 更新 → Google Maps browser key referrer に Vercel URL 追加 → 本番 E2E 確認

**Phase 1.10 デプロイ準備（コード側）**: ✅ 2026-04-25 セッションで完了（`feat/deploy-prep` ブランチ、API unit 283 件 PASS / Web 61 件 PASS / gunicorn smoke OK）。デプロイ前ブロッカーをまとめて解消:
  - **CORS 追加**: `flask-cors` 導入 + `apps/api/src/app.py` に `_resolve_cors_origins()` 実装。env `CORS_ALLOWED_ORIGINS`(CSV) 読み、未設定時 `http://localhost:3000` のみ。`Authorization` / `Content-Type` 許可、`GET/POST/OPTIONS` 許可。CORS テスト 6 件
  - **gunicorn 追加**: `requirements.txt` に追加、`--workers 1 --timeout 180` で起動 smoke OK
  - **render.yaml 新規作成**: Singapore region / healthCheckPath /healthz / 秘密値は `sync: false` で Dashboard 経由
  - **PROMPT_VERSION_DEFAULT を v2.0.0 に昇格**: Phase 1.3e 実証版（hallucination 0% / success 100%）を本番 default に。env 設定漏れでも v1（10〜67% hallucination）にフォールバックしない安全配線
  - **validator: item_type vs category 整合性チェック**（Codex Minor 残対応）: `IssueKind.ITEM_TYPE_CATEGORY_MISMATCH` 新設、`_MEAL_CATEGORIES`/`_LODGING_CATEGORIES` allowlist + Google Places `*_restaurant` 接尾辞許容。meal slot に観光地のみ・lodging slot にレストランのみ等の semantic mismatch を検出。テスト 10 件
  - **docs/setup-guide.md** を Render Blueprint 経由フローと CORS env で刷新
  - **デプロイ実施は user 作業**（Vercel/Render アカウント作成、env 入力、Settings UI で HTTP Timeout 180s）

**分業土台**: ✅ 2026-04-25 整備完了。3 メンバー並行着手可能な状態:
  - 型 3 点同期済み（`ShareResponse` / `SharedPlanResponse` 系、Phase 1.9 DB-4/5 の契約確定）
  - `supabase/migrations/` 00〜04 が冪等で配置済み（DB-1 は Manato 先行実施、DB 担当は今後の新規 ALTER のみ）
  - `.claude/settings.json` に `git add/commit/merge/push/rebase/reset` 系 deny、型 3 点同期対象ファイル編集時の PreToolUse 警告、セッション終了時の todo/lessons 反映 Stop hook を追加（Claude Code 横断で効く）
  - CLAUDE.md → tasks/todo.md → tasks/handoff-*.md の動線を明示、`docs/team-roles.md` / `handoff-frontend.md` も 2026-04-25 の状況で更新

**次にやるべきタスク:**
- [x] **Manato**: Phase 1.3e すべて完遂（hallucination 0% / success 100%、run 27 ベースライン）
- [ ] **Manato（真因判明、SQL 適用待ち）**: 「RLS 42501」は実は `plans.session_id` の **FK 違反 (23503)**。本番 E2E で `proxy-status: PostgREST; error=23503` を確認。anon サインインが `public.sessions` に mirror 行を作らないのが根本原因。**`supabase/migrations/20260425_05_auth_user_sessions_mirror.sql` を Supabase SQL Editor で実行**すれば解消（トリガ + backfill、冪等）。詳細は @tasks/lessons.md 「RLS 42501 の真因は FK 違反」エントリ参照
- [ ] **旧 (参考、SQL 適用後に閉じる)**: `test_routes_plans.py::test_integration_end_to_end_plan_generation` と `::test_integration_lock_conflict_returns_409` の RLS violation (42501) 解消。
  - 2026-04-25 セッションでコード側の調査は完了。`test_rls.py` のコメントに「実 DB の RLS 設定上は挙動が docs/data-model.md 通りになっていない」と既に明記済み = production drift 確定
  - migrations 側は `FOR ALL USING (session_id = auth.uid())` のみで `WITH CHECK` 暗黙、PostgreSQL default で USING と同じになるはず → production policy は何かしら drift している
  - 再開時の手順:
    1. Supabase SQL Editor で下記 2 クエリを実行して現状を確認:
       ```sql
       SELECT tablename, policyname, cmd, permissive, roles, qual, with_check
       FROM pg_policies
       WHERE tablename IN ('plans','participants','plan_items','sessions','evidence_pack_sessions')
       ORDER BY tablename, policyname;

       SELECT c.relname AS tablename, c.relrowsecurity AS rls_enabled, c.relforcerowsecurity AS rls_forced
       FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
       WHERE n.nspname = 'public'
         AND c.relname IN ('plans','participants','plan_items','sessions','evidence_pack_sessions');
       ```
    2. drift がある場合は `supabase/migrations/20260401_00_init.sql` を本番に再適用（冪等 DROP → CREATE で安全）
    3. `cd apps/api && .venv/bin/pytest -m integration tests/test_routes_plans.py -x -v` で 3/3 PASS 確認（Supabase anon sign-in は 30/hour rate limit、直前に他 integration を多く回した直後は 1 時間クールダウン）
    4. PASS したら todo.md と lessons.md（drift 原因と修正の記録）を更新
- [ ] **Manato**: Phase 1.10 デプロイ準備（Vercel + Render）。次セッション着手時の最初の一手は **CORS 追加 + gunicorn 追加 + render.yaml 作成** を `feat/deploy-prep` で実装。`apps/api/src/app.py` に CORS 設定なし / `requirements.txt` に gunicorn なしが本番ブロッカーとして 2026-04-25 セッションで判明。Vercel/Render アカウント作成と本番ドメイン方針の判断はユーザ側で必要（詳細は 1.10 節）
- [x] **Manato（Codex Minor、2026-04-25 完了）**: item_type vs category 整合性 validator を追加（`feat/deploy-prep` ブランチ）。`IssueKind.ITEM_TYPE_CATEGORY_MISMATCH` 新設、`_check_item_type_category_consistency` 実装、`_MEAL_CATEGORIES` / `_LODGING_CATEGORIES` allowlist + `*_restaurant` 接尾辞対応。テスト 10 件 PASS、unit 全 283 件 PASS
- [ ] **Manato（残課題、優先度低、Phase 2 scope）**: Codex (latent) 営業時間 parser 日跨ぎ対応（"22:00-02:00" のような夜またぎ）。MVP 箱根デモは日中観光のみで影響なし
- [ ] **メンバー B**: DB-4〜6 共有 API（型は 2026-04-25 に同期済み、Flask 実装すれば通る） / DB-7 楽天申請 / DB-8 Supabase ログ（@tasks/handoff-db.md）
- [ ] **メンバー C**: 1.4〜1.9 の見た目仕上げ（@tasks/handoff-frontend.md）

詳細は下の各セクション参照。

---

## Phase 0 / プロジェクト基盤

### 0.1 モノレポ初期化
- [x] `pnpm init` でルート package.json
- [x] Turborepo 導入（turbo.json、pnpm-workspace.yaml）
- [x] `apps/web` に Next.js 15 + TypeScript + Tailwind v4 を作成
- [x] `apps/api` に Flask (Python 3.12) プロジェクトを作成
- [x] `packages/shared-types` で TS 型を共有する仕組みを作る
- [x] `pnpm dev` で両方起動することを確認
- [x] 検証: 手動動作確認（必要に応じて Codex レビューを依頼）

### 0.2 Supabase 連携
- [x] Supabase プロジェクト作成、URL と anon key を取得（ユーザ手動）
- [x] `docs/data-model.md` の DDL を Supabase SQL Editor で実行（ユーザ手動、4テーブル作成確認済み）
- [x] フロント側に `@supabase/supabase-js` を導入（`apps/web/src/lib/supabase.ts`）
- [x] バック側に `supabase` (supabase-py) を導入（`apps/api/src/supabase_client.py`）
- [x] 匿名認証が動くことを確認（ライブで sign_in_anonymously → 691 chars の JWT 取得 → admin delete でクリーンアップ、全て OK）
- [x] 検証: `pytest apps/api/tests/test_supabase.py` パス（4件）

### 0.3 外部 API キー取得と疎通
- [x] Google Cloud Console で Places / Routes / Geocoding API を有効化
- [x] OpenAI API キー取得
- [x] Mapbox トークン取得（`.env` に `NEXT_PUBLIC_MAPBOX_TOKEN` セット済、Phase 1.8 で実戦確認）
- [ ] 楽天トラベル App ID 取得（Phase 2 用、早めに申請）
- [x] バック側に疎通テスト実装（`apps/api/src/external/health.py` に Google Places / Routes / Geocoding / OpenAI の4チェック）
- [x] 検証: 全 API のヘルスチェックテストがパス（`pytest -m integration` で 4/4 PASS、5.66秒）

---

## Phase 1 / MVP （絶対完成させる）

### 1.1 データモデルと型の定義
- [x] テスト: vitest で `isValidBudgetBreakdown` / `isValidParticipantCount` / `getEvidenceBadgeInfo` を検証（`packages/shared-types/src/index.test.ts`、12件 PASS）
- [x] 実装: `packages/shared-types/src/index.ts` に enum / entity / API / UI ヘルパー型を定義（`Plan` / `PlanItem` / `Participant` / `Evidence` / `EvidenceBadgeInfo` 他）
- [x] 実装: Pydantic v2 のスキーマを `apps/api/src/schemas/__init__.py` に同期（手動ミラー、`_StrictBase` で未知フィールド拒否）
- [x] 検証: フロント型とバック型が同じ構造（`apps/api/tests/test_schema_parity.py` でフィールド名セットの一致をアサート、12モデル × 26フィールドで 2件 PASS）

### 1.2 Evidence Pack Builder（コア機能、サーバー側 places のみ）
- [x] テスト: Places API で「箱根湯本駅」を検索 → place_id と関連情報が返る
- [x] 実装: `apps/api/src/evidence/places.py` に検索関数
- [x] 実装: `apps/api/src/evidence/routes.py` に DRIVE モード経路関数（Phase 2 recalc 用、JP transit は Routes/Directions サーバー API 不可のため）
- [x] 実装: `apps/api/src/evidence/builder.py` で places-only の EvidencePack を構築
- [x] 実装: `apps/api/src/evidence/pack.py` に Pydantic モデル（`TransitEdge` は Field 制約強化済み、有向エッジ明文化）
- [x] 検証: 架空のスポット名を渡すと空リストが返る（例外にならない）
- [x] 検証: Places / Routes (DRIVE) の integration テスト PASS
- [ ] transit 取得は Phase 1.3 でフロントに移動（`apps/web/src/lib/transit.ts`）

### 1.3 LLM プラン生成 + フロント transit 取得（コア機能）

Phase 1.3 は大物なので 4 段に分割: 1.3a → 1.3b → 1.3c → 1.3d の順。

#### 1.3a: `/api/evidence/places` エンドポイント + キャッシュ ✅ 完了（develop: `0cab182`）
- [x] Supabase `evidence_pack_sessions` テーブル DDL（data-model.md 正典に追加、ユーザ適用済）
- [x] 認証ミドルウェア `apps/api/src/auth.py`（JWT 検証で `g.owner_session_id` セット）
- [x] キャッシュモジュール `apps/api/src/evidence/cache.py`（opportunistic cleanup + retry 2 回）
- [x] Flask blueprint `POST /api/evidence/places`（入力 validate → build_evidence_pack → store_pack → evidence_pack_id + places 最小サブセットを返却）
- [x] `EvidencePlacesResponse` を 3 点同期（docs / shared-types / Pydantic）
- [x] ライブ integration テスト（匿名サインイン → end-to-end 200 OK、Supabase ラウンドトリップ、cleanup 検証）

#### 1.3b: フロント Maps JS SDK DirectionsService ラッパー ✅ 完了（develop: `dd1b9b9`）
- [x] `@googlemaps/js-api-loader` v2 の `setOptions` + `importLibrary("routes")` で dynamic ロード
- [x] `apps/web/src/lib/transit.ts` — `fetchTransitMatrix(places, departureTime, options)` で `{edges, stats}` 返却
- [x] 有向エッジ（A→B と B→A を両方呼ぶ）、近接 10km フィルタ、各 place 被覆保証、並列 5、per-call 2s timeout、グローバル締切 10s（SDK ロード含む）
- [x] JST 固定 HH:mm フォーマット（`Intl.DateTimeFormat` で TZ 依存解消）
- [x] SSR ガード / API キー未設定エラー / Loader 失敗後の singleton クリアで再試行可能
- [x] `ClientTransitEdge` を 3 点同期（pack.TransitEdge と同一 Field 制約、同一性テスト付き）
- [x] Vitest 25 件 PASS（pure helpers + mocked SDK + parallelism / deadline / fail-soft / JST / 再試行）

#### 1.3c: サーバー側 Transit Validator + `/api/plans/generate` 骨組み ✅ 完了（develop へのマージ待ち）
- [x] `apps/api/src/evidence/validator.py` 新規: `validate_client_transit_matrix(edges, evidence_pack) -> list[TransitEdge]`
  - Pydantic 層で値域・文字長・HH:mm は既にガード済（`ClientTransitEdge`）
  - 追加: `from/to_place_id` が Evidence Pack.places に含まれるか
  - 追加: 自己ループ（from == to）を reject
  - 追加: 距離上限 `MAX_EDGE_DISTANCE_KM=15.0`（フロント 10km フィルタ + 浮動小数点誤差マージン）
  - 追加: `(from, to, mode)` 3-tuple 重複は「完全一致 drop / 矛盾 reject」で隠蔽防止
  - 追加: 件数上限 `min(HARD_CAP=200, N*(N-1))` を正規化後件数で判定
- [x] `apps/api/src/routes/plan_routes.py` 新規: `POST /api/plans/generate` 骨組み
  - 認証必須（`require_session`）
  - 入力 `PlanGenerationPayload = { evidence_pack_id: UUID, transit_matrix }` を Pydantic validate（`max_length=200` 静的 hard cap）
  - `load_pack(evidence_pack_id, owner_session_id)` で取り出し、None（期限切れ/未知/所有者不一致）は 404
  - Transit Validator で検証、失敗は 400。404 ログは owner を sha256 8 文字・pack_id prefix 8 文字のみ（PII 対策）
  - 検証済み transit_matrix を base_pack に merge（`model_copy(update=...)`、フロント改ざんデータは LLM に届かない）
  - 通常レスポンス: `{ plan_id: null }`。`?debug=1` の時のみ `{ plan_id: null, evidence_pack: merged }` 追加
  - `MAX_CONTENT_LENGTH=256KB` で巨大ペイロード DoS を一次防御
- [x] `PlanGenerationPayload` を 3 点同期（計画節から実型へ昇格、docs 先行 → shared-types → Pydantic → parity）
- [x] Unit テスト: validator 18 件 + `/api/plans/generate` 16 件（認証 / 入力 / UUID / hard cap / 期限 / 所有者 / DB 障害 500 / 検証失敗 / 成功パス / debug / 413）
- [x] Integration テスト: `/api/evidence/places` → `/api/plans/generate?debug=1` のラウンドトリップ（live Supabase、14km 以内ペア能動選定）
- [x] 検証: pnpm --filter api test 135 件 PASS（unit）、integration 1 件 PASS（箱根 live Places + Supabase）

#### 1.3d: LLM プロンプト / 生成 / ハルシネーション検出 ✅ 完了（develop: Branch 0/A/B/C/D 全マージ済み）

詳細計画は @tasks/plans/2026-04-24-llm-plan-generation.md（v3、Codex GO 済）。5 ブランチに分割して実装、各ブランチで Codex GO 取得。

**Branch 0** `feat/opening-hours-normalization` ✅
- [x] `OpeningHoursSlot` 追加、PlacePoint.opening_hours を構造化、日本語 weekdayDescriptions パーサ

**Branch A** `feat/llm-prompt-and-validator` ✅
- [x] `apps/api/src/llm/prompt.py` に system prompt（v1.0.0）と user prompt builder
- [x] `apps/api/src/llm/schema.py` LlmGeneratedPlan / LlmPlanItem / LlmTransitRef（OpenAI strict 対応）
- [x] `apps/api/src/llm/validator.py` で LLM 出力検証 13 項目（place_id / 時刻 / opening_hours / transit 整合 / 予算 / 時系列 / tz）

**Branch B** `feat/llm-generator-atomic` ✅
- [x] `apps/api/src/llm/generator.py` OpenAI Structured Output + retry×3 + gpt-4o-mini fallback、deadline 150s clamp
- [x] `supabase/migrations/20260424_04_plan_generation_rpcs.sql`: acquire_plan_generation_lock / mark_plan_failed / finalize_plan（compare-and-set + SELECT FOR UPDATE）
- [x] `apps/api/src/plans/storage.py` 3 RPC ラッパ（httpx 例外を RpcTransportError に wrap）

**Branch C** `feat/plans-generate-route` ✅
- [x] `/api/plans/generate` 最終配線: lock → LLM → finalize_plan RPC
- [x] debug mode `?debug=1` 廃止、最終応答を `{ plan_id: <UUID> }` に
- [x] 失敗分類: 422（ハルシネーション/refuse）/ 502（OpenAI transport）/ 504（deadline / finalize RPC transport）/ 500（bad_request / 想定外例外で stuck 防止の保険）
- [x] `_serialize_plan_item` が pack.places から place_name/lat/lng/address を埋める（1.7 MapView 対応）
- [x] `docs/setup-guide.md` 追記: pg_cron 有効化手順 / RPC 適用手順 / Render HTTP timeout 180s / PROMPT_VERSION

**Branch D** `feat/db-integrity-sweep` ✅
- [x] DB-2: RLS E2E integration テスト（`apps/api/tests/test_rls.py`、他セッション遮断 / service_role バイパス / evidence_pack_sessions 完全遮断）
- [x] DB-3: pg_cron クリーンアップ（`supabase/migrations/20260424_03_cleanup_cron.sql`、evidence_pack_sessions / stuck generating / abandoned draft+failed、succeeded は保全）

**検証**: `pytest -m "not integration"` 234 件 PASS。integration は rate limit リセット後に `pytest -m integration` で再確認推奨。

**実環境検証（2026-04-25 更新）**:
- [x] `pytest -m integration tests/test_rls.py`（8 件）: **2026-04-25 00:49 JST に全 8 件 PASS（10.5 秒）**。rate limit は 1 時間クールダウンで回復した
- [ ] `pytest -m integration tests/test_routes_plans.py`（3 件）: **1/3 PASS（`test_integration_invalid_transit_returns_400` のみ）**。残 2 件（`test_integration_end_to_end_plan_generation` / `test_integration_lock_conflict_returns_409`）は anon client から `plans` への INSERT 時に **RLS violation (code=42501, "new row violates row-level security policy for table plans")** で失敗。rate limit ではなく RLS policy 側の問題
  - **原因仮説**: 本番 Supabase の "Plans of own session" policy が `FOR ALL USING (session_id = auth.uid())` だが WITH CHECK が事実上効かず anon INSERT を deny している。または本番 policy が migrations ファイルと drift している可能性
  - **推奨対応（次セッション）**: (a) `supabase/migrations/20260401_00_init.sql` を本番に再適用して DROP POLICY IF EXISTS → CREATE POLICY で最新に揃える、(b) もしくは test 側を service_role 経由の INSERT に書き換える（フロント 1.5 の実挙動は anon INSERT なので (a) が本筋）、(c) Supabase SQL Editor で `SELECT * FROM pg_policies WHERE tablename='plans';` を実行して現在の policy を確認
  - **今回は「検証と記録のみ」指示のためコード修正なし**。次の Manato 作業で吸収
- [ ] `apps/api/scripts/verify_hallucination_rate.py --runs 10`: 2 run（OpenAI 合計 ~$4-6）いずれも hallucination 1/10 = **10%**。詳細 issue breakdown は @tasks/lessons.md 2026-04-25 エントリ。次イテレーション案 (a)〜(d) に従い prompt token / validator retry / fixture を見直す
  - **閉塞原因の仮説（lessons.md 参照）**: prompt 22k tokens、opening_hours retry の効きが弱い、transit_matrix 拡張による places 情報の埋没
  - **2026-04-25 着手済みの改善（Step 1-2、再検証未実施）**:
    - (Step 1) `verify_hallucination_rate.py::_build_transit_matrix` を「各 place から最近傍 5 edges、hard_cap=100」に変更。14km 全ペア 160 edges → 75 edges（-53%）で実運用密度（フロント SDK 実測 ~40 edges）に近づけた
    - (Step 2) `src/llm/prompt.py::_place_for_llm` から `lat` / `lng` / `relevance_tags` を除外（token 節約）。system prompt ルール 9（opening_hours 遵守）を「最頻出の違反」として強調
    - **効果（計測値）**: prompt token 22,385 → **11,645（-48%）**。evidence-pack.md 目安 10k 内は届かず、12k warning threshold は +350 で僅か超
    - unit テスト 60 件 (LLM 関連) PASS、regression なし
  - **Step 3 実施（2026-04-25 夜、`--runs 5`、OpenAI ~$1）**: 結果 **悪化**。success 0/5、hallucination 1/5 = **20%**。内訳: `unknown_transit_edge=7`（新規大量発生）/ `outside_opening_hours=5`（前回 12 から激減）/ `budget_exceeded=1` / `unknown_place_id=1`
    - opening_hours 違反は system prompt 強調で激減できたが、transit_matrix を 160→75 に攻めすぎて **LLM が pack にない edge を hallucinate する新しい失敗モード** が噴出
    - validator 的には「制約違反の押し出し」現象。片方を締めるともう片方が開く
  - **次イテレーション仮説（未実施、Manato 次セッション）**:
    - (a') transit_matrix を最近傍 5 → 8 に戻す（75 → ~120 edges、prompt ~13k tokens 想定）
    - (b') system prompt に「transit_matrix に該当 edge がなければ経路を使わず別 places を選び直す」と明示
    - (e') **LCaMO 論文（石原・中村 2026）思想の適用、本命候補**: LLM の役割を「pack 内 place_id の順列選定 + slot 指定」に限定し、`start_time` / `transit_ref` / `cost_jpy` はサーバ決定論で埋める設計改修。5 種の validator issue を構造的に 0 化できる想定。詳細と選択肢は @tasks/lessons.md「2026-04-25 深夜: LCaMO 論文からの構造的知見」エントリ参照
    - MVP 合格条件を「hallucination + unknown_transit_edge ≤ 10%」に下げる判断もあり（ハッカソン提出優先、Manato 次セッションで判断）
  - **進め方の選択肢（Manato 次セッションで判断）**:
    - (A) 設計 plan ファイル（`tasks/plans/2026-04-25-lcamo-inspired-plan-generation.md`）を先に書き、実装は次々セッション
    - (B) Phase 1.3e 新ブランチで骨組みだけ実装（schema + slot テンプレ + transit 自動挿入 stub）、動作確認は次
    - (C) ハッカソン提出優先で MVP 合格条件を緩和、LCaMO 応用は Phase 2 以降
  - **再現手順**: `cd apps/api && .venv/bin/python scripts/verify_hallucination_rate.py --runs 10`（env: OPENAI_API_KEY / GOOGLE_MAPS_API_KEY 必須）

### 1.4〜1.9: **フロント骨組み + デザイン引き渡し**（並列 3 トラック運用）

1.3c マージ後、Manato/Claude がフロントの「骨組み」を `feat/frontend-skeleton` で一括実装し、
その後デザイナー（メンバー C）に「見た目」をお任せする運用に切替。
詳細計画は @tasks/plans/2026-04-21-frontend-skeleton.md、
引き継ぎ資料は @tasks/handoff-frontend.md 参照。

#### 1.4〜1.9 骨組み（Claude/Manato 担当、6 ブランチに分割して実装） ✅ 完了

**Branch 0** `feat/plan-generation-plan-id` ✅ (develop: `807fca8`)
- [x] Task 0: `PlanGenerationPayload` に `plan_id` 追加 + `plans.status` カラム追加（3 点同期、DDL 追記）

**Branch 1** `feat/frontend-foundation` ✅ (develop: `369127b`)
- [x] Task 1: 依存パッケージ導入（shadcn/ui、React Query + Devtools、Zustand、react-hook-form、zod、Phosphor Icons、Mapbox、react-qr-code、Framer Motion）+ Providers 配線
- [x] Task 2: API クライアント (`lib/api.ts`) + `generationSessionStore` + zod スキーマ + モック fixtures（`queryFn` 分岐で `initialData` 不使用）
- [x] Task 3: 共通コンポーネント骨組み（EvidenceBadge / PlanTimeline / PlanItem / BudgetSummary / BudgetBreakdownSlider / ParticipantTabs / ParticipantForm）

**Branch 2** `feat/frontend-core-flow` ✅ (develop: `909bec6`)
- [x] Task 4: 1.4 ランディングページ骨組み（CTA + 3 軸カード）
- [x] Task 5: 1.5 希望入力画面骨組み（フォーム配線 + plan_id 発行 + plans INSERT + `/api/evidence/places` + Zustand stash + status 遷移）
- [x] Task 6: 1.6 プラン生成中画面骨組み（Zustand 取得 + transit 取得 + `/api/plans/generate` kick + 成功/失敗時 clearSession で重複 generate 防止）

**Branch 3** `feat/frontend-plan-view` ✅ (develop: `4f649aa`)
- [x] Task 7: 1.7 プラン閲覧画面骨組み（3 カラム: タイムライン / 予算 / マップ、`USE_MOCKS` 分岐は `lib/api.ts` 内）

**Branch 4** `feat/frontend-extra-pages` ✅ (develop: `d46fe2a`)
- [x] Task 8: 1.8 地図ビュー骨組み（Mapbox 初期化 + マーカー + 1.7 への差し込み）
- [x] Task 9: 1.9 プラン共有画面骨組み（QR + 共有 URL、API 未接続で 1.9 本実装待ち）

**Branch 5** `feat/frontend-handoff`
- [x] Task 10: ハンドオフ資料 + todo.md + architecture.md 最終化 + Codex レビュー Must-fix 反映（API URL 環境変数名を `NEXT_PUBLIC_API_BASE_URL` に統一、1.6 成功/失敗時の clearSession 追加、handoff 状態を完成ずみに更新、TabsTrigger ネスト button を外出し、getActiveSession で TTL 切れ時に autoclear、updatePlanStatus failed のログ明示化）
- [x] 検証: `pnpm --filter web test` 61 件 PASS、`pnpm --filter web exec tsc --noEmit` PASS

#### 1.4〜1.9 デザイン着地（メンバー C 担当、骨組みマージ後）
- [ ] 1.4 ランディングページの見た目仕上げ（ヒーロー / CTA / 3 軸カード、AI 感のない表現）
- [ ] 1.5 希望入力画面の見た目仕上げ（参加者タブ、予算スライダー、日本語 15 文字以上で崩れない）
- [ ] 1.6 プラン生成中画面のアニメーション実装（5 ステップのプログレス、Framer Motion）
- [ ] 1.7 プラン閲覧画面の見た目仕上げ（タイムラインを主役に、予算サマリ / マップは脇役）
- [ ] 1.8 地図ビューの見た目仕上げ（マーカークリック → PlanItem スクロール、ミニタイムラインストリップ）
- [ ] 1.9 プラン共有画面の見た目仕上げ（QR + 共有 URL、印刷可能なレイアウト）
- [ ] UI 耐久性チェック: 長文スポット名 / 0 件 / ローディング / エラー / 参加者数 2〜5 で全画面崩れないこと
- [ ] Design Tokens の最終調整（`globals.css` + `.claude/rules/frontend-design.md` 更新）

#### 1.9 共有 API 実装（メンバー B 担当、@tasks/handoff-db.md の DB-4/5/6）
- [x] 型 `ShareResponse` / `SharedPlanResponse` を docs / shared-types / Pydantic / parity に 3 点同期（2026-04-25 Manato、DB 担当の実装は contract 通りに通せば OK）
- [ ] `POST /api/plans/:id/share`（share_token 生成、owner 検証、`plans.status='succeeded'` 限定）
- [ ] `GET /api/plans/shared/:token`（Flask + service_role、RLS バイパス経路、handoff-db.md 参照）
- [ ] 共有用 RLS ポリシー監査（handoff-db.md の DB-6 に要件整理）

### 1.x: **DB 整理タスク**

詳細は @tasks/handoff-db.md 参照。2026-04-25 時点で **Manato 担当分は完了**、**メンバー B 担当分が残り**。

#### Manato 担当（1.3d と合流して対応） ✅ 完了
- [x] DB-2: RLS の E2E テスト（`apps/api/tests/test_rls.py`、他セッションからのアクセス遮断検証。integration は rate limit 回復後に完走確認）
- [x] DB-3: 定期クリーンアップ（`supabase/migrations/20260424_03_cleanup_cron.sql`）: (a) `evidence_pack_sessions` の期限切れ、(b) `plans WHERE status='generating' AND updated_at < now() - INTERVAL '1 hour'`、(c) `plans WHERE status IN ('draft','failed') AND created_at < now() - INTERVAL '24 hours'`。`succeeded` は保全

#### メンバー B 担当（1.3d と完全独立、並行可）
- [x] DB-1: `supabase/migrations/` 冪等 5 連番ファイル配置（2026-04-25 Manato 先行実施）。DB 担当は今後の DDL 変更時に新規連番ファイルを追加する運用を維持
- [ ] DB-7: 楽天トラベル API の App ID 取得（Phase 2 事前準備、申請に時間がかかるので今すぐ）
- [ ] DB-8: Supabase Row-Level Logging（pg_stat_statements など、Phase 1.3d の RPC + plan_items INSERT が稼働し始めるのでログ観測基盤を用意）
- [ ] 1.9 共有 API は上の「1.9 共有 API 実装」セクションで DB-4/5/6 として別管理

<details>
<summary>（旧）1.4 ランディングページ (01) — 骨組みタスクへ吸収済み</summary>

- [ ] テスト: ヒーロー、3軸カード、CTA が描画される
- [ ] 実装: `apps/web/src/app/page.tsx`
- [ ] UI 耐久性: 画面の主役が「旅を計画する」CTA になっている
- [ ] UI 耐久性: 長文テキスト（説明文 60文字以上）で崩れない
- [ ] 検証: 手動動作確認（必要に応じて Codex レビューを依頼）
</details>

<details>
<summary>（旧）1.5〜1.7 希望入力画面 / プラン生成中 / プラン閲覧 — 骨組みタスクへ吸収済み</summary>

### 1.5 希望入力画面 (04)
- [ ] テスト: 参加者を 2〜5 人で追加・削除できる
- [ ] テスト: 予算配分スライダーが常に合計 100% を保つ
- [ ] テスト: 全員分の入力が埋まるまで「プランを生成」ボタンが無効
- [ ] 実装: `apps/web/src/app/plan/new/page.tsx`
- [ ] 実装: Zustand で希望入力ステートを管理
- [ ] UI 耐久性: 参加者名が日本語 15文字以上でも崩れない
- [ ] UI 耐久性: タブの人数が 5 人になっても横スクロールなしで収まる

### 1.6 プラン生成中画面 (05)
- [ ] テスト: 5 ステップの状態変化がアニメーションする
- [ ] 実装: `apps/web/src/app/plan/[id]/generating/page.tsx`
- [ ] 実装: バックからの SSE（Server-Sent Events）で進行状況を受信
- [ ] 実装: エラー時の復帰導線（「もう一度試す」ボタン）
- [ ] UI 耐久性: 生成に 60 秒以上かかってもタイムアウトしない（バック側の許容時間を確認）

### 1.7 プラン閲覧画面 (06)
- [ ] テスト: タイムライン、予算サマリ、ミニマップの3カラムが描画
- [ ] テスト: 各 PlanItem に Evidence バッジが表示される
- [ ] テスト: 交通区間が電車便名・運賃・所要時間とともに表示
- [ ] 実装: `apps/web/src/app/plan/[id]/page.tsx`
- [ ] 実装: タブで「タイムライン / マップ / 予算」を切り替え
- [ ] UI 耐久性: 長文スポット名（30文字超）で崩れない
- [ ] UI 耐久性: PlanItem が0件（空状態）でも画面が成立
- [ ] UI 耐久性: ローディング状態・エラー状態を定義

### 1.8 地図ビュー (07)
- [ ] テスト: Mapbox 地図が描画、全スポットのマーカーが配置
- [ ] テスト: スポット間の経路ポリラインが描画
- [ ] 実装: `apps/web/src/components/MapView.tsx`
- [ ] 実装: マーカークリックで該当 PlanItem にスクロール
- [ ] 実装: 下部にミニタイムラインストリップ（横スクロール）
- [ ] UI 耐久性: スポット数 0 でも地図が成立
- [ ] UI 耐久性: Mapbox トークン未設定時に適切なエラーメッセージ

### 1.9 プラン共有 (08)
- [ ] テスト: 共有 URL でプランが読み取り専用表示される
- [ ] テスト: QR コードが生成される
- [ ] 実装: `apps/web/src/app/plan/[id]/share/page.tsx`
- [ ] 実装: `react-qr-code` で QR 表示
- [ ] 実装: PDF 生成はバック側で ReportLab or WeasyPrint
- [ ] 検証: URL 共有 → 別端末で閲覧可能

</details>

### 1.10 デプロイと初回公開

#### デプロイ前に必須のコード修正（`feat/deploy-prep` ブランチで実装、2026-04-25 完了）
- [x] **🔴 CORS 設定追加**: `flask-cors>=5.0,<7.0` を requirements 追加、`apps/api/src/app.py` に `_resolve_cors_origins()` + `CORS(app, ...)` を実装。env `CORS_ALLOWED_ORIGINS`（CSV）読み込み、未設定時は `http://localhost:3000` のみ許可。`Authorization` / `Content-Type` ヘッダ + `GET/POST/OPTIONS` メソッド許可。CORS unit テスト 6 件 PASS（`tests/test_cors.py`）
- [x] **🔴 `gunicorn>=22.0,<24.0` を requirements に追加**: ローカル smoke test で `gunicorn 'src.app:create_app()'` boot 成功 + `/healthz` 200 OK + ACAO ヘッダ付与確認済
- [x] **🟡 `render.yaml` 作成**: `singapore` region / `--workers 1 --timeout 180` / `healthCheckPath: /healthz` / env var 宣言（秘密値は `sync: false` で Dashboard 経由）
- [x] **🟡 `PROMPT_VERSION_DEFAULT = "v2.0.0"` に変更**: 本番デプロイ時に env 設定を忘れても Phase 1.3e で実証された LCaMO 構造化版（hallucination 0% / success 100%）が走るように。test_llm_prompt の default 期待値も v2 に更新、test_llm_generator は v1 schema mock のため `autouse fixture` で `PROMPT_VERSION=v1.0.0` を明示
- [x] **🟡 `docs/setup-guide.md` のデプロイ節を更新**: render.yaml Blueprint 経由のフロー、CORS_ALLOWED_ORIGINS の必須化、env 一覧の刷新
- [x] **検証**: API unit 273 件 PASS / Web 61 件 PASS / Web tsc PASS / gunicorn smoke OK / CORS ヘッダ実出力確認

#### デプロイ実施
- [ ] フロント: Vercel に `apps/web` をデプロイ（env 5 件: `NEXT_PUBLIC_API_BASE_URL` / `NEXT_PUBLIC_GOOGLE_MAPS_BROWSER_KEY` / `NEXT_PUBLIC_SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_ANON_KEY` / `NEXT_PUBLIC_MAPBOX_TOKEN`）
- [ ] バック: Render に `apps/api` をデプロイ（env 4 件必須: `GOOGLE_MAPS_API_KEY` / `OPENAI_API_KEY` / `NEXT_PUBLIC_SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY`、任意で `PROMPT_VERSION`）。HTTP Timeout 180s 必須
- [ ] Google Maps Console: ブラウザキーの HTTP referrer 制限に Vercel 本番ドメインを追加 / サーバキーの IP 制限に Render outbound IP を追加（Render の固定 IP は有料 plan 機能なので無料 plan は IP 制限スキップ可）
- [ ] Supabase: 匿名認証が production で有効か確認。RLS 42501 残課題（test_routes_plans 2 件）はデプロイ後の本番動作に直接影響しないが、anon plans INSERT が必要なので結局解決必要
- [ ] 本番環境の E2E テスト（1つのデモシナリオを最初から最後まで、希望入力 → 生成 → 閲覧 → 共有）
- [ ] パフォーマンス: プラン生成が 60 秒以内（Phase 1.3e で 4.4s/run 達成済、Render cold start を考慮しても余裕あり）
- [ ] 検証: 3人（チーム全員）で実機テスト

---

## Phase 2 / 差別化機能（ハッカソン向けに優先度高）

### 2.1 出発モード切替（お任せ / アンカー / テーマ）
- [ ] テスト: 3モードに応じて LLM プロンプトが切り替わる
- [ ] テスト: アンカー型で指定したスポットが必ずプランに含まれる
- [ ] 実装: `apps/web/src/components/ModeSelector.tsx`
- [ ] 実装: アンカー型のスポット検索 UI（Places Autocomplete）
- [ ] UI 耐久性: アンカー3つ以上でもレイアウトが崩れない

### 2.2 予算配分の制約化
- [ ] テスト: スライダーの配分が LLM プロンプトに数値制約として渡される
- [ ] テスト: 生成結果が配分内に収まっている（カテゴリごと合計を検証）
- [ ] 実装: Evidence Pack に `budget_breakdown` フィールドを追加
- [ ] 実装: LLM プロンプトで「宿泊は予算の40%以内、食事は30%以内」と指定
- [ ] 検証: 配分を極端に変える（宿泊80%など）と出力が追従する

### 2.3 宿泊費 API 連携
- [ ] テスト: 楽天トラベル API で「箱根」「2025-10-18〜20」の検索結果が返る
- [ ] 実装: `apps/api/src/evidence/lodging.py`
- [ ] 実装: 予算配分の宿泊枠に収まる宿を候補提示
- [ ] 実装: プラン内の宿泊 PlanItem に楽天トラベル URL を付与
- [ ] UI: 宿泊選択モーダル（3〜5件の候補）

### 2.4 手動編集 + 部分再提案
- [ ] テスト: PlanItem を削除すると後続の start_time が再計算される
- [ ] テスト: 「代替案」ボタンで1アイテムだけ差し替えられる（他は変わらない）
- [ ] 実装: `apps/api/src/llm/regenerate.py` で単一アイテム再生成 API
- [ ] 実装: `apps/web` でドラッグ&ドロップ並び替え（dnd-kit 等）
- [ ] 実装: 並び替え時に Routes API で再計算
- [ ] UI 耐久性: 再計算中のローディング表示

### 2.5 Evidence 詳細モーダル
- [ ] テスト: バッジクリックで根拠が展開される
- [ ] 実装: `apps/web/src/components/EvidenceModal.tsx`
- [ ] 表示内容: 実在確認日、営業時間、評価、出典、取得時刻

---

## Phase 3 / 余裕があれば

### 3.1 飲食費の精密化
- [ ] HotPepper Gourmet API 連携（個人開発OK）
- [ ] price_level だけでなく平均予算（朝/昼/夜別）を取得
- [ ] Evidence バッジを「~ 推定」から「✓ HotPepper」に格上げ

### 3.2 入場料の半自動取得
- [ ] Webスクレイピング（許可されたサイトのみ）で主要観光地の入場料をキャッシュ
- [ ] キャッシュ未ヒット時は LLM 推定のまま

### 3.3 当日の旅のしおりビュー
- [ ] モバイル最適化、オフライン対応（Service Worker）
- [ ] 次の予定までのカウントダウン表示

### 3.4 リモート同期（大規模拡張）
- [ ] Supabase Realtime の導入
- [ ] マルチカーソル表示
- [ ] 楽観的ロック

---

## 定常運用ルール（Phase を問わず）

- 各タスク完了時に `tasks/lessons.md` を確認。2回目の失敗は `.claude/rules/` に昇格
- Codex レビューはユーザ依頼時のみ実行（必須ではない）
- UI 実装タスクには必ず UI 耐久性チェック（長文/0件/エラー状態）を含める
- コミット前に `pnpm test` が全パス
