# Phase 2.2: 予算配分の制約化

**ステータス**: codex review 1 回目 完了 → Blocker 0 / Major 3 / Minor 3 / OK 5 を反映済（実装着手準備完了）
**ブランチ**: `feat/budget-constraint`
**スコープ**: prompt v2.0.0 に `budget_context_md` placeholder を追加、`mode_context_md` と同じパターン
**想定 LOC**: +50（実装 ~20 / test ~30、validator / assembly / フロント変更なし）
**想定時間**: 1〜2 時間
**OpenAI コスト**: 0（unit test で完結）。手動 verify は ~$0.30（5 run × 配分極端パターン）

## 1. 目的（demo インパクト）

Routeful の希望入力画面には予算配分スライダー（宿泊 / 食事 / 観光 / 交通の 4 軸）がある。ユーザは例えば「宿泊にもっと使いたい」と思ってスライダーを動かす。**しかし現状、その配分は LLM プロンプトで「参考値」扱いで強制されていない**。Phase 2.2 でこれを **数値制約として明示**し、demo で「**配分を変えると生成結果が追従する**」を訴求する。

## 2. 現状（Explore agent 調査結果より要約）

| レイヤ | 現状 | Phase 2.2 で変更 |
|---|---|---|
| フロント `BudgetBreakdownSlider` | 4 軸合計 100% rebalance あり | 変更なし |
| API `/api/evidence/places` | `BudgetBreakdown` を受信、`breakdown_percent` + `breakdown_jpy` を計算済 | 変更なし |
| `EvidencePack.budget_constraints` | `total_jpy_per_person` / `breakdown_percent` / `breakdown_jpy` 揃ってる | 変更なし |
| prompt v2.0.0 user template | `{budget_constraints_json}` で JSON 数値注入「参考値」扱い | **`{budget_context_md}` を追加**して制約言語の Markdown を注入 |
| LLM | 数値のみ参照、強制力なし | 「宿泊は予算の 40%（¥12,000）以内に収めよ。超過は validator で reject」を見て遵守する圧力 |
| validator `_check_budget` | カテゴリ別 breakdown チェック既に実装、`BUDGET_EXCEEDED` issue 出力、retry に inject 済 | 変更なし（既に通る） |
| assembly cost_jpy 決定 | `price_level → jpy` マップで決定論 | 変更なし |

**Phase 2.1 の `mode_context_md` パターン**を踏襲するのが最小変更。

## 3. 設計

### `_build_budget_context_md(pack: EvidencePack) -> str`

`apps/api/src/llm/prompt.py` に新規追加。

**入力**: `pack.budget_constraints.breakdown_percent` + `breakdown_jpy` + `total_jpy_per_person`

**出力例**（auto モードで予算 ¥30,000 / 配分 40/30/20/10 の場合）:

```markdown
## 予算配分の絶対制約

参加者 1 人あたり総予算 ¥30,000 を、以下の配分（カテゴリ別上限）に収めること。
**超過は validator で reject され、retry の対象**となるため遵守必須。

- **宿泊**: 予算の 40%（¥12,000 以内）
- **食事**: 予算の 30%（¥9,000 以内）
- **観光**: 予算の 20%（¥6,000 以内）
- **交通**: 予算の 10%（¥3,000 以内）

注: 上記は category 合計の上限。各 PlanItem の cost_jpy 自体はサーバが price_level から決定論的に埋めるが、**slot 配分（何回 meal を入れるか / どの price_level の lodging を選ぶか）でこの上限を守れる構成にせよ**。
```

**意図**:
- 「絶対制約」という強い言葉で system.md の他のルール（「places の place_id を必ず使え」等）と同じトーンに
- **¥** + 円整形で具体的な金額を見せる（LLM は % だけより金額の方が attention 高い）
- **validator で reject** を明示して LLM の self-healing を促進
- **slot 配分で守れと指示**: cost_jpy はサーバ決定論だが、「lodging slot を 2 回入れる」「price_level=4 の meal を入れる」と当然超過する → LLM の slot/place 選定段階で配慮させる
- 数値表記は「上限目標（validator は +5% 許容）」と書く（Codex Minor 3 反映、`BUDGET_TOLERANCE_RATIO=0.05` の事実と整合）

### user_template.md の編集

`apps/api/src/llm/prompts/v2.0.0/user_template.md` に `{budget_context_md}` プレースホルダを追加。位置は **`{mode_context_md}` の直後**（Codex Minor 1 反映、JSON 直後より attention 高い位置を選ぶ）。

**同時に `{budget_constraints_json}` 直前の見出し「予算目安（参考値、実際の cost はサーバが決定する）」を「予算目安（カテゴリ上限は次の絶対制約節を参照）」に書き換える**（Codex Major 1 反映、「参考値」と「絶対制約」の文言衝突を解消）。

