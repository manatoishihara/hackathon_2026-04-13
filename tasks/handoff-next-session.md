# 次セッション再開プロンプト（2026-04-27 終了時点 → 次セッション）

このファイルの中身をそのまま新しい会話の冒頭に貼り付けて使ってください。

---

## 再開プロンプト本文（コピペ用）

```
Routeful プロジェクト（hackathon 2026-04-13）の作業継続。本番 Run 13c で
草津 4 日プランの 422 が再発 → Phase 2 polish v3 計画書を Codex review 4 サイクル
で Blocker 0 認定済。次セッションは plan 通り **実装に着手するだけ** の状態。

## 🎯 本セッションのゴール

`tasks/plans/2026-04-27-pack-transit-stability-fix.md` の T1+T2+T4+T5+T7
を 4 commits で実装 → Codex review 5 (実装後) → 反映 → user push →
**本番 Run 13d/13e で `/api/plans/generate → 200`** 達成で 422 根本解消。

提出までの想定時間: 4 commits ~30-40 分 + Codex review + verify ~20 分 + 本番 Run ~10 分
= **合計 ~60-70 分**。

## 前セッション (2026-04-27) で確定済みの背景

### Run 13b/13c (2026-04-27) で観測された 422 失敗

本番 Run 13c (草津 4 日 / 80,000 円 / お任せ / 楽天 env 投入後) で
`/api/plans/generate → 422` が再発。Render Live tail 4 attempts log:
- attempt 1 (gpt-4.1): kind=unknown_transit_edge "japanese_restaurant 候補枯渇"
- attempt 2 (gpt-4.1): kind=unknown_place_id "ChIJJCcG... 5文字頭 ChIJJ ハルシ"
- attempt 3 (gpt-4.1): kind=unknown_transit_edge 同パターン
- attempt 4 (gpt-4.1-mini): kind=unknown_transit_edge category=zoo
- 重複防止 swap 動作 log 2 件 (Phase 2 polish A 重複防止が production で正常動作の証拠)

### 確定した根本原因

- **A6 (主原因、3/4 attempts)**: Pack 12-15 places + transit_matrix
  `MAX_PAIRS=20` × `MAX_EDGE_DISTANCE_KM=10km` で疎、重複防止 exclude で
  `_find_alternate_place` の (a) 距離 reachable + (b) category 共通 +
  (c) opening_hours OK + (d) used 除外 全部満たす候補 0 件
- **A1 (副次、1/4 attempts)**: gpt-4.1 が `ChIJJ` 頭 5 文字でハルシネーション
- **副次**: 楽天 applicationId が UUID で誤投入（`0415bc2d-...`）。本物は
  19-20 桁数字。lodging fail-soft で skip だが正値で 422 解消の助けになる可能性

### 切り分け済の否定 (時間節約のため重要)

- A2 (anchor + 重複防止衝突): Run 13c (アンカー無し) で 422 → **否定**
- A4 (楽天 lodging 未投入): Run 13c (env 投入後) で 422 → **否定**

## 計画書の修正内容 (T1〜T7、Codex review 4 サイクル反映済)

詳細は `tasks/plans/2026-04-27-pack-transit-stability-fix.md` を必ず読み込むこと。
以下は要約のみ:

### T1 (Commit A): transit_matrix coverage 緩和 + フロントガード強化
- `apps/web/src/lib/transit.ts:31-37` 定数:
  - `DEFAULT_MAX_PAIRS = 20 → 40`
  - `DEFAULT_DISTANCE_KM = 10 → 15`
  - `DEFAULT_GLOBAL_DEADLINE_MS = 10_000 → 15_000`
- `apps/web/src/app/plan/[id]/generating/transit-guard.ts` で
  `shouldEarlyThrowOnTransit` に **deadline 非依存の常時下限チェック**:
  ```ts
  const MIN_SUCCEEDED_FOR_GENERATE = 10;
  const MIN_COVERAGE_RATIO = 0.3;

  if (stats.attempted === 0) return false;
  if (stats.succeeded === 0) return true;
  if (stats.succeeded < MIN_SUCCEEDED_FOR_GENERATE) return true;
  if (stats.succeeded / stats.attempted < MIN_COVERAGE_RATIO) return true;
  return false;
  ```
- test: `transit-guard.test.ts` に境界値テスト 4 件追加

### T2 (Commit B): LLM ハルシ対策
- T2-1: `apps/api/src/llm/prompt.py:_UNKNOWN_PLACE_ID_PATTERNS` に
  `re.compile(r"(ChIJ[A-Za-z0-9_\-]{20,30})")` 追加 (capture group 必須)
- T2-2: `apps/api/src/llm/prompts/v2.0.0/system.md` 第 9 項追加:
  > place_id は提示された `places` 配列内の文字列を 1 文字も変えずに正確に
  > コピーせよ。短縮、省略、推測、合成は禁止。
- test: regex capture group 動作確認 + token 増加 (12k 警告閾値内) 確認

### T4 + T7 (Commit C): 可視性 log + tier3 item_type filter
- T4-1: `apps/api/src/llm/assembly.py:_find_alternate_place` /
  `_find_eligible_alternate_for_slot` で `return None` 前に warning log
  (target/category/from/reachable/eligible/excluded counts)
- T4-2: `apps/api/src/llm/generator.py` で attempt 終了時に
  `Counter(issue.kind.value for issue in validator_issues).most_common(5)`
  の info log 追加
- T7: `_find_eligible_alternate_for_slot` の tier3 に item_type filter:
  ```python
  from .validator import _categories_indicate_meal, _categories_indicate_lodging

  def _is_item_type_compatible(item_type, place_categories):
      if not place_categories:
          return True  # validator と一致: 空 category は判定 skip = 許容 (Codex review 4 Major 反映)
      if item_type == "meal":
          return _categories_indicate_meal(place_categories)
      if item_type == "lodging":
          return _categories_indicate_lodging(place_categories)
      return True  # activity は制約なし

  tier3 = [p for p in candidates if _is_item_type_compatible(slot_meta["item_type"], p.category)]
  if tier3:
      return min(tier3, key=lambda p: (-(p.rating or 0.0), p.place_id))
  return None
  ```

### T5 (Commit D): docs/setup-guide.md 楽天 ID 形式注意
- 「applicationId は **19-20 桁数字** (UUID 不可)、webservice.rakuten.co.jp
  ダッシュボードの『アプリ ID』フィールド」を明示

### 削除/保留した修正 (Codex 指摘で却下、history)
- ~~T3 (bucket quota 調整)~~: 楽天 lodging が LLM prompt の places リスト未接続のため案 1 が逆効果
- ~~T6 (retry guidance 強化)~~: 既実装認識 (`prompt.py:330, 346`)、効果上積み限定

## 検証戦略

### Phase 1: ローカル test (実装中)
- API: `cd apps/api && .venv/bin/pytest -m "not integration" -q`
  期待: 既知 env 依存 2 件 (test_supabase) 以外全 PASS
- Web: `cd apps/web && pnpm exec tsc --noEmit && pnpm exec vitest run && pnpm exec next build`
  期待: 全部 clean

### Phase 2: Codex review 5 (実装後)
- 改訂版 plan + 実装差分を投げて Blocker 0 確認
- secret preflight (CLAUDE.md ルール、commit 提案前必須):
  ```bash
  git diff -- apps/ packages/ docs/ render.yaml | rg -n -e 'AIzaSy[A-Za-z0-9_-]{30,}' -e 'sk-[A-Za-z0-9]{20,}' -e 'eyJ[A-Za-z0-9_]{8,}\.eyJ[A-Za-z0-9_]{8,}' -e 'service_role' -e '<env>=<value>'
  ```

### Phase 3: 本番 Run 13d/13e (user push 後)
- **Run 13d (お任せモード)**: 草津 / 11/21〜11/24 / 80,000 円 / アンカー無し
  → `/api/plans/generate → 200` 期待 / `/plan/[id]` で完全レンダリング
- **Run 13e (アンカー有り)**: 同条件 + 漫画堂 + 草津温泉湯畑 アンカー
  → 200 期待
- **(理想) 草津以外 verify**: 箱根 / 京都 / 東京 各 1 回 200 確認
- もし 422 残るなら Render Live tail で attempt 別 issue 取得 → 別仮説 (B
  中位 issue: outside_opening_hours / item_type_category_mismatch /
  budget_exceeded 等) の preventive fix 検討

## 必須遵守事項 (CLAUDE.md より)

- **`git add` / `git commit` / `git merge` / `git push` を絶対に自分で
  実行するな**。コミット提案だけ user に渡す
- commit 提案前に **secret preflight 必須**: 0 hit 確認してから add
  コマンド提示
- **debug log / docs に API key / token / secret の生文字列を書くな**
- LLM に Evidence Pack なしで推論させるな
- 架空の場所・架空の時刻を出力するな (Places / Routes API で検証)

## 楽天 applicationId について (副次)

User の Render Dashboard 投入値 `0415bc2d-b441-41ce-9447-d3413ce5c3f7`
は UUID 形式で 楽天仕様外。本物は webservice.rakuten.co.jp ダッシュボードの
「アプリ ID」フィールド (19-20 桁数字、例: `1024711987305213057`)。

T5 で docs に注意書き追加するが、user に「ダッシュボードで『アプリ ID』
を再確認 → 19-20 桁数字なら Render env を置換 → redeploy」を依頼する手も。
ただし lodging は fail-soft で skip されるので 422 直接原因ではない。

## ブランチ戦略

- branch: `fix/pack-transit-stability` (develop から派生)
- 4 commits 構成 (Commit A → B → C → D)
- develop に push 済の Phase 2 polish v2 (commits 0f80711 / 1564632 /
  7be79a7) はそのまま base、本ブランチで上乗せ

## 期待する commit 提案フォーマット (CLAUDE.md より)

1. **secret プリフライト結果** (`git diff | rg <patterns>` の hit 件数)。
   0 hit でなければ commit 提案を停止
2. 提案コミットメッセージ
3. 対象ファイル一覧 (`git add` するパス)

## 進め方の確認

最初にこのプロンプトを読んだら、以下を実行:

1. `tasks/plans/2026-04-27-pack-transit-stability-fix.md` を Read で読み込む
2. T1 (Commit A) から実装着手
3. 各 commit 後にローカル verify (API pytest + Web tsc/vitest/build)
4. 全 commit 完了後に Codex review 5 (実装後)
5. Blocker 0 確認 → 4 commits の commit 提案を user に渡す
6. user push → 本番 Run 13d/13e verify
```

