# Plan quality improvements (Phase 1.10 後段 polish)

**ステータス**: Phase 1 探索完了 + Phase 2 Codex review 1 反映済 (Blocker 2 / Major 3 / Minor 2 / OK 2)、実装着手準備完了
**ブランチ**: `feat/plan-quality-improvements`（develop から派生、1 ブランチ + 3 commit）
**スコープ**: 本番 Run 12 完全動作後の demo 観察で発覚した 3 課題を網羅的に塞ぐ
**想定時間**: 約 4 時間（実装 + test + 本番 Run 13 verify）
**OpenAI コスト**: 0（unit test のみ、本番 Run 13 で ~$0.05）

## Context

本番 Run 12 で `/api/plans/generate → 200 + /plan/[id]` 完全レンダリングを達成した直後、user が demo 内容を観察して以下 3 課題を指摘:

1. **DAY 1 / DAY 2 で同じ場所・食事処が重複採用** (例: 「箱根食堂」が day1_lunch と day2_lunch 両方)
2. **宿情報が pack に入らない** (`RAKUTEN_APPLICATION_ID` env 未設定で fail-soft skipped)
3. **移動手段指定なし** (全員車運転可とは限らない demo シナリオ、公共交通のみモードが欲しい)

提出までの 4 時間で 3 課題を 1 ブランチで網羅的に修正し、demo 完成度を最大化する。

## 真因と設計（Codex review 1 反映後）

### 課題 A: slot 跨ぎ place_id 重複防止（assembler + prompt）

**真因**: `apps/api/src/llm/assembly.py:196-337` の slot ループ内で各 slot 独立に place_id を決定、slot 跨ぎ uniqueness 制約皆無。既存 self-healing は opening_hours 不適合 / transit 不成立の局所制約のみ。

**設計**:
1. **assembler ([assembly.py:196-340])**: slot ループ内で `used_place_ids: set[str]` を accumulate
2. 各 slot で LLM pick が `used_place_ids` に含まれていたら swap helper を呼ぶ
3. **`_find_eligible_alternate_for_slot()` (line 529) と `_find_alternate_place()` (line 598) の両方に `exclude_place_ids: set[str]` 引数を追加** (Codex Major 1: transit 代替経路でも再重複を防ぐ)
4. **最終 place_id に対する重複 invariant check** をループ末尾に入れて、絶対に重複が出ないことを保証 (Codex Major 1)
5. **prompt ([system.md])**: 既存「絶対ルール 7 項目」に**第 8 項として独立ルール**で「同じ place_id を複数 slot に割当てない、同じ place への複数訪問禁止、assembler が swap するが初手で避けると retry 削減」を追加 (Codex Minor 1: 第 3 項の拡張ではなく独立ルール化が誤解されにくい)
6. **test ([test_llm_assembly.py:920~])**: 重複 swap test 3 件 (opening_hours OK + 重複 → swap、transit OK + 重複 → swap、3 つの slot で同 place 3 回指定 → swap 後の最終 invariant 確認)

### 課題 B: 楽天 lodging env 設定 (コード変更ゼロ)

`apps/api/src/evidence/lodging.py` は Phase 2.3 で実装済 / test PASS、本番 Render に env 未設定 → fail-soft で skipped。

**設計** (3 ファイルのみ):
1. `docs/setup-guide.md`: 楽天トラベル App ID 取得手順 + Render Dashboard env 設定手順を追記
2. `render.yaml`: env vars に `RAKUTEN_APPLICATION_ID` / `RAKUTEN_AFFILIATE_ID` を `sync: false` で追加 (Codex Minor 2: Blueprint 初回構築漏れ防止)
3. `.env.example`: 同 env を例として追加（既存に存在するか確認、なければ追加）

**user 手動作業**:
- https://webservice.rakuten.co.jp/ で App ID 取得（無料）
- Render Dashboard → routeful-api → Environment → 上 2 つの env 追加
- auto redeploy で次回 plan 生成時に lodging が pack に入る

### 課題 C: 移動手段指定 (form + shared-types + Pydantic + prompt + transit + session 伝播)

