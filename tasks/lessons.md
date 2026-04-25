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

## 2026-04-25: Supabase anon sign-in を test 設計で枯渇させた
- 問題: `pytest -m integration tests/test_rls.py` を走らせると 3 件 PASS / 5 件 `AuthApiError: Request rate limit reached` で FAIL。10 分・30 分待機でも解けず、Manato の IP から Supabase anon sign-in 枠（default 30 signups/hour/IP）がほぼ完全枯渇。routes_plans integration も同じ枠に阻まれて未実行
- 原因: 各テスト内で `_make_anonymous_user()` を 2 回呼ぶ設計（user_a + user_b を 2 人立てる）なので 8 テスト = 最大 16 sign-in 消費。連続実行を数回繰り返すと 30/hour 到達。rate limit を前提にした retry / cooldown / 再利用設計が未導入だった
- ルール:
  - **integration test で anon sign-in を使うテストは、1 test 1 sign-in に収まるよう setup を共有化**（session 単位 fixture + cleanup 移譲）。現状 8 件で最悪 16 sign-in → 将来 4〜5 sign-in に圧縮したい
  - 連続実行時は `pytest -m integration --maxfail=1 -x` で枠枯渇を早期検出し 1 時間クールダウン
  - CI で走らせる場合は IP 当たりの rate limit を気にせず済むよう **ローカル Supabase（`supabase start`）を用意**するか、テスト用の別プロジェクトを切る運用を検討
- → 2 回目が来たら `.claude/rules/testing.md` の「integration テスト」節に昇格（今は 1 回目）

## 2026-04-25: docs/data-model.md の shared_plans VIEW がカラム名衝突で実行不能だった
- 問題: `supabase/migrations/` を起こそうとして既存 DDL を読み直したら、`CREATE VIEW shared_plans AS SELECT p.*, pa.*, pi.* FROM plans p LEFT JOIN participants pa ... LEFT JOIN plan_items pi ...` が書かれていた。これは p.id / pa.id / pi.id など同名カラムが複数あるため PostgreSQL で `duplicate column name` エラーになり実行不能。Phase 0.2 で本番に適用した際に VIEW セクションを skip していたため見過ごされていた
- 原因: DDL を docs に書いた時点で実行確認していなかった。Phase 1.9 共有 API の実装方針が「view 経由」から「Flask + service_role 経由」に変わった後も、docs の VIEW 定義を直し忘れた
- ルール:
  - **DDL を docs に貼る時は、**少なくとも一度は本番 or ローカル Supabase で SQL Editor 実行して syntax を確認する
  - 運用方針が変わった（view → Flask 経由）場合、該当 DDL もその場で簡素化（使わないなら削除も可）
- → 2 回目が来たら `.claude/rules/data-model-sync.md` に「DDL は実行確認必須」節を追加