---

## 重要な参照ファイル (次セッションで読むべき順序)

1. **`tasks/plans/2026-04-27-pack-transit-stability-fix.md`** - 本セッションの計画書 (Codex review 4 サイクル Blocker 0 認定済)
2. **`tasks/lessons.md`** - 「2026-04-27: Phase 2 polish v3 計画書を Codex review 4 サイクルで Blocker 0 認定」エントリ + 「Render Live tail で Run 13c 422 の根本原因確定」エントリ
3. **`tasks/todo.md`** - Phase 2 polish v3 の進捗サマリ (本実装着手待ち状態)
4. **`CLAUDE.md`** - プロジェクト Do NOT / ワークフロー / ルール参照
5. **`.claude/rules/llm-rules.md`** - LLM 呼び出し時の鉄則
6. **`.claude/rules/api-rules.md`** - Flask API 実装時のルール
7. **`.claude/rules/data-model-sync.md`** - 3 点同期ルール (本タスクでは不要だが念のため)

## ファイル変更想定 (4 commits)

### Commit A (T1): フロント transit + transit-guard
- `apps/web/src/lib/transit.ts` (定数 3 箇所変更)
- `apps/web/src/lib/transit.test.ts` (境界値 test 修正)
- `apps/web/src/app/plan/[id]/generating/transit-guard.ts` (deadline 非依存判定 + 定数 2 個追加)
- `apps/web/src/app/plan/[id]/generating/transit-guard.test.ts` (境界値 test 4 件追加)