**真因**: 現状 `transit.ts` の fallback chain (TRANSIT → WALKING / DRIVING) が距離自動判定のみ、user 側で「公共交通のみ」を明示できない。

**Codex review 反映で軌道修正された設計** (`Plan` への保存はスコープ外):
1. **`shared-types`**: `TransportMode = "all_modes" | "public_transit_only"` 型追加 + `GeneratePlanRequest.transport_mode` (default "all_modes") + `QueryContext.transport_mode` (Pack 経由で prompt に届ける用)。**`Plan.transport_mode` は追加しない**（Codex Blocker 2: DB / RPC 列追加は別スコープ、4 時間枠オーバー）
2. **Pydantic ([apps/api/src/schemas/__init__.py])**: `GeneratePlanRequest` / `QueryContext` に同期。Plan は変更なし
3. **test_schema_parity**: 上 2 つの `EXPECTED_FIELDS` に `"transport_mode"` 追加
4. **form ([apps/web/src/app/plan/new/page.tsx])**: `TransportModeSelector.tsx` 新設 (ModeSelector の pattern 踏襲)、出発モード radio の直後に配置 (Codex Q5)
5. **planForm zod schema**: `transport_mode: z.enum(["all_modes", "public_transit_only"]).default("all_modes")`
6. **session 伝播 (Codex Blocker 1 反映)**: `apps/web/src/stores/generationSessionStore.ts` の type に `transport_mode: TransportMode` 追加、`/plan/new` page で submit 時に session に格納、`/plan/[id]/generating` page で `postPlanGenerate` 呼び出しに含める
7. **prompt ([apps/api/src/llm/prompt.py])**: `_build_mode_context_md` を**合成方式に変更** (Codex Major 2: 現状の「anchor/theme で早期 return」だと transport 指示が落ちる)。anchor/theme/transport を独立に MD 文字列を組み立て、`"\n\n".join(filter(None, [...]))` で合成
8. **transit.ts**: `fetchTransitMatrix(places, departureTime, options: { transportMode? })` 追加、`callDirectionsWithFallback` で `transportMode === "public_transit_only"` なら modes から DRIVING 除外 (`["TRANSIT", "WALKING"]`)
9. **徒歩時間上限 (Codex Major 3 反映)**: `parseDirectionsResult` 内で `requestedMode === "WALKING"` かつ `duration_min > 30` のとき **null を返して edge を drop**。これにより「徒歩 2 時間」が plan に組み込まれない
10. **test**: schema_parity / planForm / TransportModeSelector / prompt mode_context 合成 / transit fallback DRIVING 除外 / 徒歩 30 分上限 / generating page の transport_mode 伝播 各層

**default 安全 (Codex Q6)**: `getattr(..., "transport_mode", "all_modes")` 多用ではなく、Pydantic / zod schema の default で吸収。

## 変更ファイル一覧

### Commit A: assembler 重複排除 + prompt ルール

| ファイル | 変更 | 行数 |
|---|---|---|
| `apps/api/src/llm/assembly.py` | `_find_eligible_alternate_for_slot` / `_find_alternate_place` に `exclude_place_ids` 引数、slot ループに `used_place_ids` 管理 + 最終 invariant check | +50 |
| `apps/api/src/llm/prompts/v2.0.0/system.md` | 第 8 項 "place 重複禁止" 独立ルール追加 | +3 |
| `apps/api/tests/test_llm_assembly.py` | 重複 swap test 3 件追加 | +60 |

### Commit C: 移動手段指定

