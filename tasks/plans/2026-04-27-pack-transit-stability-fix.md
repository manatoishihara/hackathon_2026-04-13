# Pack / Transit / LLM 安定化 fix (Phase 2 polish v3)

**ステータス**: **Codex review 1+2+3+4 全反映完了、Blocker 0 認定、実装着手可能**
- review 1: Critical 1 + High 4 + Medium 2 → 全反映
- review 2: Major 2 + Minor 1 → 全反映
- review 3: Major 1 + Minor 3 → 全反映
- review 4: **Blocker 0**、Major 1 (T7 empty-category) + Minor 2 のみ → 反映済
**ブランチ**: `fix/pack-transit-stability` (develop から派生、想定 4 commits)
**スコープ**: 本番 Run 13c (草津 4 日 / 80,000 円 / お任せモード) で観測された 422 失敗の根本原因 (A6) + Run 13d で出る可能性のある潜在原因の網羅的解消

## Context

### Run 13c で観測された Render Live tail の log (確定原因)

```
attempt 1 (gpt-4.1):  kind=unknown_transit_edge "japanese_restaurant 候補なし"
attempt 2 (gpt-4.1):  kind=unknown_place_id    "ChIJJCcG... 5文字頭 ChIJJ でハルシ"
attempt 3 (gpt-4.1):  kind=unknown_transit_edge 同パターン
attempt 4 (gpt-4.1-mini): kind=unknown_transit_edge category zoo
[WARNING] Duplicate place_id swap (Phase 2 polish A 重複防止が production で正常動作)
```

### 確定原因 2 種

#### A6 (主原因、3/4 attempts): transit_matrix coverage 不足
- 構造: Pack 12-15 places × `MAX_PAIRS=20` × `MAX_EDGE_DISTANCE_KM=10km` で **transit_matrix が疎**
- 重複防止 `exclude_place_ids` で後半 slot で `_find_alternate_place` の **(a) 距離 reachable + (b) category 共通 + (c) opening_hours OK + (d) used 除外** を全部満たす候補が **0 件**
- 細粒度 Google Places category (`japanese_restaurant`, `zoo` 等) で更に絞り込まれる

#### A1 (副次、1/4 attempts): LLM ハルシネーション
- gpt-4.1 が `ChIJJCcG...` 頭 5 文字 `ChIJJ` で出力 (本物は `ChIJ` 4 文字の 27 char)
- `prompt.py:_UNKNOWN_PLACE_ID_PATTERNS` の regex 2 個では「短縮形」を catch して prompt feedback できるが「LLM が同 pattern を再ハルシ」する確率を下げる予防対策が必要

### 副次問題: 楽天 applicationId UUID 誤投入
- log 出力: `applicationId=0415bc2d-b441-41ce-9447-d3413ce5c3f7`
- 楽天仕様: 19-20 桁数字 (例: `1024711987305213057`)
- 影響: lodging fail-soft で skip → 422 直接原因ではないが、lodging が pack に入れば slot 数が緩和され副次的に解消の助けになる可能性

### 仮説原因 (Run 13d で出る可能性、Explore agent 調査結果より)

| 優先度 | IssueKind | 発生条件 | 既存対策 | 残リスク |
|---|---|---|---|---|
| 高 | unknown_transit_edge | A6 そのもの | 部分的 (重複防止 / hard self-healing) | T1 で根本解消想定 |
| 高 | unknown_place_id | LLM ハルシ (case mismatch / 短縮形) | case-insensitive fallback / regex 2 種 | T2 強化必要 |
| 中 | outside_opening_hours | slot 営業外 / transit shift で close 超過 | hard self-healing で rescue | 現状 OK、要 monitor |
| 中 | item_type_category_mismatch | meal slot に museum 等 | validator catch + retry | 現状 OK |
| 中 | transit_departure_mismatch | departure_time ∉ candidate_departures | assembler raise | 現状 OK |
| 低 | budget_exceeded | high price_level 多数選定 | tolerance 5% | 現状 OK |
| 低 | overlapping_items | 時刻調整失敗 | transit shift で start_dt 後ろにずらす | 現状 OK |
| 低 | out_of_temporal_range | temporal_constraints 外 | validator catch | 現状 OK |
| 低 | anchor_missing | anchor swap で落ち | _check_anchors_present catch | 現状 OK |

## 修正方針 (T1〜T7、Codex review 1 反映済)