### Commit B (T2): LLM ハルシ対策
- `apps/api/src/llm/prompt.py` (`_UNKNOWN_PLACE_ID_PATTERNS` capture group 付き regex 追加)
- `apps/api/src/llm/prompts/v2.0.0/system.md` (第 9 項「正確コピー」追加)
- `apps/api/tests/test_llm_prompt.py` (regex capture group test、token 増加確認)

### Commit C (T4 + T7): assembler / generator log + tier3 item_type filter
- `apps/api/src/llm/assembly.py` (`_find_alternate_place` /
  `_find_eligible_alternate_for_slot` log + tier3 `_is_item_type_compatible`
  追加 + validator helper import)
- `apps/api/src/llm/generator.py` (attempt 終了時の Counter most_common 5 log)
- `apps/api/tests/test_llm_assembly.py` (tier3 item_type filter test、空
  category 許容 test 追加)
- `apps/api/tests/test_llm_generator.py` (Counter log が既存 test 壊さない確認)

### Commit D (T5): docs
- `docs/setup-guide.md` (楽天 ID 形式注意 1 段落)

## 完了基準

- [ ] T1 + T2 + T4 + T5 + T7 実装完了
- [ ] API 全 test PASS (既知 env 依存 2 件 fail のみ無関係) / Web 全 test
      PASS / tsc clean / build PASS
- [ ] secret プリフライト 0 hit
- [ ] **Codex review 5 (実装後) で Blocker 0**
- [ ] commit + push (user 手動)
- [ ] **本番 Run 13d (草津 4 日 / お任せ / 80,000 円) で
      `/api/plans/generate → 200`**
- [ ] **本番 Run 13e (同条件 + 漫画堂 + 湯畑 アンカー) で 200**
- [ ] (理想) 箱根 + 京都 + 東京 各 1 回 200 で本番安定性確認
