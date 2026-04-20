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
- [ ] Supabase プロジェクト作成、URL と anon key を取得
- [ ] `docs/data-model.md` の DDL を Supabase SQL Editor で実行
- [ ] フロント側に `@supabase/supabase-js` を導入
- [ ] バック側に `supabase-py` を導入
- [ ] 匿名認証が動くことを確認（テスト: セッション作成 → 取得）
- [ ] 検証: `pytest apps/api/tests/test_supabase.py` パス

### 0.3 外部 API キー取得と疎通
- [ ] Google Cloud Console で Places / Routes / Geocoding API を有効化
- [ ] OpenAI API キー取得
- [ ] Mapbox トークン取得
- [ ] 楽天トラベル App ID 取得（Phase 2 用、早めに申請）
- [ ] バック側に疎通テスト実装（各 API を最小リクエストで叩く）
- [ ] 検証: 全 API のヘルスチェックテストがパス

---

## Phase 1 / MVP （絶対完成させる）

### 1.1 データモデルと型の定義
- [ ] テスト: `shared-types/tests/test_plan_item.ts` で型の必須フィールドを検証
- [ ] 実装: `packages/shared-types/src/index.ts` に `Plan`, `PlanItem`, `Participant`, `EvidenceBadge` 型を定義
- [ ] 実装: Pydantic v2 のスキーマを Flask 側に同期（または codegen）
- [ ] 検証: フロント型とバック型が同じ構造を表現している

### 1.2 Evidence Pack Builder（コア機能）
- [ ] テスト: Places API で「箱根湯本駅」を検索 → 結果に place_id と営業時間が含まれる
- [ ] テスト: Routes API で「新宿駅 → 箱根湯本駅」transit → 運賃と所要時間が返る
- [ ] 実装: `apps/api/src/evidence/places.py` に検索 + 詳細取得関数
- [ ] 実装: `apps/api/src/evidence/routes.py` に transit 経路取得関数
- [ ] 実装: `apps/api/src/evidence/builder.py` で Evidence Pack を構築
- [ ] 検証: 架空のスポット名を渡すと検索失敗を適切にハンドリング
- [ ] 検証: docs/evidence-pack.md の仕様通りの JSON を出力する

### 1.3 LLM プラン生成（コア機能）
- [ ] テスト: Evidence Pack + 希望入力を渡して OpenAI から構造化 JSON が返る
- [ ] テスト: LLM の出力 place_id が必ず Evidence Pack に含まれる（ハルシネーション検出）
- [ ] 実装: `apps/api/src/llm/prompt.py` に system prompt と user prompt builder
- [ ] 実装: `apps/api/src/llm/generator.py` で OpenAI 呼び出し + JSON Schema 検証
- [ ] 実装: 失敗時のリトライ（最大2回、指数バックオフ）
- [ ] 検証: 10 回生成して架空スポット出力率 0%（ハルシネーション対策の効果測定）

### 1.4 ランディングページ (01)
- [ ] テスト: ヒーロー、3軸カード、CTA が描画される
- [ ] 実装: `apps/web/src/app/page.tsx`
- [ ] UI 耐久性: 画面の主役が「旅を計画する」CTA になっている
- [ ] UI 耐久性: 長文テキスト（説明文 60文字以上）で崩れない
- [ ] 検証: 手動動作確認（必要に応じて Codex レビューを依頼）

### 1.5 希望入力画面 (04)
- [ ] テスト: 参加者を 2〜5 人で追加・削除できる
- [ ] テスト: 予算配分スライダーが常に合計 100% を保つ
- [ ] テスト: 全員分の入力が埋まるまで「プランを生成」ボタンが無効
- [ ] 実装: `apps/web/src/app/plan/new/page.tsx`
- [ ] 実装: Zustand で希望入力ステートを管理
- [ ] UI 耐久性: 参加者名が日本語 15文字以上でも崩れない
- [ ] UI 耐久性: タブの人数が 5 人になっても横スクロールなしで収まる
- [ ] 検証: 手動動作確認（必要に応じて Codex レビューを依頼）

### 1.6 プラン生成中画面 (05)
- [ ] テスト: 5 ステップの状態変化がアニメーションする
- [ ] 実装: `apps/web/src/app/plan/[id]/generating/page.tsx`
- [ ] 実装: バックからの SSE（Server-Sent Events）で進行状況を受信
- [ ] 実装: エラー時の復帰導線（「もう一度試す」ボタン）
- [ ] UI 耐久性: 生成に 60 秒以上かかってもタイムアウトしない（バック側の許容時間を確認）
- [ ] 検証: 手動動作確認（必要に応じて Codex レビューを依頼）

### 1.7 プラン閲覧画面 (06)
- [ ] テスト: タイムライン、予算サマリ、ミニマップの3カラムが描画
- [ ] テスト: 各 PlanItem に Evidence バッジが表示される
- [ ] テスト: 交通区間が電車便名・運賃・所要時間とともに表示
- [ ] 実装: `apps/web/src/app/plan/[id]/page.tsx`
- [ ] 実装: タブで「タイムライン / マップ / 予算」を切り替え
- [ ] UI 耐久性: 長文スポット名（30文字超）で崩れない
- [ ] UI 耐久性: PlanItem が0件（空状態）でも画面が成立
- [ ] UI 耐久性: ローディング状態・エラー状態を定義
- [ ] 検証: 手動動作確認（必要に応じて Codex レビューを依頼）

### 1.8 地図ビュー (07)
- [ ] テスト: Mapbox 地図が描画、全スポットのマーカーが配置
- [ ] テスト: スポット間の経路ポリラインが描画
- [ ] 実装: `apps/web/src/components/MapView.tsx`
- [ ] 実装: マーカークリックで該当 PlanItem にスクロール
- [ ] 実装: 下部にミニタイムラインストリップ（横スクロール）
- [ ] UI 耐久性: スポット数 0 でも地図が成立
- [ ] UI 耐久性: Mapbox トークン未設定時に適切なエラーメッセージ
- [ ] 検証: 手動動作確認（必要に応じて Codex レビューを依頼）

### 1.9 プラン共有 (08)
- [ ] テスト: 共有 URL でプランが読み取り専用表示される
- [ ] テスト: QR コードが生成される
- [ ] 実装: `apps/web/src/app/plan/[id]/share/page.tsx`
- [ ] 実装: `react-qr-code` で QR 表示
- [ ] 実装: PDF 生成はバック側で ReportLab or WeasyPrint
- [ ] 検証: URL 共有 → 別端末で閲覧可能

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