### `build_user_prompt` の編集

`prompt.py` の `build_user_prompt()` で `budget_context_md = _build_budget_context_md(pack)` を呼び、template に format 済引数として渡す。

## 4. 変更ファイル一覧

| ファイル | 変更内容 | 行数 |
|---|---|---|
| `apps/api/src/llm/prompt.py` | `_build_budget_context_md()` 関数追加（~25 行）+ `build_user_prompt()` 内で format 引数を追加（1 行） | +26 |
| `apps/api/src/llm/prompts/v2.0.0/user_template.md` | `{budget_context_md}` プレースホルダを `{budget_constraints_json}` の直後に追加 | +1〜3 |
| `apps/api/tests/test_llm_prompt.py` | budget context 注入の test 4〜5 件 | ~30 |

**型変更なし**、API 変更なし、validator 変更なし、フロント変更なし、3 点同期不要。

## 5. TDD 手順

### Step 1: `_build_budget_context_md` の単体テスト（先 → 実装）

| ケース | 入力 | 期待出力 |
|---|---|---|
| 標準配分 (40/30/20/10) | total=30000, percent={40,30,20,10} | 4 行のリスト、各カテゴリに「N%（¥X,XXX 以内）」が含まれる |
| 偏った配分 (宿泊 80%) | total=50000, percent={80,10,5,5} | 「宿泊: 予算の 80%（¥40,000 以内）」が含まれる |
| 0% カテゴリ | total=30000, percent={50,50,0,0} | 観光 / 交通 が「0%（¥0 以内）」表記、それでも 4 行出る（不在ではなく 0 と明示） |
| 端数の整数化 | total=10000, percent={33,33,17,17} | 整数 ¥3,300 / ¥3,300 / ¥1,700 / ¥1,700 で 3 桁区切り |
| 「絶対制約」「validator で reject」が文中に含まれる | 任意 | テンプレ文言の存在を assert |

### Step 2: `build_user_prompt` の統合テスト

| ケース | 期待 |
|---|---|
| auto モード | output に `## 予算配分の絶対制約` + `{budget_context_md}` が展開された Markdown が含まれる |
| anchor モード | mode_context_md と budget_context_md が両方含まれる（両立確認） |
| theme モード | 同上 |
| **挿入順検証** | `prompt.index("予算配分の絶対制約") > prompt.index("出発モード補足")`（Codex Minor 2 反映、`{mode_context_md}` 直後に来ることを assert） |
| プロンプト全体に `{budget_context_md}` のリテラル placeholder が残っていない | format 漏れを防ぐ regression test |
| **v1 prompt 非影響**（Codex Minor 2 反映） | `PROMPT_VERSION=v1.0.0` で build_user_prompt を呼ぶと「予算配分の絶対制約」が出力に含まれない |

### Step 3: 既存テストの後方互換確認

`test_llm_prompt.py` の既存 60 件が全て PASS することを確認。`{budget_context_md}` placeholder を未追加のまま template だけ変えると `KeyError` で落ちるので、両方を同時に編集。

### Step 4: 全体検証

- `pnpm --filter api test`（unit、ローカル integration 除く）→ 既存 + 新規が全件 PASS
- `pnpm --filter web test` → 影響なし、61〜130 件 PASS（フロント変更なし）

### Step 5（**必須化**、Codex Major 3 反映）: 手動 verify

- 最低 **2 run 必須**:
  - **Run A（通常配分）**: 40/30/20/10 で 1 run 走らせて `BUDGET_EXCEEDED` issue が前ベースライン（Phase 1.3e の `budget_exceeded=2/run`）と同等か減少するか観察
  - **Run B（偏り配分）**: 宿泊 80% / 食事 10% / 観光 5% / 交通 5% で 1 run 走らせて、lodging を 2 回入れる構成にならないか + 高 price_level の lodging が選ばれるか観察
- コスト ~$0.10〜0.15（2 run × OpenAI gpt-4.1、4-5 秒/run）
- 結果に応じて plan を update し、必要なら追加 retry / fallback を Phase 2.2.1 として切り出す

## 6. UI 耐久性 / 後方互換

- フロント変更なし、UI 耐久性チェック不要
- v1 prompt（`PROMPT_VERSION=v1.0.0`）は `_build_budget_context_md` を **呼ばない**ので影響なし。`build_user_prompt` 内で v2 のみ生成
- `BudgetConstraints` 型の互換性確認: 既存 `breakdown_percent` / `breakdown_jpy` を読むだけ、新フィールド追加なし
- `mode_context_md` と並列に 2 つの context が prompt に乗ることになるが、両方とも 200〜400 token 程度で総トークンは 12k 警告閾値を超えない見込み

## 7. リスク