### T1 (HIGH、改訂): transit_matrix coverage 緩和 + フロントガード強化
**ファイル**: `apps/web/src/lib/transit.ts`、`apps/web/src/app/plan/[id]/generating/transit-guard.ts`、`apps/web/src/app/plan/[id]/generating/page.tsx`

#### T1-1: 定数緩和
- `DEFAULT_MAX_PAIRS = 20 → 40`
- `DEFAULT_DISTANCE_KM = 10 → 15`
- `DEFAULT_GLOBAL_DEADLINE_MS = 10_000 → 15_000`

#### T1-2 (Codex H2 + review 2 Major + review 3 Major 反映): coverage 不足を early throw (deadline 非依存、ratio + absolute floor 両方常時チェック)
**Codex 指摘 (review 1 H2)**: 現状 `shouldEarlyThrowOnTransit` は `succeeded === 0 && attempted > 0` のみ。低 coverage でも API に流れて A6 再発する。
**Codex 指摘 (review 2 Major)**: `coverage < 30%` 比率単独だと「attempted=5, succeeded=2 (40%)」のような少数バッチ通過する → **ratio + absolute floor** 併用必要。
**Codex 指摘 (review 3 Major)**: `deadlineReached` 条件内に閉じていると **deadline 未到達でも低 coverage を取り逃す**。例: `attempted=10, succeeded=2 (20%)` が deadline 前に確定したら通過してしまう。

修正案: `transit-guard.ts` の判定条件を **deadline 依存を捨て、絶対下限と比率下限を常時チェック**:
```ts
const MIN_SUCCEEDED_FOR_GENERATE = 10;       // 絶対下限: assembler が 4 日 18 slot を組める最低 edge 数
const MIN_COVERAGE_RATIO = 0.3;              // 比率下限

export function shouldEarlyThrowOnTransit(stats: FetchTransitStats): boolean {
  if (stats.attempted === 0) return false;   // pair 0 件 (places 不足 or 距離制約) で続行
  if (stats.succeeded === 0) return true;    // 全滅
  // deadline 関係なく常に下限チェック (Codex review 3 Major 反映)
  if (stats.succeeded < MIN_SUCCEEDED_FOR_GENERATE) return true;
  if (stats.succeeded / stats.attempted < MIN_COVERAGE_RATIO) return true;
  return false;
}
```

**効果**: T1-1 で完走しないケースでも、低 coverage (絶対数 OR 比率) を検知してフロント側で 422 を予防。`attempted=5, succeeded=2` も succeeded < 10 で early throw。user に「もう一度試す」CTA を出す。

**理屈**: assembler が 4 日 18 slot に対して transit edges 必要数は最低 10-15 (各 slot 間 1 edge 想定 + alternate 候補数本)。`MIN_SUCCEEDED_FOR_GENERATE=10` はこの下限値、`MIN_COVERAGE_RATIO=0.3` は補助指標。

**副作用**: 短い旅程 (1〜2 日 / 4-6 slot) で `attempted=8, succeeded=8 (100%)` のような小規模 success case でも throw する誤判定リスク。本実装では「短期間 plan は時間的に未対応」と割り切る (4 日 plan の安定化が最優先)。短期間対応は Phase 14 で別途検討。

**完走前提を捨てる根拠 (Codex H1)**:
- 現実装は pair ごとに 3 mode 逐次試行、worst-case `ceil(80/5) * 3 * 2s = 96s`。15s deadline でも部分取得で終わる
- ただし「TRANSIT 即成功」が大半 (per-mode は 1 modeで終わる) ため平均 latency は 15s 内に収まる想定
- 部分取得でも coverage 30% 以上あれば assembler は組める実績 (Run 12 で 200 達成)

### T2 (HIGH、改訂): LLM ハルシ対策
**ファイル**: `apps/api/src/llm/prompt.py`、`apps/api/src/llm/prompts/v2.0.0/system.md`

#### T2-1 (Codex Critical 1 反映): `_UNKNOWN_PLACE_ID_PATTERNS` regex 強化
**Codex 指摘**: 計画案 `r"ChIJ[A-Za-z0-9_\-]{20,30}"` は **キャプチャグループが無い**、`_extract_unknown_place_ids` は `match.group(1)` を前提のため `IndexError` で 500 化リスク。

修正案: キャプチャグループを明示
```python
_UNKNOWN_PLACE_ID_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"unknown place_id ['\"]([^'\"]+)['\"]"),
    re.compile(r"place_id=['\"]([^'\"]+)['\"]"),
    # 追加 (T2-1): Google Places ID pattern を explicit match
    # quote に囲まれていない裸 ID も catch (validator log や assembly error で出る)
    re.compile(r"(ChIJ[A-Za-z0-9_\-]{20,30})"),
]
```

