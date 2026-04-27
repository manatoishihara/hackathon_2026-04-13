# 次セッション再開プロンプト（2026-04-27 終了時点 → 次セッション）

このファイルの中身をそのまま新しい会話の冒頭に貼り付けて使ってください。

---

## 再開プロンプト本文（コピペ用）

```
Routeful プロジェクト（hackathon 2026-04-13）の作業継続。本番 Run 12 で
プラン生成は完全動作 (200 + /plan/[id] 完全レンダリング) しているが、
demo 観察で 3 つの polish 課題が発覚済み。前セッション（2026-04-27）末で
Phase 1 探索 + Codex review 1 反映済の実装計画書まで作ってある。

## 🎯 本セッションのゴール

`tasks/plans/2026-04-27-plan-quality-improvements.md` の計画書通り実装 →
Codex review 2 → 本番 Run 13 verify で demo 完成度を最大化する。
想定 4 時間で A + B + C を 1 ブランチ + 3 commits で完遂。

## 課題と設計（計画書から要約、詳細は plan 参照）

### A: slot 跨ぎ place_id 重複防止
本番 Run 12 で「箱根食堂」が day1_lunch と day2_lunch 両方に採用される現象。
Phase 1.3e assembler は各 slot 独立に place を選ぶ logic で slot 跨ぎ
uniqueness 制約皆無。

修正:
- `apps/api/src/llm/assembly.py:196-337` の slot ループに
  `used_place_ids: set[str]` accumulate + 重複検出 → swap
- `_find_eligible_alternate_for_slot` (line 529) と `_find_alternate_place`
  (line 598) の **両方** に `exclude_place_ids: set[str]` 引数追加
- ループ末尾で **最終 invariant check**（重複ゼロ確認、違反は logger.error +
  item drop で fail-soft）
- `apps/api/src/llm/prompts/v2.0.0/system.md` に第 8 項「同じ place_id を
  複数 slot に割当て禁止」を独立ルールで追加
- test_llm_assembly.py に重複 swap test 3 件

### B: 楽天 lodging env 設定（コード変更ゼロ）
`apps/api/src/evidence/lodging.py` は実装済 / test PASS だが Render に
`RAKUTEN_APPLICATION_ID` env 未設定で fail-soft skipped。

修正:
- `docs/setup-guide.md` に楽天 App ID 取得 + Render env 設定手順追記
- `render.yaml` に `RAKUTEN_APPLICATION_ID` / `RAKUTEN_AFFILIATE_ID` を
  `sync: false` で追加（Blueprint 初回構築漏れ防止）
- `.env.example` 確認 / 追記
- user 手動: https://webservice.rakuten.co.jp/ で App ID 取得 →
  Render Dashboard で env 設定 → auto redeploy

### C: 移動手段指定（form + shared-types + Pydantic + prompt + transit + session）
全員車運転可とは限らない demo シナリオで「公共交通のみ」モード指定が必要。

**重要な軌道修正（Codex review 1 反映）**:
- `Plan.transport_mode` への DB 保存は **スコープ外**（migration / RPC 列追加で
  4 時間枠オーバー）。`GeneratePlanRequest` / `QueryContext` のみで prompt 注入

修正:
- `packages/shared-types/src/index.ts`:
  `TransportMode = "all_modes" | "public_transit_only"` 型追加 +
  `GeneratePlanRequest.transport_mode` (default "all_modes") +
  `QueryContext.transport_mode`
- `apps/api/src/schemas/__init__.py`: 上 2 モデル同期（Plan は変更なし）
- `apps/api/tests/test_schema_parity.py`: EXPECTED_FIELDS 同期
- `apps/web/src/lib/schemas/planForm.ts`: zod schema に追加
- `apps/web/src/components/TransportModeSelector.tsx` 新設（ModeSelector
  pattern 踏襲）
- `apps/web/src/app/plan/new/page.tsx`: 出発モード radio 直後に配置 +
  submit で session 格納
- `apps/web/src/stores/generationSessionStore.ts`: session type に
  `transport_mode` 追加（**Codex Blocker 1**: 生成処理に届ける伝播経路必須）
- `apps/web/src/app/plan/[id]/generating/page.tsx`: `postPlanGenerate` に
  `transport_mode` 含める
- `apps/api/src/llm/prompt.py`: `_build_mode_context_md` を **合成方式に
  refactor**（Codex Major 2: 現状の anchor/theme 早期 return だと transport
  指示が落ちる）。anchor / theme / transport を独立 string + `\n\n` で連結
- `apps/web/src/lib/transit.ts`:
  - `fetchTransitMatrix(places, departureTime, options: { transportMode? })`
  - `callDirectionsWithFallback` で `transportMode === "public_transit_only"`
    なら DRIVING 除外 (`["TRANSIT", "WALKING"]`)
  - `parseDirectionsResult` で `requestedMode === "WALKING"` かつ
    `duration_min > 30` のとき null 返却で edge を drop（**Codex Major 3**:
    徒歩 2 時間 plan 防止）
- test 各層: schema_parity / planForm / TransportModeSelector / prompt 合成 /
  transit DRIVING 除外 / 徒歩 30 分上限 / session 伝播

## 進め方（前セッションパターン踏襲）

1. **計画書通読**: `tasks/plans/2026-04-27-plan-quality-improvements.md`
   を最後まで読み、§変更ファイル一覧 / TDD 手順を完全把握
2. **branch 切り替え**: user 手動で `feat/plan-quality-improvements` を
   develop から派生
3. **TDD 実装**: subagent に委任可能（前セッション同様）。Step 1 = A 重複防止、
   Step 2 = C 移動手段、Step 3 = B docs（test 不要）
4. **Codex review 2**: 実装後に変更全体を review 依頼、Blocker 0 確認
5. **secret プリフライト**: 0 hit 確認
6. **commit 提案**: 3 commit に分割（A / C / docs+lessons+todo）→ user 手動 push
7. **本番 Run 13 verify**: Vercel + Render auto deploy 後、Playwright で
   2 シナリオ確認:
   - default モード → DAY 重複なし + 宿情報あり + 200 + `/plan/[id]` 完全 render
   - `transport_mode = public_transit_only` モード → DRIVING edge 0 +
     徒歩 30 分超なし + 200 + `/plan/[id]` 完全 render

## 制約 / 守ってほしいこと

- CLAUDE.md / .claude/rules/ を必ず読んでから着手
- develop に直接コミットしない、必ず `feat/plan-quality-improvements` ブランチ
- git commit / push は user が手動でやる、Claude は提案だけ
- commit 提案前に必ず secret プリフライト（CLAUDE.md ルール）
- TDD 厳守: test 先行 → 失敗確認 → 最小実装 → 通る → refactor
- subagent は適材適所で活用 OK（Explore / general-purpose / codex で plan 実装 review）

## 軌道修正された重要な設計判断（Codex review 1 反映済）

絶対に踏襲すべき:

1. **Plan.transport_mode を DB に保存しない** — `GeneratePlanRequest` /
   `QueryContext` のみで prompt 注入（DB / RPC スコープ回避）
2. **transport_mode を session 経由で生成処理に伝播** —
   `generationSessionStore` 拡張 + generating page で
   `postPlanGenerate` に渡す
3. **`exclude_place_ids` を 2 関数両方に伝播 + 最終 invariant** —
   transit 代替経路でも再重複しない、最後に絶対重複ゼロ確認
4. **`_build_mode_context_md` を合成方式に refactor** —
   anchor / theme / transport の組み合わせで指示が落ちない
5. **徒歩 30 分上限で edge drop** — 「徒歩 2 時間」が plan に組み込まれない
6. **prompt に「place 重複禁止」を独立第 8 項として追加** —
   既存ルールの拡張ではなく独立化が誤解されにくい

## 副次的な未解決タスク（hackathon 提出に致命的ではない）

- `tasks/lessons.md` で 1 回目記録した教訓のうち、`.claude/rules/` 昇格候補:
  - 「外部経路 SDK は単一モード固定にせずフォールバック」(2 回目記録済)
  - 「commit 前 conflict marker grep」(1 回目記録済、2 回目で昇格)
  - 「component の data access は必ず optional chaining」(1 回目記録済)
  - 「Phase 跨ぎ contract drift」(2 回目記録済)
  - 「Plan の data shape 変更は DB / RPC スコープ連動」(本セッション 1 回目)
- Phase 1.7 / 1.8 / 1.9 の見た目仕上げ（メンバー C スコープ）
- Phase 2.4 手動編集 + 部分再提案（時間あれば）
- 食事クリック式 UX（提出後 Phase 2.x で plan 起案）

## 関連参照

- @CLAUDE.md
- @tasks/todo.md（Phase 1.10 進捗サマリ + 最優先タスク節）
- @tasks/lessons.md（直近の Run 11/12 学び + Phase 2 polish 計画策定の学び）
- @tasks/plans/2026-04-27-plan-quality-improvements.md
  （**最重要、まずこれを最後まで読んで**）
- @apps/api/src/llm/assembly.py（slot ループ + self-healing helper）
- @apps/web/src/lib/transit.ts（fallback chain + parseDirectionsResult）
- @apps/web/src/components/ModeSelector.tsx（TransportModeSelector の参考 pattern）

まずは plan を最後まで読んで現状把握 → Step 1 (A 重複防止) から TDD 実装で進めて。
```