| ファイル | 変更 | 行数 |
|---|---|---|
| `packages/shared-types/src/index.ts` | `TransportMode` 型 + `GeneratePlanRequest.transport_mode` + `QueryContext.transport_mode` | +5 |
| `apps/api/src/schemas/__init__.py` | 上 2 モデルに同期 | +5 |
| `apps/api/tests/test_schema_parity.py` | `EXPECTED_FIELDS` 同期 | +2 |
| `apps/web/src/lib/schemas/planForm.ts` | zod schema に `transport_mode` 追加 | +2 |
| `apps/web/src/components/TransportModeSelector.tsx` | 新規（ModeSelector pattern） | +60 |
| `apps/web/src/components/TransportModeSelector.test.tsx` | 新規 | +40 |
| `apps/web/src/app/plan/new/page.tsx` | TransportModeSelector を出発モード直後に配置、submit で session 格納 | +15 |
| `apps/web/src/stores/generationSessionStore.ts` | session type に `transport_mode` 追加 | +2 |
| `apps/web/src/app/plan/[id]/generating/page.tsx` | `postPlanGenerate` に `transport_mode` 含める | +1 |
| `apps/api/src/llm/prompt.py` | `_build_mode_context_md` を合成方式に refactor + transport 分岐 | +20 |
| `apps/api/tests/test_llm_prompt.py` | mode_context 合成 + transport の test 4 件 | +50 |
| `apps/web/src/lib/transit.ts` | `fetchTransitMatrix` options に `transportMode`、`callDirectionsWithFallback` で DRIVING 除外、`parseDirectionsResult` で WALKING 30 分超 reject | +20 |
| `apps/web/src/lib/transit.test.ts` | transport_mode public / 徒歩 30 分上限の test 5 件 | +50 |

### Commit docs: 計画書 + B の env docs

| ファイル | 変更 | 行数 |
|---|---|---|
| `tasks/plans/2026-04-27-plan-quality-improvements.md` | 本計画書（次セッションで参照） | 新規 ~250 |
| `docs/setup-guide.md` | 楽天 App ID 取得 + Render env 設定手順 | +20 |
| `render.yaml` | `RAKUTEN_APPLICATION_ID` / `RAKUTEN_AFFILIATE_ID` を `sync: false` で追加 | +2 |
| `.env.example` | 上 2 env を例示 | +2（既存にあれば省略） |
| `tasks/lessons.md` / `tasks/todo.md` | 本セッション末の反映 | +30 |

## TDD 手順 (実装は次セッション)

### Step 1: A 重複防止 (assembler + prompt + test)

1. test 先行: `test_llm_assembly.py` に重複 swap test 3 件
2. 失敗確認 (Red)
3. `_find_eligible_alternate_for_slot` / `_find_alternate_place` に `exclude_place_ids: set[str]` 引数追加
4. assemble_plan loop に `used_place_ids` accumulate、slot pick 後に重複 check → swap
5. **最終 invariant check**: ループ末尾で `assert len(set(item.place_id for item in items)) == len(items)`
6. system.md に第 8 項追加
7. test PASS 確認
8. `pytest -m "not integration"` 全 PASS 確認

### Step 2: C 移動手段指定 (フロント + バック)

1. **3 点同期先行**: shared-types / Pydantic / test_schema_parity に `transport_mode` 追加
2. test 先行（zod / TransportModeSelector / prompt 合成 / transit）
3. 失敗確認 (Red)
4. **生成 path の伝播**:
   - planForm zod schema に追加
   - TransportModeSelector component 新設
   - page.tsx に配置 + session 格納
   - generationSessionStore type 拡張
   - generating/page.tsx で postPlanGenerate に渡す
5. **prompt**: `_build_mode_context_md` 合成方式に refactor + transport 分岐
6. **transit.ts**: options に `transportMode`、callDirectionsWithFallback で DRIVING 除外、parseDirectionsResult で WALKING 30 分上限 reject
7. test PASS 確認
8. `pnpm --filter web test` / `pnpm --filter web exec tsc --noEmit` / `pnpm --filter web build` 全 clean

### Step 3: B 楽天 env (docs + render.yaml)

1. `docs/setup-guide.md` に楽天 App ID 取得 + Render env 設定手順を追記
2. `render.yaml` に env 2 つ追加
3. `.env.example` 確認 / 追記
4. test 不要 (コード変更ゼロ)

### Step 4: Codex review 2 (実装後)

実装完了後、Codex に変更全体を review 依頼。Blocker / Major 0 を確認。

### Step 5: 本番 Run 13 verify (user 手動 push 後)

