# TODO: Routeful 実装計画

ハッカソン出品までの実装計画。Phase 1 は MVP として必ず完成させる。
各タスクは TDD 形式（テスト先行 → Red → Green → Refactor → 検証）で進める。

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

#### 1.3d: LLM プロンプト / 生成 / ハルシネーション検出
- [ ] `apps/api/src/llm/prompt.py` に system prompt と user prompt builder（`docs/evidence-pack.md` の仕様通り）
- [ ] `apps/api/src/llm/generator.py` で OpenAI 呼び出し + JSON Schema 検証（structured output）
- [ ] `apps/api/src/llm/validator.py` で LLM 出力の place_id 実在 / 時刻 / opening_hours / 予算 / 時系列を検証
- [ ] 失敗時のリトライ（最大 2 回、指数バックオフ）、`gpt-4o` → `gpt-4o-mini` フォールバック
- [ ] `/api/plans/generate` の最終応答を `{ plan_id }` に戻し、plan_items を Supabase に保存
- [ ] 検証: 10 回生成して架空スポット出力率 0%（ハルシネーション対策の効果測定）

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
- [ ] `POST /api/plans/:id/share`（share_token 生成）
- [ ] `GET /api/plans/shared/:token`（read-only、RLS バイパス経路）
- [ ] 共有用 RLS ポリシー監査
- [ ] 型 `ShareResponse` を shared-types/Pydantic に追加（Manato と調整）

### 1.x: **DB 整理タスク**

詳細は @tasks/handoff-db.md 参照。2026-04-24 整理で **Manato（1.3d と合流）** と **メンバー B（独立）** に分業。

#### Manato 担当（1.3d と合流して対応）
- [ ] DB-2: RLS の E2E テスト（`apps/api/tests/test_rls.py`、他セッションからのアクセス遮断検証）— 1.3d で plan_items 書き込みを始める前に必須
- [ ] DB-3: 定期クリーンアップ（pg_cron）: (a) `evidence_pack_sessions` の期限切れ、(b) `plans WHERE status='generating' AND updated_at < now() - INTERVAL '1 hour'`（stuck 中断対策）、(c) `plans WHERE status IN ('draft','failed') AND created_at < now() - INTERVAL '24 hours'`。`succeeded` は保全

#### メンバー B 担当（1.3d と完全独立、並行可）
- [ ] DB-1: `supabase/migrations/` ディレクトリ化（DDL 分割 + 連番管理）
- [ ] DB-7: 楽天トラベル API の App ID 取得（Phase 2 事前準備、申請に時間がかかるので今すぐ）
- [ ] DB-8: Supabase Row-Level Logging（1.3d 着手前に整備、pg_stat_statements など）
- [ ] （1.9 共有 API は上の「1.9 共有 API 実装」セクションで DB-4/5/6 として別管理）

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
- [ ] フロント: Vercel に `apps/web` をデプロイ（環境変数設定）
- [ ] バック: Render に `apps/api` をデプロイ（無料プラン）
- [ ] 本番環境の E2E テスト（1つのデモシナリオを最初から最後まで）
- [ ] パフォーマンス: プラン生成が 60 秒以内
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