#### T2-2 (Codex H3 反映): prompt v2 system.md
**Codex 指摘**: 「27 文字固定」の制約は現行コードと不整合 (Pack の place_id は固定長制約していない、28 文字 ID も実在)。有効 ID をモデルに否定させる矛盾を作る。

修正案: 固定長やめて「正確コピー」要求に変更。第 9 項として追加:
```markdown
9. **place_id は提示された `places` 配列内の文字列を 1 文字も変えずに正確にコピーせよ**。短縮、省略、推測、合成は禁止。
   - 例: `places[0].place_id = "ChIJN1t_tDeuEmsRUsoyG83frY4"` を使う時は、この 27 文字をそのまま転記する
   - LLM が自信を持って「短縮形なら通る」「末尾の `_xyz` は省略可能」のような判断をしないこと
```

**効果**: `ChIJJ` のような 5 文字頭ハルシを抑制、gpt-4.1 の「短縮判断」をガイドラインで縛る。

### T3 (一旦保留、Codex H4 反映): bucket quota 調整は実装誤認のため却下
**Codex 指摘**: 計画案 1 (lodging quota 1 + 楽天で補完) の前提「楽天 lodging で補完」は **既存実装で成立していない**。`lodging_options` は pack には入るが LLM prompt の `places` リストには未接続。

修正方針: 
- 案 1 (lodging quota 1): **却下** (副作用で逆に lodging slot 候補不足)
- 案 2 (`MAX_PLACES = 15 → 20` + token 圧縮): T1 + T2 で 422 解消するか Run 13d で確認後、効果不足なら別 fix で対応
- 本 plan では **T3 を保留**、T1 + T2 で十分な可能性を検証してから判断

### T4 (MEDIUM、強化): assembler + generator 候補枯渇 log
**ファイル**: `apps/api/src/llm/assembly.py`、`apps/api/src/llm/generator.py`

#### T4-1: assembler 側 (元の T4)
- `_find_alternate_place` (L700) と `_find_eligible_alternate_for_slot` (L624) で `return None` 前に warning log:
```python
logger.warning(
    "Alternate place exhausted: target=%s category=%s from=%s reachable=%d eligible=%d excluded=%d",
    target_place.place_id, target_place.category, from_place_id,
    len(reachable_ids), len(eligible_candidates), len(excluded),
)
```

#### T4-2 (Codex Medium 反映): generator 側 issue kind 集計
- `apps/api/src/llm/generator.py` で attempt 終了時に **issue kind 集計** を info log に追加:
```python
logger.info(
    "LLM attempt %d (model=%s) issue kind summary: %s",
    attempt_num, model,
    Counter(issue.kind.value for issue in validator_issues).most_common(5),
)
```

**効果**: 本番 Live tail で「どの kind が支配的か」を瞬時に把握、次の調整方向を即決定可能。

### T5 (LOW、維持): 楽天 applicationId 形式注意 docs
**ファイル**: `docs/setup-guide.md`
- 楽天 env 節に「applicationId は **19-20 桁数字** (UUID は不可)、webservice.rakuten.co.jp ダッシュボードの『アプリ ID』フィールド」を明示

### T6 (Codex Medium 1 反映、削除): retry guidance は既にほぼ実装済
**Codex 指摘**: `_build_retry_guidance_md` は既に `previous_issues` 累積化 + 「再使用禁止」を実装済 (`prompt.py:330, 346`)。効果上積みは限定的。

修正方針: **T6 を本 plan から削除**、T2-1 の regex 強化で十分なリーチ。

### T7 (新設、Codex Medium 2 + review 2 Major 反映): `_find_eligible_alternate_for_slot` tier3 の item_type 整合
**ファイル**: `apps/api/src/llm/assembly.py:_find_eligible_alternate_for_slot`

**Codex 指摘 (review 1 M2)**: tier3 (任意 eligible) は category 無視で選ぶため、`item_type_category_mismatch` の誘発余地。例: meal slot に tier3 で museum が swap される。

**Codex 指摘 (review 2 Major)**: 当初提案した独自 `_is_loosely_compatible` の category list が validator の `_MEAL_CATEGORIES` / `_LODGING_CATEGORIES` より狭く、正常候補を回帰で落とすリスク。`bakery / bar / meal_takeaway / meal_delivery / resort_hotel / hostel / inn / guest_house` 等が漏れる。