### Risk: LLM が制約を無視して BUDGET_EXCEEDED を頻発させる
- 対処: validator は既にカテゴリ別 breakdown チェックを実装済（`_check_budget` line 458-487）、retry に issue が inject される。Phase 1.3e の retry 機構が機能する
- 緩和: `BUDGET_TOLERANCE_RATIO=0.05` で ±5% 許容（小数誤差 / price_level 端数）

### Risk: 偏った配分（宿泊 80%）で実現可能な構成がない
- 例: 1 泊予算 ¥12,000 で実現可能な lodging が pack に居なくて生成が失敗する
- **訂正（Codex Major 2 反映）**: assembly の self-healing は **opening_hours / 経路到達性** のみを最適化対象としており、**予算最適化はしない**（apps/api/src/llm/assembly.py の `_find_eligible_alternate_for_slot` / `_find_alternate_place` 周辺）。なので不可能配分は **retry 後に最終的に 422 / `BUDGET_EXCEEDED`** で停止する
- 対処: demo 時の入力は **事前に feasibility 確認した現実的配分**（公平 / やや偏り）に留める。極端な配分は demo 録画時に避ける
- 将来 Phase 2.2.1 として「budget-aware self-healing」を assembly に追加する余地あり（スコープ外）

### Risk: prompt token 増加
- `_build_budget_context_md` は ~250 token 想定（Markdown 1 セクション）
- 現状 prompt token ~12k → 12.25k で warning 閾値 +250。許容範囲
- 万が一 token を絞りたいなら、後で「validator で reject される」という強調文を削るオプションあり

### Codex review 1 回目の反映状況
- ✅ Major 1（文言衝突）: user_template.md の「予算目安（参考値、実際の cost はサーバが決定する）」見出しを「予算目安（カテゴリ上限は次の絶対制約節を参照）」に書き換え
- ✅ Major 2（assembly 事実誤認）: リスク §7 の「assembly self-healing で適合 price_level を探す」を「self-healing は opening_hours / 経路のみ、予算最適化はしない、不可能配分は 422 になる」に訂正
- ✅ Major 3（手動 verify 必須化）: Step 5 を optional → **必須**（Run A 通常 + Run B 偏り 80% 計 2 run）に変更、`BUDGET_EXCEEDED` 観察を完了基準に追加
- ✅ Minor 1（挿入位置）: `{mode_context_md}` の直後に変更（attention 高い位置）
- ✅ Minor 2（TDD 追加）: 「挿入順検証（prompt.index 比較）」と「v1 で予算絶対制約が出ない」を Step 2 に追加
- ✅ Minor 3（TOLERANCE 文言）: 「上限目標（validator は +5% 許容）」と表記、`BUDGET_TOLERANCE_RATIO=0.05` の維持を明記
- ✅ OK 5 件: トーン / 0% 表記 / スコープ / token / 後方互換 全部承認

### Codex review 2 回目（実装後）に確認してほしいポイント
1. 上記 Major / Minor の反映が漏れなく実装されているか
2. `_build_budget_context_md` の Markdown 出力が prompt 全体で意図通りの位置・順序に来ているか
3. 既存 `_build_mode_context_md` test との naming / 構造の一貫性
4. v1 / v2 の分岐が `build_user_prompt` 内で正しく切り替わっているか

## 8. 完了基準

- [ ] `_build_budget_context_md` 単体テスト 5 件 PASS
- [ ] `build_user_prompt` 統合テスト 6 件 PASS（auto/anchor/theme/挿入順/format-leak/v1 非影響）
- [ ] 既存 prompt test の regression なし
- [ ] `pnpm --filter api test` 全 unit PASS
- [ ] **手動 verify Run A（通常配分）+ Run B（宿泊 80% 偏り）の 2 run 必須実施**（Codex Major 3 反映）
  - Run A: `BUDGET_EXCEEDED` issue 数が前ベースライン（2/run）を超えない
  - Run B: lodging slot が 1 つに収まる、または高 price_level が選ばれる
- [ ] Codex review 2 回目で blocker 指摘なし
- [ ] commit 提案前に **secret プリフライト 0 hit** 確認（CLAUDE.md 新ルール、必須）
- [ ] commit 提案（user 手動 commit + push）

## 9. 参考

- 現状の prompt: `apps/api/src/llm/prompts/v2.0.0/{system,user_template}.md`
- 注入ロジック: `apps/api/src/llm/prompt.py:build_user_prompt`
- mode_context_md 実装: `apps/api/src/llm/prompt.py:_build_mode_context_md` (line 186-220)
- validator 既実装: `apps/api/src/llm/validator.py:_check_budget` (line 458-487)
- assembly cost マップ: `apps/api/src/llm/assembly.py:_PRICE_MAP` (line 74-106)
- 元タスク: `tasks/todo.md` の 2.2 節