1. user 手動で commit + push
2. Render auto deploy 待ち (~2.5 min)
3. user 手動で Render Dashboard に楽天 env 設定 → 2 回目 redeploy
4. Playwright で `/plan/new` から本番 Run 13 を実行:
   - **デフォルト（all_modes）で submit** → DAY 1 / DAY 2 重複なし、宿情報あり、200 + 画面遷移
   - **transport_mode = public_transit_only で submit** → DRIVING edge 0、徒歩 30 分超なし、200 + 画面遷移

## リスク

### Risk 1: A の最終 invariant が assembler を破綻させる
- 重複が swap で解消されないケースで invariant が raise → 422 になる
- 対処: invariant 違反時は **logger.error で記録して item を drop**（assembler の fail-soft path に乗せる）。raise しない方針

### Risk 2: 公共交通モードで pack 内の遠距離 places が plan から落ちる
- 徒歩 30 分上限で reject されると、距離 > 2km の places が transit_matrix から消える
- LLM は transit 到達可能 place しか選べないので、結果的に近距離 places のみで plan が組まれる
- これは設計通り（user の「公共交通のみ」意図と整合）。demo シナリオで「車不可だと選べる場所が減る」のは正しい挙動

### Risk 3: session 伝播でタイミング race
- `/plan/new` submit → Zustand 格納 → `/plan/[id]/generating` で読み取り
- session 既存実装は同期、race なし

### Risk 4: 楽天 API quota / 障害
- fail-soft 実装済 (`apps/api/src/evidence/lodging.py`)、quota 超過や API 障害で skip しても plan 生成は成功
- 対処: 既存設計通り、追加対応不要

## Codex review 1 回目の反映状況

- ✅ **Blocker 1 (transport_mode が生成処理に届かない)**: session 伝播設計を §課題 C 第 6 項で追加、generationSessionStore + generating page の改修を明記
- ✅ **Blocker 2 (Plan.transport_mode が DB / RPC スコープ)**: `Plan` への保存をスコープ外に切る、`GeneratePlanRequest` / `QueryContext` のみで prompt 注入
- ✅ **Major 1 (exclude_place_ids 両関数 + 最終 invariant)**: §課題 A 第 3〜4 項で両方明記
- ✅ **Major 2 (prompt 合成方式)**: §課題 C 第 7 項で `_build_mode_context_md` を合成方式に refactor 明記
- ✅ **Major 3 (徒歩 30 分上限)**: §課題 C 第 9 項で parseDirectionsResult の WALKING duration > 30 reject 明記
- ✅ **Minor 1 (第 8 項独立ルール)**: §課題 A 第 5 項で第 3 項拡張ではなく独立化
- ✅ **Minor 2 (render.yaml にも楽天 env)**: §課題 B 第 2 項で render.yaml 更新明記
- ✅ **OK 1 (B コード変更ゼロ)**: 維持
- ✅ **OK 2 (prev_place_id で edge 存在担保)**: §課題 A 第 3 項で transit 到達可能性は既存 prev_place_id 引数で担保

## Codex review 2 回目（実装後）に確認してほしいポイント

1. A の最終 invariant が assembler の既存 fail-soft path と整合しているか
2. C の prompt mode_context_md 合成方式が anchor / theme / transport の組み合わせ全パターンで正しい順序で連結されるか
3. C の徒歩 30 分上限が境界値（30 分ちょうど / 31 分）で正しく動くか
4. session 伝播が page reload や戻る操作で破綻しないか
5. test カバレッジに抜けがないか（特に transport_mode = public_transit_only かつ anchor / theme 併用時）
6. その他 Blocker / Major / Minor

## 完了基準

- [ ] A: 重複 swap test 3 件 + 最終 invariant test PASS
- [ ] C: schema_parity / planForm / TransportModeSelector / prompt 合成 / transit DRIVING 除外 / 徒歩 30 分上限 / session 伝播 各層 test PASS
- [ ] 既存 test の regression なし（API 394 件 PASS / Web 151 件 PASS）
- [ ] tsc clean / build PASS
- [ ] Codex review 2 回目で Blocker 0
- [ ] secret プリフライト 0 hit
- [ ] commit + push（user 手動）→ Render dashboard で楽天 env 設定 → auto redeploy
- [ ] **本番 Run 13** で:
  - default モード → DAY 重複なし + 宿情報あり + 200 + `/plan/[id]` 完全 render
  - public_transit_only モード → DRIVING edge 0 + 徒歩 30 分超 edge 0 + 200 + `/plan/[id]` 完全 render

