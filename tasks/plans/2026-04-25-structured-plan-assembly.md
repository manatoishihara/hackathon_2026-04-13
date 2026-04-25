# Structured Plan Assembly（LCaMO 論文応用）

**ステータス**: 設計 + 最小実装を Manato 単独セッションで進行中（2026-04-25 夜）。
ブランチ: `feat/structured-plan-assembly`

## 背景

Phase 1.3d 実装後、`verify_hallucination_rate.py` で hallucination 10〜20% が解消せず。
prompt tuning（token 圧縮 22,385→11,645、opening_hours 強調、transit trim）を試したが、
**制約違反の押し出し現象**で `outside_opening_hours` 12→5 に改善する一方で
`unknown_transit_edge` が 0→7 に新規噴出。根本は LLM が時刻 / transit / cost まで直接生成する設計。

LCaMO 論文（石原・中村 2026、「LLM を因果仮説生成に限定、数値は介入カタログが決める」）を
Routeful に類推適用する。`docs/evidence-pack.md` 冒頭の「LLM は意味空間、数値空間は専用モジュール」
方針と完全一致。

## 設計方針

LLM の役割を **「pack 内 place_id の順列選定 + slot カテゴリ指定 + 短い rationale」** のみに絞る。
`start_time` / `end_time` / `transit_ref` / `cost_jpy` / `cost_confidence` は **サーバ側の assembler
が決定論的に埋める**。

### LLM 出力（v2 schema）

```python
class LlmSlotAssignment:
    slot_id: str       # "day1_morning" など（下記 slot テンプレのキー）
    place_id: str      # pack.places に含まれる id 必須（LLM の選択可能集合は外部から提示）
    rationale: str     # 20〜60 文字、選定理由（参加者希望との接続）

class LlmGeneratedPlanV2:
    slots: list[LlmSlotAssignment]
```

`LlmPlanItem` のような時刻 / transit / cost フィールドは LLM には渡さない・吐かせない。

### Slot テンプレ（固定、日数に応じて展開）

| slot_id | start | end | item_type | 備考 |
|---|---|---|---|---|
| day{N}_morning | 09:00 | 11:30 | activity | 初日は出発地→最初のスポットの transit が前置 |
| day{N}_lunch | 12:00 | 13:30 | meal | |
| day{N}_afternoon | 14:00 | 16:30 | activity | |
| day{N}_dinner | 18:00 | 19:30 | meal | |
| day{N}_lodging | 19:30 | 翌 08:30 | lodging | 最終日は出さない |

日数は `pack.temporal_constraints.total_days` から導出。これらは JST 固定。
opening_hours に合わない場合、assembler が slot 内で **時刻シフト**（例: 09:30→10:00）するか、
別 place に差し替える（代替選定ロジック）。

### Assembler パイプライン

```
LlmGeneratedPlanV2.slots
    ↓ (1) 各 slot の place_id を pack.places から lookup、未ヒットなら Error（構造違反）
    ↓ (2) slot テンプレの時刻を initial とし、place.opening_hours に照合。
    ↓     不適合なら最早の内接時間帯に調整、どうしても無理なら次の候補 place に差し替え
    ↓ (3) slot[i-1] → slot[i] 間で transit_matrix を lookup。
    ↓     該当 edge があれば transit item を間に自動挿入。
    ↓     該当 edge 無ければ代替 place に差し替え（優先度: 同カテゴリ近接 → 同カテゴリ遠距離）
    ↓ (4) cost_jpy 決定:
    ↓     transit: edge.fare_jpy
    ↓     activity/meal/lodging: place.price_level → jpy マップ（後述）
    ↓ (5) LlmGeneratedPlan (v1 互換) に詰め直して返却
    ↓ (6) 既存 validator を通す（保険、理論的には全項目 OK）
```

### price_level → jpy マップ（介入カタログ）

| item_type | price_level=1 | =2 | =3 | =4 | null |
|---|---|---|---|---|---|
| meal | 1500 | 2500 | 4500 | 8000 | 2500（estimated） |
| activity | 1000 | 2000 | 3500 | 6000 | 1500（estimated） |
| lodging | 8000 | 14000 | 22000 | 35000 | 15000（estimated） |

