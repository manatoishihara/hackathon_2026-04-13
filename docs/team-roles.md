# Team Roles & Interface Spec

## 役割分担

### Manato（全体統括 + AI/LLM 担当）

- プロジェクト全体の設計判断
- `docs/data-model.md` と `docs/evidence-pack.md` の策定・更新（これが全員のIF仕様）
- Evidence Pack Builder の実装
- LLM プロンプト設計と検証
- Codex レビューの運用（依頼があった PR を Codex に通す）
- Phase 1.2、1.3、2.4、3.1 のタスクを主担当

### メンバー B（バックエンド + 外部 API 連携）

- Flask プロジェクト構成
- Supabase 連携（認証、RLS、DDL 運用）
- Google Maps Platform 連携（Places, Routes, Geocoding）
- 楽天トラベル API 連携
- Render へのデプロイ
- Phase 0.2、0.3、1.9、2.3 のタスクを主担当

### メンバー C（フロントエンド + UX + 地図）

- Next.js アプリ全体の実装
- shadcn/ui の独自テーマ適用
- Mapbox 地図描画
- Zustand 状態管理
- Vercel へのデプロイ
- Phase 1.4、1.5、1.6、1.7、1.8 のタスクを主担当

## Interface 仕様（Manato さんが握る部分）

他メンバーが並行作業できるよう、以下をコードを書くより先に確定させる。

### 1. 型定義

`packages/shared-types/src/index.ts` が全ての型の source of truth。
Pydantic スキーマ（`apps/api/src/schemas/`）はこれと一対一対応。

**変更時のフロー**:
1. Manato が `shared-types/src/index.ts` を更新
2. 同時に `docs/data-model.md` を更新
3. Pydantic スキーマも更新
4. 全員に Slack で告知
5. 各メンバーは自分の担当箇所を更新

### 2. API エンドポイント

```
POST   /api/sessions                     セッション作成
POST   /api/plans/generate               プラン生成（Evidence Pack 構築 → LLM）
GET    /api/plans/:id                    プラン取得
PATCH  /api/plans/:id/items/:item_id     アイテム編集
POST   /api/plans/:id/items/:item_id/regenerate  部分再生成 (Phase 2)
POST   /api/plans/:id/items/reorder      並び替え (Phase 2)
POST   /api/plans/:id/share              共有トークン発行
GET    /api/plans/shared/:token          共有閲覧（編集不可）
```

リクエスト/レスポンスの詳細型は `docs/data-model.md` の「API リクエスト/レスポンス」セクション参照。

### 3. Evidence Pack スキーマ

`docs/evidence-pack.md` が正典。Manato 以外が変更してはならない。
質問や改善案がある場合は GitHub Issue で起票。

## ブランチ戦略

- `main`: 本番デプロイ対象、直接 push 禁止
- `develop`: 開発の統合ブランチ
- `feat/phase-X-Y-description`: 各タスクのブランチ
- PR → コードレビュー（必要なら Codex レビューを依頼）→ develop へマージ

## コミュニケーション

- **日次**: 朝会（オンライン 15 分、進捗と blocker のみ）
- **設計相談**: GitHub Discussions または Slack
- **コードレビュー**: GitHub PR（Manato が最終確認、Codex MCP は依頼ベースで併用）

## 開発規約

- 型の変更は必ず Manato 経由
- Evidence Pack の構造変更は必ず Manato 経由
- UI の実装中に気づいたデザイン変更は `.claude/rules/frontend-design.md` を更新
- 2 回繰り返した失敗は `tasks/lessons.md` → `.claude/rules/` に昇格

## 進捗管理

- `tasks/todo.md` をチェックボックス形式で共有
- 各タスクの完了条件は「テスト全パス」。Codex レビューは必要に応じて依頼
- 日次朝会で進捗を確認
