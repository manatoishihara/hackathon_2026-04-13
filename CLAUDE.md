# Routeful

みんなで集まって1画面を囲みながら使う、AI旅行計画ツール（対面想定）。
LLMの意味理解 + 外部APIの構造化データで、実在し時間的に成立するプランを生成する。
判断に迷ったら「使う人たちが、その場で迷わず合意できるか」で決める。

## Tech Stack
Next.js 15 / TypeScript / Tailwind v4 / shadcn/ui / Flask / Supabase (DB+匿名Auth) / OpenAI GPT-4o

## Commands
- `pnpm dev` — フロント+バック同時起動
- `pnpm test` — 全パッケージのテスト
- `pnpm --filter web build` — フロントビルド
- `pnpm --filter api test` — バックエンドテスト

## Do NOT（compaction後も絶対に守れ）
- `git commit` / `git add` / `git merge` / `git push` を絶対に自分で実行するな。コミット・マージ・プッシュは必ずユーザが手動で行う。Claude はコミットメッセージ案と対象ファイル一覧を提示するだけ
- Codexレビューを勝手に起動するな。ユーザが「Codexに見せて」等と明示的に依頼した時のみ実行
- LLMに外部データを渡さず推論させるな。必ずEvidence Pack経由
- 架空の場所・架空の時刻を出力するな。Places API / Routes APIで検証せよ
- .env / SupabaseキーをGit管理するな
- リアルタイム同期機能を今回のスコープで実装するな（対面1端末想定、将来拡張）
- 参加人数を3人固定で実装するな。2〜5人程度を可変で扱え
- 性格診断やMBTI風の分類をプロダクトに復活させるな（旧版からの退化）

## ワークフロー
計画 → `feat/phase-X-Y-*` ブランチで実装 → テスト → コミット提案 → （ユーザが手動でコミット）→ develop へマージ（これもユーザが手動）

コミット提案時は必ず以下の形式でユーザに渡す:
1. 提案コミットメッセージ（複数コミットに分けるべきなら分割案も添える）
2. 対象ファイル一覧（`git add` するパス）

ブランチ戦略: `main`（本番、直接 push しない）/ `develop`（開発統合先）/ `feat/phase-X-Y-description`（タスク用、develop から生やす）。詳細は @docs/team-roles.md。

Codexレビューはデフォルトで実施しない。ユーザから依頼された時のみ `/codex-review` を走らせる。
ただし、大きめの設計判断や不安がある実装に当たったときは「Codexに見てもらいますか？」と提案してよい（実行判断はユーザ）。

## 判断基準
AI感のあるデフォルトデザインより、プロダクトらしい仕上がりを優先。
精度とスピードが衝突したら精度を優先（ハルシネーションは致命的）。
複雑な機能とシンプルな体験が衝突したらシンプル優先。

## ルール参照（実装前に必ず確認）
フロントエンド実装時: @.claude/rules/frontend-design.md
Flask API実装時: @.claude/rules/api-rules.md
LLM呼び出し実装時: @.claude/rules/llm-rules.md
テスト作成時: @.claude/rules/testing.md

## ドキュメント記述ルール
todo.md の各タスクはTDD形式（テスト→Red→Green→Refactor→検証）で書け。
lessons.md は「問題・原因・ルール」の3項目。2回目が来たら .claude/rules/ に昇格せよ。
Evidence Packの仕様は @docs/evidence-pack.md を正典とする。そこから外れた実装をするな。
データモデルの変更は @docs/data-model.md を必ず更新してから実装せよ。