修正案: **validator の既存 helper `_categories_indicate_meal` / `_categories_indicate_lodging` を再利用**。

```python
# apps/api/src/llm/assembly.py の冒頭で import
from .validator import _categories_indicate_meal, _categories_indicate_lodging

# _find_eligible_alternate_for_slot の tier 3 を以下に変更:
def _is_item_type_compatible(item_type: str, place_categories: list[str]) -> bool:
    """slot.item_type に対し place の category が validator の整合性チェックを通るか。
    `validator._check_item_type_category_consistency` と同じ判定で、tier3 fallback での
    item_type_category_mismatch 誘発を防ぐ。

    Codex review 4 Major: validator 本体は空 category を **skip (許容)** するため、
    本 helper も同じく空なら True を返して完全一致。さもなくば tier3 候補が不要に減って
    NoFeasibleTransitError 増加するリスク。
    """
    if not place_categories:
        return True  # validator と一致: 空 category は判定 skip = 許容
    if item_type == "meal":
        return _categories_indicate_meal(place_categories)
    if item_type == "lodging":
        return _categories_indicate_lodging(place_categories)
    return True  # activity slot は category 制約なし (validator も activity はチェックしない)

# tier 3: 任意 eligible (ただし slot.item_type と category の整合を validator と同基準で確認)
tier3 = [p for p in candidates if _is_item_type_compatible(slot_meta["item_type"], p.category)]
if tier3:
    return min(tier3, key=lambda p: (-(p.rating or 0.0), p.place_id))
return None
```

**効果**:
- `item_type_category_mismatch` validator 違反を tier3 でも誘発しない (preventive fix)
- validator と同じ判定関数 (`_categories_indicate_meal` / `_categories_indicate_lodging`) を再利用するため、既存の `bakery / bar / meal_takeaway / meal_delivery / resort_hotel / hostel / inn / guest_house` 等の validator 認識 category を tier3 も全て候補に含める (回帰なし)
- 将来 validator の allowlist が更新された時に assembler tier3 も自動追従

## 検証戦略

### Phase 1: ローカル test
- `apps/web/src/lib/transit.test.ts`: `MAX_PAIRS=40` / `DISTANCE_KM=15` / `DEADLINE=15s` で fallback chain test の境界値を再確認
- `apps/web/src/app/plan/[id]/generating/transit-guard.test.ts`: T1-2 の coverage threshold (ratio + absolute floor) の境界値テスト 4 件追加
- `apps/api/tests/test_llm_assembly.py`: `_find_alternate_place` の log 追加が既存 test を壊さないか + T7 の tier3 item_type filter test (meal slot に museum 候補が swap されない)
- `apps/api/tests/test_llm_prompt.py`: T2-1 regex の境界値 (capture group 動作確認 + 既存 ID extraction が回帰しない)、T2-2 system.md の token 増加確認 (12k 警告閾値内)
- `apps/api/tests/test_llm_generator.py`: T4-2 の Counter most_common 出力 log 確認

### Phase 2: 本番 Run 13d (T1 + T2 deploy 後)
- 草津 4 日 / お任せ / 80,000 円 (Run 13c と同条件) → **200 期待**
- もし 422 残るなら Render Live tail で attempt 別 issue を再取得し、kind が変化したか観察:
  - unknown_transit_edge 消えた → T1 効いた
  - unknown_place_id 消えた → T2 効いた
  - 別 kind (outside_opening_hours / item_type_category_mismatch 等) 出現 → 仮説 B の中位 issue が顕在化、追加対策

### Phase 3: 本番 Run 13e (アンカー有り)
- 同フォーム + 漫画堂 + 湯畑アンカー → 200 期待
- アンカー有りで衝突するなら anchor + 重複防止の調整 (anchor 件数を 1 件 default にする等)

### Phase 4: 草津以外で安定性 verify
- 箱根 / 京都 / 東京で各 1 回 200 確認 (本番 デモシナリオ)
- 草津以外で 422 出たら本 plan 範囲外の地域固有問題

## ファイル変更一覧 (想定、Codex review 1 反映後)