---

## 補足（このファイル自体は次セッションの context に入らないので参考）

### 前セッション (2026-04-27) で完了したもの

| 項目 | 状態 | branch / commit |
|---|---|---|
| Phase 1.10 fix: Maps Directions travelMode 距離分岐フォールバック | ✅ develop merge + push 済 | `fix/transit-fallback-walking-driving` (ce3dabd) |
| Phase 1.10 後段 chore: Flask logging.basicConfig(INFO) | ✅ develop merge + push 済 | `chore/api-logging-config` (148f4be / 13ba685) |
| Phase 1.10 後段: 422 真因全塞ぎ（canonical 8 点 + retry guidance + previous_issues 累積化） | ✅ develop merge + push 済 | `fix/plan-generation-blockers` (6f1b025 / c7c343d / 1402778 / ddb0aa9) |
| Phase 1.10 後段 fix: EvidenceModal / MapView location undefined セーフガード | ✅ develop merge + push 済 | `fix/evidence-modal-undefined-location` (72b2c93 / 96e228b) |

### 前セッションで判明 + 解決した本番 Run の系譜

| Run | 状況 | 解消 |
|---|---|---|
| 8 (ローカル) | TRANSIT が観光地ペアで全 ZERO_RESULTS | distance-based fallback で解決 |
| 9 (本番) | Run 8 の本番版、transit fallback 動作確認 | logging.basicConfig で次の調査準備 |
| 10 (本番) | logging 反映後、422 の真因 4 attempts 全 breakdown 取得 | candidate_departures 1 件 + LLM hallucination の 2 真因確定 |
| 11 (本番) | 全塞ぎ fix 反映、200 + /plan/[id] 遷移成功、ただし React render error | EvidenceModal optional chaining で解決 |
| 12 (本番) | プラン閲覧画面まで完全動作確認 | demo 完成、観察で 3 polish 課題発覚 |

