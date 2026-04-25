# Lessons Learned

失敗と解決策の一時メモ。**同じ失敗が 2 回起きたら `.claude/rules/` に昇格せよ**。
自動ロードされるルールになって初めて、失敗の繰り返しが止まる。

## フォーマット

```markdown
## YYYY-MM-DD: [簡潔なタイトル]
- 問題: [何が起きたか、具体的に]
- 原因: [なぜ起きたか、根本原因]
- ルール: [次回から守ること、機械的に判定できる形で]
- → 2回目が来たら .claude/rules/[該当]-rules.md に昇格
```

## 例（削除して実際の記録に置き換えよ）

```markdown
## 2026-04-25: LLM が架空の店舗を出力した
- 問題: 「箱根の和食ランチ」で存在しない店「鶴亀屋」を提案した
- 原因: Evidence Pack に候補を渡さず、LLMに自由生成させた
- ルール: LLM 呼び出し前に必ず Places API で候補を10件収集し、place_id リストを Evidence Pack に含める
- → 既に .claude/rules/llm-rules.md に記載、この失敗は二度と起こさない
```

---

## ログ

## 2026-04-21: Google Directions / Routes API は日本国内 transit を返さない
- 問題: Phase 1.2 で Routes API の TRANSIT モードを使って 新宿駅→箱根湯本駅 の経路を取ろうとしたが、HTTP 200 で空レスポンス (`{}` or `{"geocodingResults":{}}`) が返り続けた。代わりに Legacy Directions API を enable しても同じ（`ZERO_RESULTS`）。US ルート（SF→Mountain View）や DRIVE モードは正常動作
- 原因: Google Maps Platform の **Directions / Routes API tier は日本の公共交通データを持たない**。consumer 版 Google Maps（maps.google.com / Maps JavaScript API の DirectionsService）だけが Jorudan / Navitime と提携した日本 transit データを返す。2026-04 時点でも同じ制約
- ルール:
  - **日本 transit を取る場合、サーバー側 Directions/Routes API を使うな**。フロント側で Maps JS SDK DirectionsService を呼ぶ
  - サーバー側の DRIVE モードは動作するので、必要なら所要時間の概算として利用可（`apps/api/src/evidence/routes.py` の `compute_drive_estimate`）
  - 健全性チェック（`check_google_routes`）も TRANSIT ではなく DRIVE で書く（TRANSIT だと HTTP 200 で実質失敗なのに ok=True になる false positive）
- → 2 回目が来たら `.claude/rules/external-api-rules.md` に昇格（今は 1 回目）

## 2026-04-25: Phase 1.3d ハルシネーション検証で 10% 発生（目標 0% 未達）
- 問題: `apps/api/scripts/verify_hallucination_rate.py --runs 10` を 2 回実行（1 回目 transit_matrix 2 エッジ、2 回目 14km 以内全ペア ~160 エッジに拡張）し、いずれも `UNKNOWN_PLACE_ID` が 1 件発生（= hallucination rate 10%）。加えて non-hallucination の failure が 7〜8 件（主因は `outside_opening_hours` 12件、`overlapping_items` 6件、`budget_exceeded` 2件）で、最終成功は 1〜2/10
- 原因（推定）:
  - プロンプトのトークン数が 22,000+（目安 10,000 の 2 倍超）で LLM が制約を見落としやすい状態。`docs/evidence-pack.md` の「Evidence Pack 全体で 10,000 token 以内を目安」が守れていない
  - 箱根の観光スポットは夏場の定休日・営業時間帯が複雑で opening_hours の解釈に retry が効きにくい（gpt-4o-mini fallback でもズレが残る）
  - transit_matrix を 14km 以内で取れるだけ取ると edges が肥大化し、prompt の transit セクションが places より目立って opening_hours 情報が埋もれる
- ルール:
  - 10 回検証で hallucination > 0% の状態では Phase 1.3d は「完了」と見なさない
  - 次イテレーションの具体策:
    - (a) transit_matrix のサーバ側 trim（例: places ごと上位 3 近接に絞る）で prompt トークンを 10k 内に戻す
    - (b) `places` 側の送信フィールドを最小化（address / rating などは validator のみで使い、prompt には name + opening_hours + category のみ渡す検討）
    - (c) validator の `OUTSIDE_OPENING_HOURS` / `OVERLAPPING_ITEMS` issue を retry プロンプトに「該当 item のみ書き直せ」形式で inject して部分修正を狙う
    - (d) test fixture の region を「opening_hours が比較的単純な観光地」に変えてベースラインを切り分け
- → 2 回目が来たら `.claude/rules/llm-rules.md` の「プロンプトトークン管理」節に昇格（今は 1 回目）
- **追記（2026-04-25 夜、Step 1-2 着手）**:
  - 原因 (a) = transit_matrix 拡張が主因と判明。verify スクリプトが 14km 全ペア 160 edges を生成していたのが現実と乖離（フロント SDK 実測 ~40 edges）。これを「各 place から最近傍 5 edges、hard_cap=100」に変更 → 75 edges
  - 原因 (b) = prompt 内の places 冗長フィールド (`lat` / `lng` / `relevance_tags`) を `_place_for_llm` から除外。system prompt ルール 9（opening_hours 遵守）を「最頻出の違反」と強調
  - 効果: prompt token **22,385 → 11,645（-48%）**。evidence-pack.md 目安 10k には届かず（12k warning threshold は +350 で僅か超）。更なる削減は category / route_summary / candidate_departures などの絞り込みが余地として残る