`cost_confidence`: transit は `verified`、activity/meal/lodging で `price_level` が
non-null なら `estimated`、null なら `unknown`。

### 代替選定ロジック（対策 transit 不成立）

slot[i] の place_x から slot[i+1] の place_y に transit_matrix の edge が無い場合:
1. place_y と同カテゴリ（`category[0]` 基準）で、place_x からの edge がある places を列挙
2. そのうち rating 最高（tie なら元の place_y に最も近い）を採用
3. 見つからなければ place_x と place_y 両方を近接組に差し替え（連鎖的探索、1 回まで）
4. それでも無ければ Exception → LLM に別 slot 配分を要求（retry）

### LLM プロンプト（v2.0.0）

- system.md: 「数値は生成するな、slot_id と place_id のみ」を強調。
- user_template.md: `pack.places` を圧縮形式で提示（各 place に `available_slots` マーカー付き）、
  `slot_catalog`（上記テンプレ）、`participants_wishes`、`budget_tier`（予算 tier で pack を事前絞り込み済）を提示。

---

## 実装ファイル

| 新規 / 変更 | パス | 内容 |
|---|---|---|
| 新規 | `apps/api/src/llm/assembly.py` | slot テンプレ / assembler / 代替選定 / cost マップ |
| 変更 | `apps/api/src/llm/schema.py` | `LlmSlotAssignment` / `LlmGeneratedPlanV2` を追加、既存 v1 は温存 |
| 新規 | `apps/api/src/llm/prompts/v2.0.0/system.md` | 役割縮小の system prompt |
| 新規 | `apps/api/src/llm/prompts/v2.0.0/user_template.md` | v2 user template |
| 変更 | `apps/api/src/llm/prompt.py` | v2 分岐（build_user_prompt_v2）追加 |
| 変更 | `apps/api/src/llm/generator.py` | `PROMPT_VERSION=v2.0.0` で assembly 経路 |
| 新規 | `apps/api/tests/test_llm_assembly.py` | assembler unit tests |

## 非スコープ

- v1 → v2 の完全置き換え。v1 は develop に残し、`PROMPT_VERSION` env で切り替える A/B 構成
- UI 側の変更（assembler は v1 互換 `LlmGeneratedPlan` を返すので、フロントは変更不要）
- pack 事前絞り込み（予算 tier）は Phase 2 検討、今は pack 全 places を LLM に渡す

## 完了条件

- [x] `pytest tests/test_llm_assembly.py` 最低 5 件 PASS（**9 件 PASS 実績**）
- [x] `pytest -m "not integration"` 既存 234 件 + 新 9 件 = **243 件 PASS**（v1 regression なし）
- [x] `PROMPT_VERSION=v2.0.0 verify_hallucination_rate.py --runs 3` 実施:
      **hallucination=0/3 達成（主目的クリア）**、ただし `unknown_transit_edge=3/3` で
      全 run 失敗（assembler の代替選定 stub が直接の原因、LLM 由来ではない）
- [x] 本 plan ファイルと `tasks/lessons.md` に結果を記録

## 実装状況メモ（2026-04-25 夜）

- ブランチ: `feat/structured-plan-assembly`（develop から切替済み）
- 実装済みファイル:
  - `apps/api/src/llm/schema.py`: `LlmSlotAssignment` / `LlmGeneratedPlanV2` 追加、v1 温存
  - `apps/api/src/llm/assembly.py`: 新規（slot カタログ・assembler・cost マップ）
    - **2026-04-25 追加**: `_find_alternate_place` で代替選定ロジック実装（設計書 §「代替選定ロジック」step 1-2）。同 `category[0]` 一致 + `from_place_id` から transit edge が存在する候補を rating 降順で採用。連鎖探索（step 3）は LLM retry 経路で解消する方針で見送り
  - `apps/api/src/llm/prompts/v2.0.0/system.md` + `user_template.md`: 新規
  - `apps/api/src/llm/prompt.py`: `build_user_prompt` が v2 にも対応（slot_catalog_json 引数追加）
  - `apps/api/src/llm/generator.py`: `PROMPT_VERSION=v2.0.0` で `LlmGeneratedPlanV2` を受信、`assemble_plan()` 経由で v1 互換に変換、AssemblyError は validator issue 扱いで retry
  - `apps/api/tests/test_llm_assembly.py`: **12 件 PASS**（+3 件: 代替選定の成功 / rating 優先 / category 不一致で raise）