### 次セッション開始時の git 状態（想定）

- branch: develop（直前に user が `feat/plan-quality-improvements` を切る）
- working tree: clean（前セッション最後で全 commit + push 済）

### 環境変数（再開時に確認すべき）

- `apps/api/.env`: `GOOGLE_MAPS_API_KEY` / `OPENAI_API_KEY` /
  `NEXT_PUBLIC_SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY`
- `apps/web/.env.local`: `NEXT_PUBLIC_GOOGLE_MAPS_BROWSER_KEY` /
  `NEXT_PUBLIC_API_BASE_URL=http://localhost:5000` /
  `NEXT_PUBLIC_SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_ANON_KEY` /
  `NEXT_PUBLIC_MAPBOX_TOKEN`
- 本番 Render（user 作業）: `RAKUTEN_APPLICATION_ID` /
  `RAKUTEN_AFFILIATE_ID` を Phase B で設定する

### 想定実装時間内訳

- Step 1 (A): ~1 時間（assembler 改修 + test）
- Step 2 (C): ~2 時間（フロント + バック + 3 点同期 + 5 層 test）
- Step 3 (B): ~15 分（docs + render.yaml）
- Codex review 2 + 反映: ~30 分
- 本番 Run 13 verify (Playwright): ~30 分

合計: ~4 時間