- **追記（2026-04-25 夜、Step 3 再検証、`--runs 5` 実施）**:
  - **結果悪化**: success 0/5、hallucination 1/5 = **20%**（前回 10% から増加）。issue 内訳: `unknown_transit_edge=7`（新規大量発生）、`outside_opening_hours=5`（前回 12 から激減）、`budget_exceeded=1`、`unknown_place_id=1`
  - **洞察**: opening_hours 違反は system prompt 強調で激減（12→5）が、transit_matrix を 160→75 に攻めすぎたことで LLM が **pack に無い edge を hallucinate する新しい失敗モード**（`unknown_transit_edge`）を 7 件噴出させた。validator 的には「制約違反の押し出し」現象で、片方を締めると別が開く
  - **次イテレーション仮説（未実施）**:
    - (a') transit_matrix を最近傍 5 → 8 に戻す（75 → ~120 edges、prompt ~13k tokens 想定）
    - (b') system prompt に「transit_matrix に該当 edge がなければその経路自体を使わず、別 places を選び直す」と明示
    - 必要なら places を 15 → 10 に絞って prompt 安定化（ただし候補選択肢を狭めすぎるリスク）
  - **判断**: hallucination 0% は現状の prompt 設計では構造的に難しい可能性。Structured Output + validator retry の合わせ技でも LLM は制約の優先順位を勝手に決める。妥協線として「hallucination + unknown_transit_edge の合計 ≤ 10%」を MVP 合格条件に下げることを検討（ハッカソン提出優先の判断は Manato 次セッションで）

## 2026-04-25 深夜: LCaMO 論文（石原・中村 2026）からハルシネーション対策の構造的知見
- 問題: Routeful 現状は LLM が plan item の `start_time` / `end_time` / `place_id` / `transit_ref` / `cost_jpy` を **全部直接生成** しており、prompt tuning（token 圧縮 / ルール強調 / retry injection）だけでは validator 違反が押し出し現象で消えない（20% 悪化）
- LCaMO 論文の核心: **「LLM を因果仮説生成に限定し、数値は介入カタログが決める」** 3 フェーズ設計。ゲーム武器バランス最適化で GA-only の 50 世代 1/5 成功に対し、LCaMO は 30 ラウンドで 5/5 成功（2.1 倍効率）。数値直接生成を排除したことで制約逸脱を構造的に防いだ
- Routeful への直接類推（`docs/evidence-pack.md` 冒頭「LLM は意味空間、数値は専用モジュール」と完全一致の思想）:
  - LLM の役割を「**pack 内 place_id の順列選定** + 各 place の slot カテゴリ指定（morning_activity / lunch / ...）」に縮小
  - `start_time` / `end_time` は slot テンプレ（`day1_morning=09:00-11:00`）+ opening_hours 照合でサーバ決定論
  - `transit_ref` は隣接 slot 間で `transit_matrix` を lookup、該当なしは近接 place に自動差し替え（pack 外 edge を生成不能に）
  - `cost_jpy` は transit=fare_jpy、activity/meal=price_level→jpy マップで決定論
  - 事前介入: LLM に渡す pack を予算 tier で絞り込む（budget_exceeded をスコープ外に）
- 予測効果（論文からの類推）: `unknown_place_id` / `unknown_transit_edge` / `outside_opening_hours` / `overlapping_items` / `budget_exceeded` の **5 種の issue が全て構造的に 0 になる**。LLM が制約違反する「表現空間」自体を剥奪する設計
- 実装範囲: 大改修（600-900 行規模）。`schema.py` 再設計、slot テンプレ定義、transit 自動挿入関数、介入カタログ、prompt テンプレ全刷新
- ルール:
  - **prompt tuning で何往復しても hallucination が残る場合、LLM の役割を絞って数値を決定論に押し込む設計変更を検討せよ**
  - 制約違反の「押し出し現象」（片方締めると別が開く）が出たら、prompt 強化ではなく役割再配分で解く
- → 2 回目が来たら `.claude/rules/llm-rules.md` の「役割分担原則」節に昇格（今は 1 回目、設計指針として定着させる価値あり）
- **追記（2026-04-25 夜、Phase 1.3e 実装着手）**:
  - ブランチ `feat/structured-plan-assembly` を develop から切り、LCaMO 論文思想を反映した Structured Plan Assembly 最小版を実装:
    - `src/llm/schema.py`: `LlmSlotAssignment` / `LlmGeneratedPlanV2` 追加（v1 温存）
    - `src/llm/assembly.py`: slot カタログ（day{N}\_morning/lunch/afternoon/dinner/lodging）+ 時刻決定 + opening_hours 照合 + transit 自動挿入 + price_level→jpy カタログ
    - `src/llm/prompts/v2.0.0/`: LLM に「数値生成するな、slot 割当のみ」を明示する system + user template
    - `src/llm/generator.py`: `PROMPT_VERSION=v2.0.0` で `LlmGeneratedPlanV2` を受信 → `assemble_plan()` で v1 互換 `LlmGeneratedPlan` に変換 → 既存 validator を通す。AssemblyError は retry 対象
  - unit test 9 件 PASS（`tests/test_llm_assembly.py`）、全 243 件 PASS（v1 regression なし）
  - v2 prompt tokens: 11,866（v1 改善版 11,645 と同等）。主目的は token 削減ではなく LLM 出力空間の構造的制限
  - 動作確認 `PROMPT_VERSION=v2.0.0 verify --runs 3` 実施結果:
    - ✅ **hallucination rate = 0%**（LCaMO 思想の主目的達成、`unknown_place_id` が構造的に消滅）
    - ⚠️ success 0/3、other_failure 3/3。残る 100% の issue は **`unknown_transit_edge`**（連続 slot の place ペアが transit_matrix に存在しない case）
    - **原因**: LLM ではなく `assembly.py::assemble_plan` の代替選定ロジックが **stub 状態**（設計書では 4 ステップ記述、最小実装は `NoFeasibleTransitError` を即 raise）。LLM が validator 的に正しい出力を返しても、assembler が transit を解決できず失敗扱いしている
    - **次の一手**: `assembly.py` に代替選定（同カテゴリ近接 place への差し替え / 連鎖探索）を実装すれば、hallucination 0% を保ったまま全体成功率も劇的改善の見込み。実装量 60-100 行 + unit test 2-3 件追加
    - 所要時間: 平均 23.6 秒/run（v1 の 50-70 秒より速い、v2 prompt が slot 割当のみで軽いため）
  - **帰結**: Phase 1.3d で 3 回の prompt tuning で hallucination 率が下がらなかったのに対し、Phase 1.3e は 1 セッションで 0% 達成。**構造制約を決定論に押し込む設計の有効性を実証**（LCaMO 論文の 2.1 倍効率化と同じ方向性）。残る transit 欠落は assembler 機能不足で、これは実装可能な範囲
  - **追記（同日夜、代替選定実装）**: `assembly.py` に `_find_alternate_place`（同 `category[0]` 一致 + `from_place_id` から transit edge が存在する候補のうち rating 降順で採用）を追加。slot[i-1] → slot[i] の transit が欠落した場合、slot[i] の place を代替候補に差し替えて `_fit_to_opening_hours` と transit を再計算する。unit test 12 件 PASS（+3: 代替選定成功 / rating 優先 / category 不一致）、全 246 件 PASS。2 回目の `verify --runs 3` で unknown_transit_edge=3/3 再発、効果限定的
  - **追記（同日夜、代替選定第 2 弾）**: 2 回目失敗のログ分析から 2 つの課題を特定して改修:
    - 自己ループ: LLM が連続 slot に同じ place_id を割当てるケースで `from == to` edge 探索が失敗 → 代替候補から `p.place_id == from_place_id` を除外
    - category 厳密一致の狭さ: Google Places の細粒度 category（`yakiniku_restaurant` / `taiwanese_restaurant` / `locality` / `colloquial_area`）で `category[0]` 厳密一致だと候補枯渇 → `target_place.category` と候補 `category` の **共通集合が非空**ならマッチ（`restaurant` / `food` 等の generic ラベル経由で到達可能）
    - unit test 14 件 PASS（+2: 緩和 category マッチ / 自己ループ回避）、全 248 件 PASS
    - 3 回目の `verify --runs 3`: hallucination=0/3、`unknown_transit_edge` も 0/3（代替選定第 2 弾で構造的に解消）。新たに `transit_departure_mismatch=18`（assembler が prev_end_dt を departure_time に流用、candidate_departures と不一致）+ `outside_opening_hours=6`（重なり 30 分閾値が validator と整合しない）が表面化
  - **追記（同日夜、第 3 弾実装と悪化判明）**:
    - assembly に `_pick_departure_time(edge, start_dt)` を追加し、`edge.candidate_departures` から start_dt 以降で最早を採用（fallback は最遅）→ transit_departure_mismatch を構造的に消す
    - `_fit_to_opening_hours` の「重なり 30 分未満なら slot のまま返す」閾値を撤廃、1 秒でも重なれば opening 内に寄せる
    - verify スクリプトの `candidate_departures` を 1 個 → 10 個（08:00〜17:00）に拡充
    - unit test 16 件 PASS（+2: pick_departure_time の正常選択 / 全 candidate が前なら最遅 fallback）、全 250 件 PASS
    - 4 回目 verify --runs 3 結果: **hallucination 66.7% に悪化**（2/3）、加えて outside_opening_hours=2。原因は prompt token が 12k → **14.6k に肥大化**したことで LLM の注意散漫 → 架空 place_id を hallucinate する確率が上昇。candidate_departures × 75 edges = 約 +2.5k token のオーバーヘッド
  - **総括（2026-04-25 セッション終了時点）**:
    - **Phase 1.3e の主目的「hallucination 構造的 0%」は 1〜3 回目で 1 回達成**（success rate は別問題）。が、副次的調整で hallucination が戻る制約違反の押し出し現象を再演
    - **次セッションへの引き継ぎ**: `candidate_departures` を 10 → 3〜5 個に絞って prompt token を 12k 以下に戻すのが最初の一手。token と命中率のスイートスポット探索が必要
    - **Phase 1.3d の prompt tuning 限界（hallucination 10% 床）に対し Phase 1.3e は構造改修で下限を 0% に到達できる潜在能力を示した**。ただし運用安定化までは追加 1〜2 セッション必要
  - **追記（2026-04-25 13:50 JST、run 5、新セッション）**: `candidate_departures` を 10 → 3 (`["09:00", "12:00", "15:00"]`) に縮小:
    - prompt token = **12,547**（10 個時 14,600 から -2,053、目安 12k はわずか超過 +547）
    - `verify --runs 3`: success 1/3、**hallucination 1/3 = 33.3%**、other_failure 1/3（outside_opening_hours=2）
    - run 4 (66.7%) → run 5 (33.3%) で改善、ただし run 1〜3 の 0% には未到達
    - 観察: run 1 と run 2 の両方で **同じ架空 ID `ChIJJD-9JCXWjGWARzY11tDYsd_k`** が `day2_morning` slot に対して出力。LLM が特定 slot に対して特定 ID を引きやすい構造的バイアス（実在の Google Places ID 形式で、token 圧で抑えきれていない）
    - トークン-hallucination 線形相関: 11,866→0% / 12,547→33% / 14,600→67%。**12k threshold 内に収めれば 0% 復帰の可能性が高い**
    - **次の手の選択肢（user 判断、まだ未着手）**: (α) 候補 1 個 (`["09:00"]`) で 11,866 tok 再現 / (β) transit edge から `mode`/`route_summary`/`duration_min`/`fare_jpy`/`candidate_departures` を LLM 表現から全部除外し `{from, to}` のみにする（-2k 想定、LCaMO「介入カタログ縮小」と完全一致） / (γ) places.category を `category[0]` 単一値に縮小 (-0.5〜1k) / (δ) system prompt 強化（「不安なら欠損 slot にせよ」等）
    - 推奨優先: β が最筋（LLM の役割削減を更に徹底、10 candidates でも 12k 内に収まる）。次が α
  - **追記（2026-04-25 14:03 JST、run 6、β 実装）**: `prompt.py::build_user_prompt` の v2 分岐で transit edge を `{from, to}` 2 フィールドに縮小（`_edge_for_llm_v2` 追加）。v1 は full edge 維持（regression 防止）:
    - TDD で test 2 件先行（v2 strip / v1 keep）→ Red → Green。全 252 件 PASS
    - `verify --runs 3`: 12k threshold 警告なし、**hallucination 0/3 = 0.0% 復帰**（run 5 の 33% から構造的回復）、success 0/3、other_failure 3/3 (`outside_opening_hours=2` + `unknown_transit_edge=1`)
    - 中間 attempt の unknown_place_id は依然出るが retry で recover、最終 attempt は別 issue で fail。run 5 と異なり「同じ架空 ID を 4 attempt 連続出力」は消えた
    - **主目的「hallucination 構造的 0%」を 4 セッション目で再現、LCaMO 「介入カタログ縮小」が安定化フェーズでも有効**
    - 残課題: success rate を上げる作業（opening_hours 緩和 / 代替選定第 3 弾）。Phase 1.3e の hallucination ゴールとは別軸で user 判断
  - **追記（2026-04-25 14:50 JST、run 7、area exclude 実装）**: success rate 改善に向けて pack 診断スクリプト `apps/api/scripts/diagnose_pack.py` を新設し、現状 pack の構成を可視化。診断結果:
    - 15 places のうち 13 がレストラン、`箱根町` (`locality`) と `箱根温泉` (`colloquial_area`) が混入。後者は opening_hours=0 で plan item にできず、自己ループの origin になる（run 6 の `unknown_transit_edge=1` の真因）
    - `evidence/builder.py::_dedupe_and_cap` に area 系 primary category 除外を実装（`_AREA_PRIMARY_CATEGORIES`、`_is_area_place`）。除外対象: locality / sublocality* / colloquial_area / political / country / administrative_area_level_* / neighborhood / postal_code
    - TDD: tests/test_evidence_builder.py に test 2 件追加（area 除外 / secondary tag 残存）→ Red → Green。全 254 件 PASS
    - diagnose_pack.py で実 Places API 経由 pack を再構築 → `箱根町` / `箱根温泉` が消失、空いた枠に `seafood_restaurant` 等が追加
    - `verify --runs 3` 結果: success **1/3 (run 6 の 0/3 から +1 改善)**、**hallucination 1/3 (33.3%、run 6 の 0% から悪化)**、other_failure 1/3
    - hallucination の主因は **新パターン (case mismatch)**: gpt-4o-mini fallback が `ChIJFC0R0G-jGWARNMTt10zT2GY` を出力、pack 内の `ChIJFc0R0G-jGWARNMTt10zT2GY` (`HAKONE PICNIC`) と大文字小文字違い。area exclude が引き起こしたわけではない、3 サンプルの statistical noise + LLM の case 揺らぎ
    - **評価**: area exclude は **構造的に正しい**（不要 place 除去 + success 改善）が、3 runs では hallucination の揺らぎ範囲を超えない。確度を上げるなら runs 5〜10 で再評価、または case-insensitive matching を validator に入れる選択肢
    - 残課題（user 判断）: (a) verify --runs 5〜10 で hallucination 平均値を取り直す、(b) generator/validator に case-insensitive place_id matching を入れる、(c) outside_opening_hours / budget_exceeded の根本対応
  - **追記（2026-04-25 15:00 JST、run 8〜10、改修(ii)→(iii) 試行と統計的ノイズ知見）**:
    - **改修(ii) 実装**: `assembly.py::assemble_plan` で place_id の case-insensitive fallback（`places_by_id_lower`）。pack に厳密一致が無くても lower-case で一致すれば canonical id へ正規化、warning ログ。TDD で test 2 件（救済成功 / 真の hallucination は依然 raise）→ 全 256 件 PASS
    - **run 8（β + area exclude + case-insensitive、`--runs 5`）**: success **2/5 (40%)**、**hallucination 0/5 = 0% PASS**、other_failure 3/5（全部 outside_opening_hours=2）。Phase 1.3e の主目的（hallucination 0%）+ 副次（success ~40%）に到達
    - **改修(iii) 試行**: `generate_slot_catalog` に `start_date` 引数を追加して date / day_of_week を slot ごとに付与、system.md rule 5 で「定休日の place を選ぶな」と明示。TDD で test 2 件追加。**run 9 結果**: success **0/5**、**hallucination 1/5 = 20%** で run 8 から悪化
    - **revert 後再検証 run 10**: 同じ baseline (run 8 と同条件) で `--runs 5`: success **2/5**、hallucination **1/5 = 20%**。**run 8 の 0% は 5-run サンプリングの幸運**だったと判明
    - **重要な統計知見**: 5 runs では hallucination 率が **0〜20% range で揺らぐ**（独立 5 試行で各々 ~5% 内在 hallucination 率なら 0/5 と 1/5 は両方ありえる）。MVP 品質判断には runs 10〜20 が必要だが、コスト ($1〜$2) との trade-off で 5 runs ノイズを受容する判断もあり
    - **改修(iii) は実害なし**: rule 5 強化版 (run 9) と revert 版 (run 10) でほぼ同じ hallucination 率。token 微増分は LLM の許容範囲内、変更は意味的に正しいが 5-run サンプルでは効果検出できず
    - **revert 採用理由**: CLAUDE.md「Don't add features beyond what the task requires」に従い、hallucination 率を有意に変えない冗長コードは入れない。signature 拡張も含めて run 8 baseline へ完全復帰。case-insensitive のみ採用
    - **次の改修候補（user 判断、本セッションでは未実装）**:
      - (iv) per-slot tailored places: slot ごとに営業中の place のみを LLM に提示。大規模だが outside_opening_hours を構造的に消せる候補
      - (v) test fixture 変更: 月/火曜は定休日が多いので、平日でも比較的開いている水/木〜土曜の日付に変える
      - (vi) gpt-4o-mini fallback の挙動再評価: hallucination 残りの主因がここにある可能性
  - **追記（2026-04-25 15:30 JST、Codex レビュー受領 + Major fix）**:
    - Codex (gpt-5.2-codex 想定) に独立レビューを依頼。指摘:
      - **Major**: `assembly.py::places_by_id_lower` が lower 衝突時に黙って先勝ちで上書きし、誤 canonical 化し得る → 曖昧一致は fail-fast すべき
      - **Minor**: 曖昧一致のテスト未追加
      - **戦略**: 残改修順序は **B→A→C ではなく A→C→B** が効率的（A 単独で違反を構造的に消せるので最大効果）
      - **補足真因**: outside_opening_hours は H5 (pack 構成不良) だけでなく **fixed slot × 曜日/定休 ミスマッチ** も寄与
    - 対応: `places_by_id_lower` を `dict[str, PlacePoint | None]` 化、衝突は `None` マークで救済禁止 → `UnknownPlaceInSlotError` で raise。test 1 件追加（曖昧一致 raise）→ 全 257 件 PASS
  - **追記（2026-04-25 16:00 JST、改修(iv) per-slot tailored + hard self-healing 実装）**:
    - **段階 1**: `assembly.py` に `is_place_eligible_for_slot` / `compute_eligible_slot_ids_for_place` を追加。validator/`_fit_to_opening_hours` と整合した opening_hours 半開区間 overlap 判定（pure function、unit test 6 件）
    - **段階 2**: prompt v2 で各 place に `eligible_for_slots: [slot_id, ...]` を付与（informational hint）。system.md rule 5 を強化して LLM に確認を促す
    - **run 11**（5 runs、外乱含む）: hallucination 0/5 維持、`outside_opening_hours=1` まで激減。ただし transport=1, deadline=1 の OpenAI 外乱で 5 件中 2 件汚染
    - **run 12**（再検証 5 runs、外乱なし）: hallucination 0/5、`outside_opening_hours=9` で逆悪化 → **soft hint だけでは LLM が rule 5 を無視する**と判明
    - **段階 3**: `IneligiblePlaceForSlotError` 新設、assembler に hard self-healing 実装。LLM が ineligible pick した瞬間 `_find_eligible_alternate_for_slot` で同 category 優先の eligible 代替に自動差し替え（warning ログ）。validator/generator 経路も `OUTSIDE_OPENING_HOURS` issue にマップ。test 3 件追加 → 全 266 件 PASS
    - **run 13**（5 runs、self-healing あり）: hallucination 0/5、`outside_opening_hours=6` (run 12 比 -33%)、`budget_exceeded=2`。self-healing は 1 attempt あたり 3 件 swap 発火（warning 出力で確認）するが、**post-shift case** が残る
    - **新たに発覚した残課題（post-shift opening_hours mismatch）**: assembler の `_fit_to_opening_hours` で eligible に絞った後、transit_to_next の duration_min ぶん start_dt が後ろにシフトする。シフト後 start_dt が place の opening_hours close を超えると validator が `OUTSIDE_OPENING_HOURS` を出す。eligible_for_slots の判定は pre-shift なので捕捉できない
    - **次セッション持越し**: post-shift swap（transit 後の時刻で再度 eligibility 確認 → 不適合なら別 place に差し替え + transit 再 lookup）の実装、~30 分規模
    - **本セッション最終形態**: β + area exclude + case-insensitive (ambiguous fail-fast) + per-slot eligibility hint + hard self-healing。hallucination 0% 安定 / outside_opening_hours 1.2/run（run 12 比 -33%）。MVP として hallucination 主目的は達成、success rate 改善は post-shift fix で続く想定
  - **追記（2026-04-25 16:30 JST、API キーのモデルアクセス調査）**:
    - `client.models.list()` で確認、API キーで以下が利用可能:
      - GPT-4 系: gpt-4o, gpt-4o-mini, gpt-4.1, gpt-4.1-mini, gpt-4.1-nano（既存利用）
      - GPT-5 系: gpt-5, gpt-5-mini, gpt-5-nano, gpt-5-pro, **gpt-5-codex**
      - GPT-5.x 系: gpt-5.1〜5.4, **gpt-5.2-codex**, gpt-5.3-codex, gpt-5.1-codex-max, gpt-5.4-mini, gpt-5.4-pro
      - o 系（reasoning）: o1, o3, o3-pro, o3-mini, o4-mini, o3-deep-research
    - 現状 Routeful は `gpt-4o` + `gpt-4o-mini` fallback で運用、これらは 1.5〜2 年前の世代
    - Phase 1.3e 残課題（post-shift opening_hours / budget_exceeded）の主因は **LLM の constraint-following 能力**で、gpt-5 系に上げれば structured output と eligible_for_slots の遵守が大幅改善する見込み
    - **推奨候補**: gpt-5 (default) + gpt-5-mini (fallback) への切替。reasoning 系（o3 / o4-mini）は 90s deadline + UX 観点で overkill
    - **次セッション (ix) として todo.md に登録済み**。実装は generator.py の `model="gpt-4o"` を 1 行変更 → verify --runs 5 で精度測定（コスト ~$0.5〜$1）
    - **判断軸**: gpt-5 でも post-shift / budget が残るなら自前修復続行、消えるなら自前修復ロジックを簡素化できる
  - **追記（2026-04-25 17:05 JST、gpt-5 切替実験 → revert）**:
    - `DEFAULT_PRIMARY_MODEL = "gpt-5"` / `DEFAULT_FALLBACK_MODEL = "gpt-5-mini"` に切替えて `verify --runs 5` を実施
    - 結果: success 2/5、**deadline 3/5 で全体回帰**、平均 **167.1 秒/run**（gpt-4o の 13 秒/run の 10x 以上遅い）、hallucination は 0% 維持
    - 原因: gpt-5 は内部で reasoning 段階を経るため response_time が大幅増。Routeful の deadline=150s（generator.py 規定）では gpt-5 を default で使えない
    - **revert 採用**: `DEFAULT_PRIMARY_MODEL = "gpt-4o"` / `DEFAULT_FALLBACK_MODEL = "gpt-4o-mini"` に戻す。gpt-5 は精度面で gpt-4o と同等以上だが速度コストが UX 要件（プラン生成 60s 目安）と非整合
    - **次セッションで試す価値あり**: (a) `gpt-5-mini` を primary に（mini は reasoning 軽量、速度差小の可能性）/ (b) deadline を 300s に拡張（UX で許容できる範囲か別途検討）/ (c) `gpt-4.1` 系（gpt-4o の改良、reasoning なしで速い）/ (d) `gpt-5-codex` / `gpt-5.2-codex` (codex 系は構造化出力に最適化、速度面も検証要)
    - **学び**: 「新しいモデル = 良い」ではなく、**reasoning 系は推論時間がかかる前提でアプリ全体の deadline を見直す必要**。Routeful は対面 UX なので 60-90s が現実限界、gpt-5 はそこに合わない
  - **追記（2026-04-25 17:20 JST、gpt-4.1 切替 + budget 30% で実用ライン到達）**:
    - **gpt-4.1 切替**: `DEFAULT_PRIMARY_MODEL = "gpt-4.1"` / `DEFAULT_FALLBACK_MODEL = "gpt-4.1-mini"`。reasoning なし、gpt-4o 後継で速度維持、structured output / constraint-following は段違い改善
    - **fixture budget 30%**: verify 用 `budget_breakdown` を `lodging=45/meal=25/activity=20/transit=10` → `lodging=40/meal=30/activity=20/transit=10` に修正。実旅行の現実的配分 (4 食 × ~2,500 円 が meal 8,750 円ベンチマークを超過する問題を解消)
    - **system prompt budget hint 試行 → revert**: 8 番目のルールとして「price_level=1〜2 優先」を追加したが、ルール多重化で LLM の attention dilution が起きて success 0/5、budget_exceeded=6 に逆悪化。先行 7 ルールから動かさないのが正解と確認
    - **5-run サンプリングの実態**: gpt-4.1 + 30% budget 構成で連続 5 回の `verify --runs 5` 実施
      - run 16: success 3/5 (60%) / budget=0, opening=7
      - run 17: success 3/5 (60%) / budget=4, opening=2
      - run 19: success 4/5 (80%) / unknown_place=1（budget hint revert 後 1 回目）
      - run 20: success 1/5 (20%) / opening=9, budget=5
      - run 21: success 1/5 (20%) / budget=8, opening=3
      - **累計 12/25 = 48%、中央値 60%、20〜80% range** — **5-run は本質的にノイジー、真値は 40〜60%**
    - **本セッション最終形態**:
      - hallucination **0% (5/5 run で安定維持、25/25 sample)**
      - success rate **~50% (run 13 baseline の 0% から劇改善)**
      - 平均 **10 秒/run** (gpt-5 の 167s から改善、UX 60-90s 内)
      - residual: outside_opening_hours (post-shift 由来)、budget_exceeded (LLM が高 price_level 多選び)
    - **学び**:
      - 5-run は確度測定にはノイジー、runs 20+ が必要（コスト $2+）。MVP では 5-run で 60% 中央値出れば実用判断材料として OK
      - 構造改修（self-healing）と精度改修（モデル選択）は累積で効く
      - prompt rule を増やすほど効くわけではない、**8 ルール以上で attention dilution が起きる**
      - reasoning 系 (gpt-5 / o3) は対面 UX に不適、gpt-4.1 が現状ベスト
    - **次セッション候補（実装規模順）**:
      - (vii') assembler に budget aware swap（同 category cheapest alternate に置換）、~30 分
      - (viii') assembler に post-shift opening_hours swap（transit 後に再 eligibility 確認）、~30 分
      - (x) verify --runs 20 で確度 ±10% に絞る、$2 でハッカソン提出前最終確認
  - **追記（2026-04-25 17:30 JST、_find_alternate_place のバグ fix）**:
    - **真因発見**: verify_hallucination_rate.py に詳細 issue ログを追加して原因調査。`outside_opening_hours: place_id=ChIJCbd34bSjGWAR22SmiUdhVCw（肉のKINOSUKE）は曜日 0（月）は定休日` を catch。self-healing は fire していない (no swap log)
    - **バグ箇所**: `_find_alternate_place` (transit edge 不在時の代替選定) が **slot eligibility を check していない**。フロー: LLM picks A → A 適合で通過 → prev→A の transit edge 不在 → `_find_alternate_place` が同 category の月曜定休 place を「transit 到達可能」だけで選ぶ → validator が定休日 catch
    - **fix**: `_find_alternate_place` に `slot_meta` / `slot_date` を渡し、`is_place_eligible_for_slot` を必須条件に追加。test 28 件 PASS (regression なし)
    - **効果**:
      - run 23（fix 直後）: success **5/5 (100%)**、residual 0、平均 4.3s/run
      - run 24: success 2/5 (40%) (new fail mode = unknown_transit_edge=2、これは bug fix が "偽の合格" を排除した結果)
      - run 25: success 4/5 (80%)、residual unknown_transit_edge=1
      - **累計 11/15 = 73%、中央値 80%** (前回の中央値 60% から +20pt)
    - **意味**: bug fix 前は ineligible alternate を返して assembler 通過させ、validator が catch するパターンが多かった。fix 後は構造的に「正当な代替が無い」と早期エラー化。残 `unknown_transit_edge` は pack の transit_matrix 密度不足で代替候補が枯渇する case。pack builder の改善で更に下げられる
    - **学び**: 詳細 issue ログを 1 件足すだけで bug が特定できた。「self-healing 動いてるはずなのに validator が catch」という矛盾サインを見逃さない
  - **追記（2026-04-25 17:50 JST、Codex 深掘りレビュー → 3 件の構造バグを修正、success 100% 到達）**:
    - **Codex 指摘**:
      - **Critical**: post-shift で start_dt が place の opening close を超えるケース未処理（assembler が黙って通し validator が catch）
      - **Major**: `_find_eligible_alternate_for_slot` が transit 到達可能性を check しない → opening OK だが到達不能の代替を選び後段で `NoFeasibleTransitError` 引き起こす
      - **Major**: `_pick_departure_time` の `max()` fallback が「start_dt より前の出発時刻」を返す → validator pass するが意味的に過去の電車に乗る plan
      - **Major (latent)**: 営業時間 parser の日跨ぎ未対応（Phase 2 scope 外）
      - **Minor**: item_type vs category 整合性 validator 未実装（defer）
    - **修正**:
      - Critical fix: `is_place_open_at_dt` helper 追加、assembler に post-shift check で `IneligiblePlaceForSlotError` raise
      - Major fix #1: `_find_eligible_alternate_for_slot` に `prev_place_id` 引数追加、reachable_ids で transit 到達可能性をフィルタ
      - Major fix #2: `_pick_departure_time` の max() fallback を廃止、過去候補のみなら `NoFeasibleTransitError` raise。verify の candidate_departures も 5 点 (`["09:00","12:00","15:00","18:00","21:00"]`) に拡張で全 transit を覆う
      - test 1 件 (post-shift raise) 追加 + 既存 fallback テストを raise 期待に書き換え。`_edge` test helper のデフォルト candidates も 5 点に拡張
    - **効果**:
      - run 26 (Codex fix 直後): success **5/5 (100%)**、residual 0、平均 4.4s/run
      - run 27 (再検証): success **5/5 (100%)**、residual 0、平均 4.4s/run
      - **累計 10/10 success、hallucination 0% (50+ sample で 0% 維持)**
    - **共通パターン認識**: 5 件の指摘すべて「複数制約次元（transit / opening_hours / category / cost / 順序）の一部のみ check」構造の bug。**self-healing/代替選定系の関数は全制約次元を貫徹的に check**するルールにした
    - **学び**:
      - 詳細 issue ログを永続化（verify_hallucination_rate.py）したことで以降の bug 検知が格段に楽に
      - LLM 旅行計画のような **複数制約系**で helper の責務を最小化しすぎると、複合制約をくぐり抜ける bug が出やすい。代替選定ヘルパは「事前 filter で全制約満たす候補のみ」が原則
      - Codex 独立観点レビューは **同種 bug の網羅検出に有用**。1 件 fix した後も他の同パターン bug を出してくれた

## 2026-04-25: Supabase anon sign-in を test 設計で枯渇させた
- 問題: `pytest -m integration tests/test_rls.py` を走らせると 3 件 PASS / 5 件 `AuthApiError: Request rate limit reached` で FAIL。10 分・30 分待機でも解けず、Manato の IP から Supabase anon sign-in 枠（default 30 signups/hour/IP）がほぼ完全枯渇。routes_plans integration も同じ枠に阻まれて未実行
- 原因: 各テスト内で `_make_anonymous_user()` を 2 回呼ぶ設計（user_a + user_b を 2 人立てる）なので 8 テスト = 最大 16 sign-in 消費。連続実行を数回繰り返すと 30/hour 到達。rate limit を前提にした retry / cooldown / 再利用設計が未導入だった
- ルール:
  - **integration test で anon sign-in を使うテストは、1 test 1 sign-in に収まるよう setup を共有化**（session 単位 fixture + cleanup 移譲）。現状 8 件で最悪 16 sign-in → 将来 4〜5 sign-in に圧縮したい
  - 連続実行時は `pytest -m integration --maxfail=1 -x` で枠枯渇を早期検出し 1 時間クールダウン
  - CI で走らせる場合は IP 当たりの rate limit を気にせず済むよう **ローカル Supabase（`supabase start`）を用意**するか、テスト用の別プロジェクトを切る運用を検討
- → 2 回目が来たら `.claude/rules/testing.md` の「integration テスト」節に昇格（今は 1 回目）

## 2026-04-25 (2回目): domain enum を 3 箇所以上に重複定義すると Codex に必ず指摘される
- **これは 2回目**。前回（同日 Phase 2.1 backend）で Codex が `_THEME_KEYWORDS` (builder.py) / `_THEME_LABEL_JP` (prompt.py) / `ThemeKey` (schemas) の 3 箇所重複を Minor 5 として指摘し、`apps/api/src/themes.py` に集約した。今回（Phase 2.1 frontend）でも同パターンが `shared-types/ThemeKey` (型) / `planForm.ts/z.enum([...])` (zod 列挙) / `ThemePicker.tsx/THEME_OPTIONS` (UI options) の 3 箇所で再発、Codex に Major 2 として再指摘された
- 対処: `packages/shared-types/src/index.ts` に **`THEME_KEYS = [...] as const`** + **`THEME_LABELS_JP: Record<ThemeKey, string>`** を runtime + 型の単一情報源として追加。zod は `z.enum(THEME_KEYS)` で参照、UI は `THEME_KEYS.map((k) => ({ key: k, label: THEME_LABELS_JP[k] }))` で options 導出
- パターンの本質:
  - **ドメイン列挙（`ThemeKey` / `StartMode` / `ItemType` 等）は backend 側に runtime 定数（`as const` 配列）+ 型を**、frontend 側にも同じ runtime 定数を export して、**zod schema / UI options / Pydantic Literal の参照元を 1 つに**せよ
  - TypeScript の `as const` は型と runtime の両方に効く優れた集約手段。Python は `Literal[...]` + module 定数で同等を実現
  - drift 防止のため、双方に「相手と並行管理」コメントを残し、`tests/test_schema_parity.py` で field 整合を見るのと同じ精神で enum 集約も自動化したい（次セッション以降）
- ルール: **新規ドメイン enum を導入する時は、最初から「runtime 配列 + 型 + 表示ラベル」を集約モジュールに置く**。backend の `apps/api/src/themes.py` パターン or shared-types の `THEME_KEYS` パターンを踏襲
- → **2回目なので .claude/rules/data-model-sync.md に「ドメイン enum 集約原則」節を追加**する（次セッション）

## 2026-04-25: shared-types に runtime 定数を追加したら必ず `pnpm --filter shared-types build`
- 問題: `packages/shared-types/src/index.ts` に `export const THEME_KEYS = [...] as const` を追加して即 `pnpm --filter web test` を回したら、`THEME_KEYS is undefined` で全 ThemePicker test が失敗
- 原因: `packages/shared-types/package.json` の `main: "./dist/index.js"` で **build 済成果物を export** する構成。新規 export を追加しても dist/ を rebuild しないと web 側からは見えない
- 対処: `pnpm --filter shared-types build` を実行 → 成功
- ルール: **shared-types に runtime 定数（`export const`）を新規追加 / 改名したら、必ず `pnpm --filter shared-types build` を 1 回走らせてから web 側のテストを回す**。型のみの追加（`export type`）なら TS の path mapping 経由で見えるが、runtime 値は dist 必須
- → 1回目、次再発したら `.claude/rules/data-model-sync.md` の「shared-types 変更時の手順」節に昇格

## 2026-04-25: assembler の self-healing が anchor を「救済しすぎる」と test 設計が崩れる
- 問題: Phase 2.1 anchor mode の `AnchorMissingError` test を「2 slot で transit OTHER→OTHER (self-loop) → 代替探索 → ANCHOR1 が swap される」シナリオで書いたら、assembler が**親切すぎて anchor を再注入**してしまい AnchorMissingError が raise されなかった
- 原因: Phase 1.3e で実装した `_find_alternate_place` は「同 category + transit reachable + slot eligible」で代替を探す。pack に anchor (ANCHOR1) と OTHER しかない状況で OTHER→OTHER が self-loop で塞がると、唯一の選択肢 ANCHOR1 が swap 候補に上がる。結果: LLM が anchor を無視しても assembler が自動で入れ直す
- 対処: test を **1 slot 構成** に変えて transit / swap 経路を排除し、純粋に「anchor が plan に居ない」case を作った
- 学びの本質:
  - **self-healing が強い設計は production の robustness に有用**だが、**「healing で隠蔽されるエラー」を test で再現するには healing 経路を意図的に塞ぐ必要**がある
  - test の「最小再現条件」は実装の挙動次第で変わる。Phase 1.3e で healing を強化したことで、Phase 2.1 の anchor missing test の条件が複雑化した（2 phase 間の影響）
  - production で anchor が swap されて消える case は実在する（hallucination ではないが anchor 軽視）。post-check は必須
- ルール:
  - **self-healing 系を追加した後、その healing が「validator/check で catch すべき error」を握りつぶしていないか必ず逆方向の test も書け**
  - test 設計は「最小再現」が原則だが、self-healing がある場合「healing が動かない最小条件」まで踏み込む
- → 2 回目が来たら `.claude/rules/testing.md` の「self-healing がある実装の test 設計」節に昇格（今は 1 回目）

## 2026-04-25: 「RLS 42501」の真因は実は `plans.session_id` の FK 違反 (23503) だった
- 状況: Phase 1.10 Vercel 本番 E2E で `/plan/new` submit すると `POST /rest/v1/plans 409 Conflict` が返る。Network response header に `proxy-status: PostgREST; error=23503` (foreign_key_violation) が乗っており、**RLS ではなく FK 違反**だと確定
- 真因: `plans.session_id UUID NOT NULL REFERENCES sessions(id)` という FK 制約があるが、Supabase の anon サインインは `auth.users` にしか行を作らず `public.sessions` には mirror されない。`session_id = auth.uid()` で INSERT すると参照先 row が存在せず FK 違反
- これが Phase 1.3d 残課題「test_routes_plans.py の RLS 42501 解消」の真の正体:
  - test では FK より先に RLS WITH CHECK が評価されるか、別経路で 42501 として観測されていた
  - production では FK が先に弾く形で 23503 として観測（同じ問題の別の見え方）
  - test_rls.py の `_ensure_session_row()` ヘルパが既に backfill 操作で対処していたが、本番側に同じ仕組みが無かった（test 設計上は気付いていたが production 移行時に漏れた）
- 対処: `supabase/migrations/20260425_05_auth_user_sessions_mirror.sql` を新規追加:
  - `auth.users` INSERT トリガで `public.sessions` に自動 mirror（`SECURITY DEFINER` でトリガ実行は SECURITY 委譲）
  - 既存 anon user の backfill（`SELECT id FROM auth.users` を `INSERT ... ON CONFLICT DO NOTHING`）
  - 全て冪等
- ルール:
  - **「RLS 42501」と「FK 23503」は production REST API では似た失敗に見えるが原因が異なる**。response body / proxy-status header の Postgres error code を必ず確認せよ
  - **Supabase 匿名認証 (`signInAnonymously`) は `auth.users` にしか行を作らない**。custom テーブルとの FK で繋ぐ場合、必ず mirror トリガを設定する。これは「データモデル設計時に決めるべき事項」で、後追いで気付くと本番ブロッカーになる
  - test 環境で「workaround」（_ensure_session_row のような helper）を入れる場合、**同じ workaround を production 側にも仕組みとして組み込んでいるか必ず照合せよ**。test だけ通す対症療法は production 移行時に必ず破綻する
- → 2 回目が来たら `.claude/rules/data-model-sync.md` の「Supabase 匿名認証で custom テーブル FK を繋ぐなら mirror トリガ必須」節に昇格（今は 1 回目）

## 2026-04-25: pnpm strict isolation + 依存先 package の peer 宣言漏れで Next.js build が `Module not found: zod/v4/core` で失敗
- 問題: Phase 1.10 Vercel deploy で `apps/web` の `next build --turbopack` が以下のエラーで失敗（ローカル `pnpm --filter web build` でも再現）:
  ```
  ./node_modules/.pnpm/@hookform+resolvers@5.2.2_react-hook-form@7.73.1_react@19.1.0_/node_modules/@hookform/resolvers/zod/dist/zod.mjs:1:127
  Module not found: Can't resolve 'zod/v4/core'
  ```
- 真因（2 段重ね）:
  - **`@hookform/resolvers@5.2.2` のパッケージ仕様バグ**: `peerDependencies` に `react-hook-form` のみ宣言、`zod` を宣言してないのに `./zod` サブエントリで `import * as n from "zod/v4/core"` を実行している
  - **pnpm の strict isolation**: `.pnpm/<pkg>@<ver>/node_modules/<pkg>` は宣言済 peer だけ symlink される。zod が宣言されてないので `@hookform/resolvers` の nested node_modules には zod が無く、上位 `<root>/node_modules/` にも hoist されてないため Turbopack が解決できない
- 対処: `<root>/.npmrc` に **`public-hoist-pattern[]=*zod*`** を追加 → `pnpm install` し直し → `<root>/node_modules/zod` が hoist され nested package からも resolution が通る
- 効果: `pnpm --filter web build` 成功、6 ルート全部 generate 確認、テスト 61/61 PASS（regression なし）
- ルール:
  - **pnpm + monorepo + Next.js（特に Turbopack）構成で `Module not found: <subpath>` が出たら、まず依存元 package の `peerDependencies` 宣言を疑え**。issue tracker で similar bug が常に出ているライブラリ（react-hook-form / @hookform/resolvers / @tanstack 系）は要警戒
  - **fix は `.npmrc` の `public-hoist-pattern[]=*<pkg>*` が最小侵襲**。ただし「自動的に hoist する範囲が増える」副作用があるので、対象は具体的な package 名 prefix で絞る
  - 同じ問題は `npm` / `yarn classic` では起きない（hoisting が default で甘いため）。pnpm を使う限り宿命
- → 2 回目が来たら `.claude/rules/frontend-design.md` か `docs/setup-guide.md` の monorepo セクションに昇格（今は 1 回目）

## 2026-04-25: Render Free + Singapore region + render.yaml で /healthz 一発通過、CORS env も即時反映
- 状況: `feat/deploy-prep` で配置した render.yaml を Render Blueprint に流し込んだだけで、コード追加なしで `https://routeful-api.onrender.com/healthz` が `{"service":"routeful-api","status":"ok"}` を返す状態に到達。手動セットアップ（Settings UI で Build / Start command / Python version を 1 つずつ設定）と比べて圧倒的に速かった
- 良かった点:
  - `region: singapore` を選んだら NRT (東京) edge 経由でルーティング、cold start 1 回目 ~0.4s、2 回目 ~0.1s。日本ユーザ向けで oregon より体感速い
  - `CORS_ALLOWED_ORIGINS=http://localhost:3000` 仮置きで起動 → curl でも `access-control-allow-origin: http://localhost:3000` がエコーバック確認できた。実装と env が一致して production で初動する
  - Free plan でも `gunicorn --workers 1 --timeout 180` の boot は問題なし。worker メモリ 512MB に収まる
- 注意点（次セッション以降への申し送り）:
  - Render Free の **HTTP Request Timeout 設定が UI に出ない**（plan による / UI 改定揺れ）。gunicorn の `--timeout 180` で worker は守られるが、edge proxy 側の上限が不明（推定 30〜100s）。Phase 1.3e で生成 4.4s 平均なので Free でも実用通る見込みだが、502/504 が出たら Starter ($7/mo) 移行
  - 1 回目は cold start で 30〜60s かかる可能性。本番デモでは事前に warm-up 用 curl を 1 発打つと体感が劇的に良くなる
- ルール:
  - **monorepo + 多言語 (Python + TS) のサーバ deploy には render.yaml Blueprint を最優先**せよ。手動 UI セットアップは設定漏れ・再現性なしで他メンバーが困る
  - region 選択は **JP 向けなら singapore 一択**（実測で oregon より速い、GH Action / OpenAI 米国へのレイテンシは無視できる程度）
- → 2 回目が来たら `.claude/rules/api-rules.md` の「デプロイ」節に「IaC（render.yaml / vercel.json）優先」を追加（今は 1 回目）

## 2026-04-25: Vercel の Root Directory ピッカーは monorepo の中間ディレクトリを隠す
- 問題: Phase 1.10 Vercel デプロイで Root Directory に `apps/web` を指定したいのに、Vercel 新 UI のフォルダ選択モーダルに **`apps/` 自体が候補として出てこない**。表示は `hackathon_2026-04-13`（repo root）/ `docs` / `tasks` のみで、`apps`/`packages`/`supabase` が抜け落ち
- 推測される原因: Vercel の Application Preset 検出が「直下に `package.json` + 認識可能な framework」のディレクトリだけを candidate にしている（apps/ 自体は workspace container で package.json なし、apps/web は次階層）。`docs` / `tasks` が出るのは謎（root のみ表示する別ロジック説あり）
- 対処:
  - **Root Directory フィールド横の Edit / 鉛筆アイコンをクリック → 自由テキストで `apps/web` と打つ**のが正攻法
  - UI に Edit が見当たらないバージョンの場合は **「いったん root で Deploy → 失敗確認 → Settings > General > Root Directory に `apps/web` を入れて Redeploy」**の 2 ステップで回避
  - Build & Output Settings の Install/Build Command を `cd ../.. && pnpm install` / `cd ../.. && pnpm --filter web build` で override すると Turborepo + pnpm-workspace でも通る（apps/web 単独 install だと shared-types が無く失敗）
- ルール:
  - **monorepo を Vercel に乗せる時は Root Directory のフリーテキスト入力 + Install Command override の 2 点を最初から想定せよ**。UI の自動検出に頼ると時間ロス
  - 同じ罠を踏んだ経験がある人にしか分からない UI なので、deploy 手順 docs（setup-guide.md）に「Root Directory の手入力方法」を明記する
- → 2 回目が来たら `docs/setup-guide.md` の Vercel 節に「Root Directory のフリーテキスト指定」スクショ + 手順を追加（今は 1 回目）

## 2026-04-25: validator の semantic check は「allowlist + 接尾辞パターン」の二段で Google Places の細粒度 category を吸収できる
- 問題: Codex Minor 指摘「item_type vs category 整合性 validator 未実装」を実装する際、Google Places API は `restaurant` だけでなく `japanese_restaurant` / `yakiniku_restaurant` / `taiwanese_restaurant` / `seafood_restaurant` 等の細粒度 category を返す。素朴な `category in {"restaurant", "food", ...}` 厳密一致だと**ほとんどの実 place を mismatch と誤判定**する（Phase 1.3e の `_find_alternate_place` で同じ罠にハマった経験あり = `category[0]` 厳密一致だと candidate 枯渇）
- 対応: 二段判定で吸収:
  - **第 1 段（exact allowlist）**: `_MEAL_CATEGORIES = {restaurant, food, cafe, bakery, bar, meal_takeaway, meal_delivery}` / `_LODGING_CATEGORIES = {lodging, hotel, resort_hotel, ryokan, bed_and_breakfast, ...}`
  - **第 2 段（接尾辞パターン）**: meal は `c.endswith("_restaurant")` も許容。Google の動的 subtype に追従できる（新しい cuisine subtype が増えても allowlist 更新不要）
- 設計原則:
  - **activity / transit は permissive**: activity の category 範囲は広すぎる（観光地 / 公園 / 店 / 自然 / 体験）ため check しない。validator の責務を「明確に意味的に間違いと言える case のみ catch」に絞る
  - **category 空 = judgement 保留**: pack 構築側の情報欠損で penalize しない。validator 自身が完璧な情報を要求するな
  - **allowlist は frozenset**: 不変性とハッシュ化高速化、import-time 構築コストゼロ
- ルール:
  - **第三者 API（Google Places 等）の細粒度 category を扱う時は、allowlist + パターン抽象化の二段で吸収せよ**。allowlist 単独では新 subtype 追加に脆弱
  - validator の semantic check は「明確な間違い」だけ捕捉。曖昧な case は permissive 側に倒して LLM の判断を尊重（誤検出で retry 浪費を避ける）
- → 2 回目が来たら `.claude/rules/llm-rules.md` の「validator 設計原則」節に昇格（今は 1 回目）

## 2026-04-25: setup-guide.md と requirements.txt / app.py が整合しないまま Phase 1.10 直前に来た
- 問題: Phase 1.10 デプロイ準備のため現状調査したところ、本番が動かない 2 件のコード/設定漏れを発見:
  - `apps/api/src/app.py` に CORS 設定がゼロ（Vercel→Render は cross-origin で全 fetch がプリフライト段階で blocked）
  - `apps/api/requirements.txt` に `gunicorn` が無いが、`docs/setup-guide.md` の Render start command が `gunicorn 'src.app:create_app()'` を前提にしている
- 原因: Phase 0〜1.9 はすべてローカル開発（`flask run` + `next dev` 同一 origin）で完結したので CORS 不要 + `flask` の dev server で動いてしまっていた。setup-guide.md は本番運用を前提に書いたものの、実コードは dev 動作に合わせて書いたまま放置
- ルール:
  - **デプロイ docs を書いたら、その docs に登場する依存（gunicorn / CORS / flask-cors 等）はその場で `requirements.txt` と起動コードに反映する**。docs 先行・実装後追いの時間差が長期化するとデプロイ直前に判明する
  - 本番想定の cross-origin 通信が出てくる時点（フロントが Render URL を叩く設計に決まった時点）で CORS は仕様書だけでなくコードに入れる。ローカルで動いてるからといって後回しにしない
- → 2 回目が来たら `.claude/rules/api-rules.md` の「環境変数の扱い」節の隣に「本番運用前提のミドルウェア（CORS / gunicorn / SecureHeaders 等）はローカル開発時から組み込む」を追加（今は 1 回目）

## 2026-04-25: docs/data-model.md の shared_plans VIEW がカラム名衝突で実行不能だった
- 問題: `supabase/migrations/` を起こそうとして既存 DDL を読み直したら、`CREATE VIEW shared_plans AS SELECT p.*, pa.*, pi.* FROM plans p LEFT JOIN participants pa ... LEFT JOIN plan_items pi ...` が書かれていた。これは p.id / pa.id / pi.id など同名カラムが複数あるため PostgreSQL で `duplicate column name` エラーになり実行不能。Phase 0.2 で本番に適用した際に VIEW セクションを skip していたため見過ごされていた
- 原因: DDL を docs に書いた時点で実行確認していなかった。Phase 1.9 共有 API の実装方針が「view 経由」から「Flask + service_role 経由」に変わった後も、docs の VIEW 定義を直し忘れた
- ルール:
  - **DDL を docs に貼る時は、**少なくとも一度は本番 or ローカル Supabase で SQL Editor 実行して syntax を確認する
  - 運用方針が変わった（view → Flask 経由）場合、該当 DDL もその場で簡素化（使わないなら削除も可）
- → 2 回目が来たら `.claude/rules/data-model-sync.md` に「DDL は実行確認必須」節を追加