### Commit A (T1): フロント transit + 低 coverage early throw
- `apps/web/src/lib/transit.ts` (定数 3 箇所)
- `apps/web/src/lib/transit.test.ts` (境界値 test 修正)
- `apps/web/src/app/plan/[id]/generating/transit-guard.ts` (`shouldEarlyThrowOnTransit` 拡張)
- `apps/web/src/app/plan/[id]/generating/transit-guard.test.ts` (低 coverage 検知 test 追加)
- `apps/web/src/app/plan/[id]/generating/page.tsx` (transit-guard 呼び出し箇所のメッセージ調整)

### Commit B (T2): LLM ハルシ対策
- `apps/api/src/llm/prompt.py` (`_UNKNOWN_PLACE_ID_PATTERNS` に capture group 付き regex 追加)
- `apps/api/src/llm/prompts/v2.0.0/system.md` (第 9 項「正確コピー」追加、固定長制約しない)
- `apps/api/tests/test_llm_prompt.py` (regex キャプチャグループ test、IndexError 起きないこと確認)

### Commit C (T4 + T7): 可視性 log + assembler item_type 整合
- `apps/api/src/llm/assembly.py` (`_find_alternate_place` / `_find_eligible_alternate_for_slot` 候補枯渇 log + tier3 item_type filter)
- `apps/api/src/llm/generator.py` (attempt 終了時の issue kind 集計 log)
- `apps/api/tests/test_llm_assembly.py` (tier3 item_type filter test 追加)
- `apps/api/tests/test_llm_generator.py` (集計 log が既存 test 壊さない)

### Commit D (T5): docs
- `docs/setup-guide.md` (楽天 ID 形式注意)

### 削除/保留した修正
- ~~T3 (bucket quota 調整)~~: Codex H4 で却下、T1 + T2 で 422 解消するか Run 13d 後に判断
- ~~T6 (retry guidance 強化)~~: Codex M1 で既実装認識、効果上積み限定で削除

## リスク

### Risk 1: T1 で deadline 10s → 15s でフロントの体感増加
- 現状 selectPairs ~5s + Maps SDK ロード ~1s で生成中画面遷移まで 6s
- 15s に伸ばすと「飛行機演出」5 ステップ進行が遅く見える
- 対処: Phase 1 verify で実際の transit fetch 時間を計測、deadline 余裕は保ちつつ実時間は ~10s 以内目標

### Risk 2: T2-2 の system.md 追加で token 増加
- ~50 token 追加程度、無視できる
- ただし LLM が「制約多すぎ」で本来の plan 構築品質が下がる可能性は低くないので、A/B 必要なら polish 後

### Risk 3: T1 で都市部 (東京 / 京都) の MAX_PAIRS 倍増
- Codex review 2: directed 80 pair で API call 増、コスト/レイテンシ要モニタ
- 対処: T4-1 / T4-2 ログで本番の attempt latency を観察、過剰なら都市/地方分岐を Phase 14 で検討

### Risk 4: モグラ叩きの再発
- T1+T2+T4+T7 全部 fix しても、草津特有の地理 / 営業時間で別 kind が出るかも
- Codex review 2 指摘: `budget_exceeded` と一部 `outside_opening_hours` は本 fix だけでは残り得る
- 対処: T4 (log 可視化) で本番の挙動を観察し、必要に応じて Phase 13e/13f で追加 fix
- ハッカソン提出は **「観測された 2 種 (A1+A6) を解消」をゴール** とし、未観測リスクは時間制約で許容

## Codex review 1 反映状況 (済、history)

(以下 Codex review 1 当時の整理。詳細最新は上記「review 1+2+3 反映完了」表参照)

| Codex 指摘 | 重要度 | 反映 |
|---|---|---|
| **C1**: T2-1 regex がキャプチャグループ欠如で `IndexError` → 500 | Critical | ✅ T2-1 で `(ChIJ[...])` capture group 明示 |
| **H1**: T1 の 15s deadline では完走無理 (worst-case 72-96s) | High | ✅ T1 で「完走前提」捨て、T1-2 で coverage 監視導入 |
| **H2**: フロントガード `succeeded===0` だけでは A6 再発路残る | High | ✅ T1-2 で `MIN_SUCCEEDED_FOR_GENERATE` + `MIN_COVERAGE_RATIO` 導入 (review 3 で deadline 依存撤廃) |
| **H3**: T2-2 「27 文字固定」は危険 (現行は固定長制約していない) | High | ✅ T2-2 で「正確コピー」要求に変更、固定長やめ |
| **H4**: T3 案 1「楽天 lodging で補完」は実装で成立していない | High | ✅ T3 全体保留、T1 + T2 で十分か Run 13d で判断 |
| **M1**: T6 は既にほぼ実装済 | Medium | ✅ T6 削除 |
| **M2**: tier3 が category 無視 → `item_type_category_mismatch` 誘発余地 | Medium | ✅ T7 新設、tier3 に item_type filter (review 2 で validator helper 再利用に変更) |