- 全体 unit 246 件 PASS（v1 regression なし）
- トークン計測: v2 prompt tokens = **11,866**（system 723 + user 11,143）。v1 改善版 11,645 とほぼ同等。主目的は token 削減ではなく「LLM 出力空間を狭めて制約違反を構造的に排除」
- 1 回目の動作確認 (`verify --runs 3`): hallucination=0/3 達成、ただし unknown_transit_edge=3/3（assembler の代替選定 stub が原因）
- 2 回目の動作確認 (`verify --runs 3`、代替選定第 1 弾 `category[0]` 厳密一致後): 依然 unknown_transit_edge=3/3。原因 2 点を特定:
  - LLM が連続 slot に同じ place_id を割当てる **自己ループ**（`from == to` で edge 探索、該当なし）
  - Google Places の細粒度 category（`yakiniku_restaurant` / `taiwanese_restaurant` / `locality` / `colloquial_area`）で `category[0]` 厳密一致だと代替候補が枯渇
- 代替選定第 2 弾（2026-04-25 夜、最新）:
  - `category[0]` 厳密一致 → **`target_place.category` と候補の `category` の共通集合が非空**（`restaurant` / `food` 等の generic ラベルでマッチ可能）
  - candidate 除外条件に `p.place_id == from_place_id` を追加（自己ループ回避）
  - unit test 14 件 PASS（+2: 緩和 category マッチ / 自己ループ回避）、全 248 件 PASS
- 3 回目の動作確認 (代替選定第 2 弾後): hallucination=0/3 / unknown_transit_edge=0/3 (構造解消)、新主因 = `transit_departure_mismatch=18` + `outside_opening_hours=6`
- 第 3 弾実装（同日夜）:
  - `_pick_departure_time(edge, start_dt)` 追加: `edge.candidate_departures` から start_dt 以降で最早を採用（全候補が前なら最遅 fallback、validator に弾かせる）
  - `_fit_to_opening_hours` の「30 分閾値」撤廃: 1 秒でも重なれば opening 内に寄せる
  - スクリプト `_build_transit_matrix` の `candidate_departures` を 1 → 10 個（08:00〜17:00）に拡充
  - unit test 16 件 PASS（+2 件）、全 250 件 PASS
- 4 回目の動作確認 (第 3 弾後): **hallucination=66.7% に悪化**（2/3）、原因は prompt token 12k → **14.6k 肥大化** で LLM の注意散漫 → 架空 place_id 再発。`unknown_transit_edge` / `departure_mismatch` は構造的に消えたが、prompt サイズと命中率のトレードオフを越えてしまった

## セッション終了時点の状況（2026-04-25 02:30 JST）

- **主目的「hallucination 構造的 0%」は run 1〜3 で達成済み**（LCaMO 思想の有効性は実証）
- ただし副次調整（candidate_departures 拡充）で hallucination が戻る制約違反の押し出し現象が再発
- **次セッション最初の一手**: candidate_departures を 10 → 3〜5 個に減らし、prompt token を 12k 以下に戻す。token と命中率のスイートスポット探索（5 → 3 → 1 で run 1 と同条件に近づける）
- 並行検討: prompt 軽量化（places の `category` を `category[0]` のみに、または除外）、LCaMO 論文の「介入カタログを各ラウンドで縮小」相当の段階制御
- **develop マージは未推奨**: 現状の `feat/structured-plan-assembly` は run 4 の悪化条件で残っているので、git diff の最終時点での hallucination 率は 66.7%。next session でスイートスポットを定めてから merge 提案する