## 関連ファイル（Critical files to modify）

**A (重複防止)**:
- `apps/api/src/llm/assembly.py:196-337` (slot loop + 重複 check 注入)
- `apps/api/src/llm/assembly.py:529-595` (`_find_eligible_alternate_for_slot`)
- `apps/api/src/llm/assembly.py:598-653` (`_find_alternate_place`)
- `apps/api/src/llm/prompts/v2.0.0/system.md:8-21` (絶対ルールに第 8 項追加)
- `apps/api/tests/test_llm_assembly.py` (重複 swap test 3 件)

**C (移動手段)**:
- `packages/shared-types/src/index.ts:15-79` (`TransportMode` + `GeneratePlanRequest` + `QueryContext`)
- `apps/api/src/schemas/__init__.py:51-202` (Pydantic 同期)
- `apps/api/tests/test_schema_parity.py:40-67` (`EXPECTED_FIELDS`)
- `apps/web/src/lib/schemas/planForm.ts:1-124` (zod schema)
- `apps/web/src/components/ModeSelector.tsx:5-81` (参考)
- `apps/web/src/components/TransportModeSelector.tsx` (新規)
- `apps/web/src/app/plan/new/page.tsx:45-71, 410-458` (form 配置 + session 格納)
- `apps/web/src/stores/generationSessionStore.ts:13` (type 拡張)
- `apps/web/src/app/plan/[id]/generating/page.tsx:104` (postPlanGenerate)
- `apps/api/src/llm/prompt.py:120-244` (`_build_mode_context_md` 合成方式)
- `apps/web/src/lib/transit.ts:304-466` (`parseDirectionsResult` + `callDirectionsWithFallback`)

**B (楽天 env)**:
- `apps/api/src/evidence/lodging.py:54` (既存実装、変更なし)
- `apps/api/src/evidence/builder.py:503` (既存組み込み、変更なし)
- `docs/setup-guide.md:157` (env 設定手順追記)
- `render.yaml:29` (env 追加)
- `.env.example:40` (例示追加)

## Verification

実装完了後の検証手順:

```bash
# Step 1: API
cd apps/api && .venv/bin/pytest -m "not integration" -q
# 期待: 394 PASS + 新規 ~10 件 = 404 PASS / 既知 env 依存 2 件 fail (無関係)

# Step 2: Web
cd /Users/milktea/大学/hackathon/hackathon_2026-04-13
pnpm --filter web test
pnpm --filter web exec tsc --noEmit
pnpm --filter web build
# 期待: 151 PASS + 新規 ~12 件 = 163 PASS / 既知 6 件 fail (無関係) / tsc clean / build PASS

# Step 3: secret preflight
git diff -- apps/ tasks/ docs/ render.yaml | rg -n -e 'AIzaSy[A-Za-z0-9_-]{30,}' -e 'sk-[A-Za-z0-9]{20,}' -e 'eyJ[A-Za-z0-9_]{8,}\.eyJ[A-Za-z0-9_]{8,}' -e 'service_role' -e 'GOOGLE_MAPS_API_KEY=' -e 'OPENAI_API_KEY=' -e 'SUPABASE_SERVICE_ROLE_KEY=' -e 'RAKUTEN_APPLICATION_ID=[a-zA-Z0-9]'
# 期待: 0 hit (env 変数名のみ参照、値はコミットしない)

# Step 4: 本番 Run 13 (user push 後)
# Playwright で /plan/new 提出 → 本番 URL で 2 シナリオ verify
# - default: DAY 重複なし + 宿あり + 200 + 画面 render
# - public_transit_only: DRIVING 0 + 徒歩 30 分超 0 + 200 + 画面 render
```