## Codex review 1+2+3 反映完了 (再 review で Blocker 0 想定)

| Review | 指摘 | 反映内容 |
|---|---|---|
| 1 C1 | T2-1 regex capture group 欠如で `IndexError` | ✅ `(ChIJ[...])` capture group 明示 |
| 1 H1 | T1 deadline 15s で完走無理 | ✅ 「部分取得 + low coverage 検知」設計 |
| 1 H2 | フロントガード低 coverage 流出 | ✅ T1-2 で `MIN_SUCCEEDED_FOR_GENERATE` + `MIN_COVERAGE_RATIO` 導入 |
| 1 H3 | T2-2 「27 文字固定」は危険 | ✅ 「正確コピー」要求に変更 |
| 1 H4 | T3 「楽天 lodging で補完」前提が成立せず | ✅ T3 全体保留 |
| 1 M1 | T6 既実装、効果上積み限定 | ✅ T6 削除 |
| 1 M2 | tier3 が category 無視で `item_type_category_mismatch` 誘発 | ✅ T7 新設 |
| 2 Major1 | T7 独自 category list が validator より狭い | ✅ validator helper `_categories_indicate_meal` / `_categories_indicate_lodging` 再利用 |
| 2 Major2 | T1-2 coverage `< 30%` 単独は少数バッチ通過 | ✅ ratio + absolute floor 併用 |
| 2 Minor | 完了基準 / 次タスクに T3/T6 残骸 | ✅ 完了基準 + 次タスク刷新 |
| **3 Major** | **T1-2 deadline 依存判定が deadline 未到達低 coverage を取り逃す** | ✅ **deadline 依存を捨て常時チェック** |
| 3 Minor1 | 確認項目に旧設計名 `_is_loosely_compatible` 残 | ✅ 本セクションに置換 |
| 3 Minor2 | `coverage<30%` 単独表現残 | ✅ T1-2 の説明を deadline 非依存記述に統一 |
| 3 Minor3 | T3/T6 grep 残骸 | ✅ historical 履歴として明示 (削除根拠を逆参照しやすくするため意図的に残す) |

## 履歴的に残す削除/保留項目 (T3/T6)
- ~~T3 (bucket quota 調整)~~: Codex H4 で却下。実装で楽天 lodging が LLM prompt の places リストに未接続のため、案 1 (lodging quota 1 件) が逆効果。T1+T2 で 422 解消後に再検討
- ~~T6 (retry guidance 強化)~~: Codex M1 で既実装認識。`prompt.py:330, 346` で `previous_issues` 累積化 + 再使用禁止 既存、効果上積み限定で削除

リポジトリ root: `/Users/milktea/大学/hackathon/hackathon_2026-04-13`、Phase 2 polish v2 まで develop に push 済 (commits `0f80711 / 1564632 / 7be79a7`)。本 plan は v3 として `fix/pack-transit-stability` ブランチで実装する想定。

## 完了基準

- [ ] T1 + T2 + T4 + T5 + T7 実装完了、API 全 test PASS / Web 全 test PASS / tsc / build / secret 0 hit
- [ ] **Codex review 5 (実装後) で Blocker 0** (本 plan は計画段階で review 1+2+3+4 = 4 サイクル完了 / Blocker 0 認定済)
- [ ] commit + push (user 手動)
- [ ] **本番 Run 13d (草津 4 日 / お任せ / 80,000 円) で `/api/plans/generate → 200`**
- [ ] **本番 Run 13e (同条件 + 漫画堂 + 湯畑 アンカー) で 200**
- [ ] (理想) 箱根 + 京都 + 東京 各 1 回 200 で本番安定性確認

## 次セッション最初のタスク

1. 本 plan を読み込む
2. T1 (Commit A): フロント transit + transit-guard
3. T2 (Commit B): LLM ハルシ対策 (regex + system.md)
4. T4 + T7 (Commit C): assembler / generator 可視性 log + tier3 item_type filter
5. T5 (Commit D): docs/setup-guide.md 楽天 ID 形式注意
6. ローカル verify (API + Web test / tsc / build / secret) → Codex review 2 → 反映 → user push → 本番 Run 13d/13e verify
