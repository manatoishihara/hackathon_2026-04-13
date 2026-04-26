# Phase 1.10 fix: Evidence Pack の category 多様性 + 距離分散保証

**ステータス**: codex review 1 回目 完了 → Blocker 2 / Major 5 / Minor 2 / OK 2 を反映済（実装着手準備完了）
**ブランチ**: `feat/evidence-pack-diversity`
**スコープ**: auto モードで「観光地 + 宿泊 + 食事処の混合」 + 距離クラスター抑制を保証する
**想定 LOC**: +150（実装 ~80 / test ~70、フロント変更なし、3 点同期不要）
**想定時間**: 1〜2 時間
**OpenAI コスト**: 0（unit + integration test のみ、本番 E2E Run 8 で ~$0.05）

## 1. 背景: 本番 E2E Run 7 で判明した bug

`/api/evidence/places` を `region: "箱根"`, auto モード, wishes_text=「温泉」「自然散策」で叩いた結果:
- places 10 件**全部が箱根湯本駅周辺の飲食店**（HAKONE PICNIC / 箱根食堂 / 肉のKINOSUKE / 箱根BOOTEA / BOX BURGER 等）
- 互いの距離 **0.01〜0.26 km**（100m 以内）
- **観光地・宿泊・温泉施設 0 件**

**結果として**:
- フロント Maps Directions の TRANSIT が至近距離で `ZERO_RESULTS`
- `transit_matrix: []` で `/api/plans/generate` に送る
- LLM が plan を組めず validator 3 回 retry → **422 plan generation failed after retries**

詳細は `tasks/todo.md` の Phase 1.10 本番 E2E Run 7 節。Codex review で **🅒 (post-filter category quota) 主軸 + 🅐 (keyword 拡張) 最小併用 + 距離偏りガード** が推奨された。

## 2. 真因（推定）

1. **Places API text search の ranking が人気度 (user_ratings_total) に偏る** → `"箱根 観光"` でも飲食店（湯本駅前のレビュー多い店）が上位に来る
2. **箱根湯本駅は観光ハブで人気店集中** → 上位 10 件全部が駅前 100m 圏内
3. 現状の `_generate_keywords` は **`["{region} 観光", "{region} 飲食"]` の 2 軸のみ**（tag が空の auto モードで実質 2 軸）→ category 多様性が保証されない
4. dedupe 後の cap (`MAX_PLACES=15`) が「先に来た順」採用 → 偏りがそのまま固定

## 3. 設計（3 axis）

### 3a. Keyword の最小拡張（🅐、Blocker 2 反映で全 mode 明示）

**`_generate_keywords(ctx)` 仕様（mode 別、Codex Blocker 2 反映で 1 表に統一）**:

| mode | 基本 4 軸 | tag 追加 | theme 語彙 | 合計 query 数 |
|---|---|---|---|---|
| **auto** | `["{region} 観光地", "{region} 温泉", "{region} 神社 寺", "{region} 食事処"]` | 最大 1 個（重複は無視） | なし | ≤ 5 |
| **anchor** | 同上 | 最大 1 個 | なし | ≤ 5（anchor place は別経路で fetch、search は周辺探索用） |
| **theme** | 同上 | 最大 1 個 | `_THEME_KEYWORDS[theme]` を全部 prepend、ただし合計 5 を超えないよう先頭から 5 - len(基本+tag) 件で打ち切り | ≤ 5 |

**ポイント**:
- 全 mode で **基本 4 軸を必ず投入**（multi-axis category 多様性を保証）
- `_THEME_KEYWORDS` で theme 語彙が来る場合、基本 4 軸を維持しつつ theme bias を加える（既存 theme bias の意図を保ちながら、Run 7 型の偏りを防ぐ）
- tag からの追加は **最大 1 個**に削減（既存「最大 3 個」は redundancy が高かったため、4 軸の代わりに削減）
- 合計 5 query 以内 → `PARALLEL_WORKERS=5` 内でレイテンシ影響最小

### 3b. Post-filter category quota（🅒、本命）

**`_merge_anchors_and_search` の cap ロジックを書き換え**:

| Category bucket | quota | 検出ロジック |
|---|---|---|
| 観光地 | 6 件 | `category` に `tourist_attraction` / `museum` / `park` / `shrine` / `temple` / `place_of_worship` / `art_gallery` / `aquarium` / `zoo` のいずれか |
| 飲食 | 5 件 | `category` に `restaurant` / `cafe` / `bakery` / `bar` / `meal_takeaway` / `meal_delivery` / `*_restaurant` 接尾辞 |
| 宿泊 | 2 件 | `category` に `lodging` / `hotel` / `resort_hotel` / `bed_and_breakfast` / `ryokan` |
| その他 | 2 件 | 上記いずれにも当てはまらない |
| **合計** | **15 件** | `MAX_PLACES=15` 維持 |

**判定優先順位（Codex Major 3 反映）**: **lodging > attraction > meal > other**。lodging を最優先にすることで「`["spa", "lodging"]` の温泉旅館」が誤って attraction に分類されるリスクを排除。`_MEAL_CATEGORIES` / `_LODGING_CATEGORIES` allowlist は **`apps/api/src/llm/validator.py` の同名定数を import して再利用**（drift 防止、Phase 1.10 で実装済の `*_restaurant` 接尾辞も継承）。

**lodging quota の可変化（Codex Major 1 反映）**: `total_days` で動的計算。
- 日帰り（`total_days <= 1`）: lodging quota = 0、その分を attraction +1 / meal +1 に分配
- 1 泊（`total_days = 2`）: lodging quota = 1
- 2 泊以上（`total_days >= 3`）: lodging quota = 2

**bucket 不足時の挙動（Blocker 1 + Major 4 反映、「quota 優先 → MIN_PLACES=12 まで限定補填」の 2 段階）**:
1. 第 1 段: 各 bucket を quota 通り採用、合計 ≤ 15
2. 第 2 段: 合計が `MIN_PLACES=12` 未満なら、不足分を **「他 bucket の余り候補」から距離ガード守って補填**（attraction 不足 → meal / other から補う、最大 12 件まで）
3. それでも 12 件未満になったら そのまま返す（pack 件数低下を許容）

**補填の優先順位**: meal > other > attraction の余り（attraction は希少かつクラスター化しやすいため後回し）。これにより transit_matrix が必ず最低 ~12 places で組める（フロント 10km filter で〜44 ペア前後、Run 8 で確認）。

### 3c. 距離偏りガード（追加 by Codex、bucket 別閾値）

**bucket 別の距離閾値（Codex Major 2 反映）**:

| bucket | 閾値 | 理由 |
|---|---|---|
| attraction | **150m** | 観光地は同一施設内 spots（彫刻の森美術館 / 神社境内）の正当な近接を保持したい |
| meal | **300m** | 飲食店クラスター（湯本駅前）の overcrowding を抑制 |
| lodging | **500m** | 宿泊は箱根全域に分散すべき、近接 2 件は冗長 |
| other | **300m** | meal と同じ |

ロジック:
- bucket ごとに採用済 place の lat/lng を保持
- 新規候補と既存採用 place の距離を haversine で計算
- 同 bucket かつ **その bucket の閾値以内**なら **skip**（次の候補へ）
- 「湯本駅前 100m 圏に 5 件全部」のような Run 7 型は meal 300m で構造的に防止
- 「彫刻の森美術館敷地内」のような正当な近接は attraction 150m で許容（`exception 1〜2 件まで`、ただし境界ぎりぎりを避ける）

実装は `_merge_anchors_and_search` の中に inline で組み込む（小さい関数 `_distance_ok_for_bucket(candidate, accepted_in_bucket)` を 1 つ追加）。

### 3d. anchor モードの扱い

anchor モードは **user 明示意思**なので：
- anchor place は quota / 距離ガード両方を **skip**（既存の area filter skip と同じ）
- 一方で、anchor 以外の search 結果は quota / 距離ガードを適用
- 結果として「anchor + 多様性ある search 結果」の混合が成立

## 4. 変更ファイル一覧

| ファイル | 変更内容 | 行数 |
|---|---|---|
| `apps/api/src/evidence/builder.py` | `_generate_keywords` の auto モード拡張（4 軸）、`_BUCKET_CATEGORIES` 定数 + `_classify_bucket` helper、`_merge_anchors_and_search` を quota + 距離ガード対応に書き換え | +60 |
| `apps/api/tests/test_evidence_builder.py` | 新規 test 8〜10 件: keyword 4 軸 / quota 配分 / 距離ガード / anchor mode 整合 / fallback (bucket 不足時) | +70 |
| `tasks/todo.md` / `tasks/lessons.md` | Run 8 実施結果の枠を確保（実施後に詳細追記） | +10 |

**型変更なし**、API 契約変更なし、validator / assembly / フロント変更なし、3 点同期不要。

## 5. TDD 手順

### Step 1: `_generate_keywords` 拡張テスト先行 → 実装

| ケース | 入力 | 期待出力 |
|---|---|---|
| auto / tag 空 | `region="箱根", tags=[]` | 基本 4 軸: `["箱根 観光地", "箱根 温泉", "箱根 神社 寺", "箱根 食事処"]`（4 件、順序固定） |
| auto / tag 1 個（重複なし） | `tags=["写真映え"]` | 基本 4 軸 + `"箱根 写真映え"` = 5 件 |
| auto / tag 1 個（重複） | `tags=["温泉"]` | 基本 4 軸のみ（重複は無視）= 4 件 |
| auto / tag 3 個 | `tags=["温泉","和食","写真映え"]` | 基本 4 軸 + 先頭の 1 個（"温泉" は重複で無視 → "和食"）= 5 件 |
| theme="onsen" / tag 空 | `start_mode="theme", theme="onsen"` | 基本 4 軸 + onsen 語彙（先頭から空き枠分）、合計 ≤ 5 件 |
| theme + tag | `theme="art", tags=["美術館"]` | 基本 4 軸 + 「箱根 美術館」 + theme art 語彙 (合計 5 件で打ち切り) |
| anchor / tag 空 | `start_mode="anchor", anchor_place_ids=[...]` | 基本 4 軸（変更なし）= 4 件 |
| anchor / tag 1 個 | `anchor=..., tags=["観光"]` | 基本 4 軸 + 「箱根 観光」 = 5 件 |
| **mode 別キーワード回帰**（Codex Major 5） | 同 input を auto / anchor / theme で投げる | 各 mode の差分が仕様表通り（不可逆な drift を防ぐ） |

### Step 2: `_classify_bucket` 単体テスト先行 → 実装

優先順位は **lodging > attraction > meal > other**（Codex Major 3 反映）。

| Place の category | 期待 bucket | 理由 |
|---|---|---|
| `["tourist_attraction", "point_of_interest"]` | `attraction` | 観光地のみ |
| `["place_of_worship", "tourist_attraction"]` | `attraction` | 神社・寺は attraction allowlist |
| `["restaurant", "japanese_restaurant"]` | `meal` | restaurant + 接尾辞 |
| `["yakiniku_restaurant", "food"]` | `meal` | `*_restaurant` 接尾辞 |
| `["lodging", "hotel"]` | `lodging` | 宿泊 |
| `["ryokan"]` | `lodging` | 旅館 |
| **`["spa", "lodging"]`** (温泉旅館) | **`lodging`** | **lodging 最優先**（spa は attraction allowlist にあるが lodging が勝つ）|
| **`["lodging", "tourist_attraction", "restaurant"]`** | **`lodging`** | 複数該当でも lodging 最優先 |
| **`["tourist_attraction", "restaurant"]`** | `attraction` | lodging なしなら attraction が勝つ |
| `["shopping_mall"]` | `other` | allowlist 外 |
| `[]` | `other` | 空 category は安全側で other |

### Step 3: `_merge_anchors_and_search` quota + 距離ガードテスト先行 → 実装

| ケース | 入力 | 期待 |
|---|---|---|
| 全 bucket 充足（1 泊） | 観光 10 / 飲食 10 / 宿泊 5 / その他 5、`total_days=2` | 観光 6 + 宿泊 1 + 飲食 5 + その他 2 + 補填 2 (meal+other 余り) = 14〜15 件 |
| 全 bucket 充足（日帰り） | 同入力、`total_days=1` | lodging quota=0、観光 7 + 飲食 6 + その他 2 = 15 件 |
| 全 bucket 充足（2 泊） | 同入力、`total_days=3` | lodging quota=2 |
| **観光不足 + MIN_PLACES 補填**（Major 4） | 観光 3 件のみ + 飲食 10 + 宿泊 2 + その他 5 | 観光 3 + 飲食 5 + 宿泊 1 + その他 2 = 11 件 → MIN_PLACES=12 未満なので飲食 / その他 余りから 1 件補填 = 12 件 |
| **観光極不足** | 観光 0 件 + 飲食 5 + 宿泊 1 | 観光 0 + 飲食 5 + 宿泊 1 + その他 0 = 6 件 → 補填しても候補なし → 6 件 (低下許容) |
| **距離ガード発動 (meal 300m)** | 飲食 5 件全部 200m 以内 | 1 件目だけ採用、残り 4 件は skip → 飲食 1 件 |
| **距離ガード境界 (Major 5)** | meal: 同 bucket 採用済の 299m / 300m / 301m に新候補 | 299m=skip、300m=skip（境界含む）、301m=採用 |
| **距離ガード境界 attraction** | attraction: 149m / 150m / 151m | 149m=skip、150m=skip、151m=採用 |
| **anchor + search dedupe (Major 5)** | anchor 1 件 + search に同じ place_id を含む結果 | anchor が先、search の重複は無視（既存 dedupe 維持） |
| anchor + search 距離ガード bypass | anchor 2 件が 100m 以内 + search も近接 | anchor 2 件は両方採用（bypass）、search 側は距離ガード適用 |
| **area filter 順序保証 (Minor 2)** | search 結果に `locality` 含む | quota 適用前に `_is_area_place` で除外、bucket 分類対象外 |
| **mixed category 優先順位 (Major 5)** | `["spa", "lodging"]` の温泉旅館を search 結果に含める | lodging bucket に分類される（attraction でない） |
| MAX_PLACES 超過 | 各 bucket 余裕 | 15 件で打ち切り（補填も 15 件以内） |

### Step 4: 統合テスト

`tests/test_evidence_builder.py` に既存 integration test があれば、auto モードで Run 7 同等入力（箱根 / wishes 短文 / tag 空）→ pack の category 多様性を assert する test を追加。

`pytest -m integration` を rate limit 回復後に手動実行（ローカル env が動けば）。

### Step 5: 全体検証

- `pytest -m "not integration"` 全 unit PASS
- `pytest -m integration tests/test_evidence_builder.py`（必要に応じて）
- 本番 deploy 後 Run 8 で `transit_matrix: []` が解消するか確認

## 6. リスク

### Risk: bucket quota 不足時の合計件数低下
- 例: 「箱根」で観光地が 5 件しか取れなければ pack 14 件（cap 15 未満）
- 対処: LLM が pack 件数に依存しない設計（Phase 1.3e）なので影響軽微。15 件 → 12〜13 件でも plan 生成は可能
- 緩和案（Phase 2 検討）: 不足分を「観光不足なら飲食を 1 件追加」で補填する fallback。今回は YAGNI で実装しない

### Risk: 距離 300m が厳しすぎる / 緩すぎる
- 300m は徒歩 4 分、箱根湯本駅前のクラスター解消には十分
- 観光地（彫刻の森美術館敷地内など）で複数 places が 300m 以内に正当に存在する case で意図せぬ skip リスク
- 対処: bucket 別に閾値を変える余地（観光 500m / 飲食 200m 等）。今回は **300m 統一**で MVP、Run 8 で結果を見て調整

### Risk: Phase 1.3e の hallucination 0% / success 100% に regression
- 設計は **prompt / validator / assembly に手を入れない**ので構造的影響なし
- pack の category 多様性が増えると LLM の slot 選択肢が増えて生成精度が向上する想定
- ただし places 数が偶発的に少なくなった場合（10 件未満）は LLM 生成自由度が下がる懸念。Run 8 で確認

### Risk: query 数増加による Places API レイテンシ
- 既存 2 query → 新 4〜5 query、`PARALLEL_WORKERS=5` 内
- 各 query は **10s timeout** (`REQUEST_TIMEOUT_SEC`、`apps/api/src/evidence/places.py:19`、Codex Minor 1 反映)、最悪 10 秒で並列完了
- p95 レイテンシ影響は **+0 秒**（並列実行で 5 query が 10s 内に収まる、Run 7 比でほぼ等価）

## 7. Codex review 1 回目の反映状況

- ✅ **Blocker 1**: 補填方針の矛盾解消 → 「quota 優先 → MIN_PLACES=12 まで限定補填」の 2 段階に統一（§3b）
- ✅ **Blocker 2**: keyword 仕様を 1 表で auto/theme/anchor 全 mode 明示（§3a）+ Step 1 test も全 mode カバー
- ✅ **Major 1**: lodging quota を `total_days` 連動可変化（日帰り 0 / 1 泊 1 / 2 泊以上 2、§3b）
- ✅ **Major 2**: 距離 bucket 別閾値（attraction 150m / meal 300m / lodging 500m / other 300m、§3c）
- ✅ **Major 3**: `_classify_bucket` 優先順位を **lodging > attraction > meal > other** に変更、validator allowlist (`_MEAL_CATEGORIES` / `_LODGING_CATEGORIES`) を import で再利用（drift 防止、§3b）
- ✅ **Major 4**: `MIN_PLACES=12` で限定補填、不足時は許容（§3b）
- ✅ **Major 5**: TDD test 5 件追加（300m 境界 / 150m 境界 / mixed category 優先順位 / anchor+search dedupe / area filter 順序 / mode 別 keyword 回帰）
- ✅ **Minor 1**: REQUEST_TIMEOUT_SEC を 10s に訂正（§6）
- ✅ **Minor 2**: area filter 順序保証 test 追加（Step 3）
- ✅ **OK 1, 2**: anchor bypass / scope 妥当性 → 維持

## 8. Codex review 2 回目（実装後）に確認してほしいポイント

1. 上記 Blocker / Major の反映が漏れなく実装されているか
2. `_classify_bucket` の優先順位 (`lodging > attraction > meal > other`) が allowlist 集合の重複に対して正しく動くか
3. 距離ガードの bucket 別閾値計算が境界値（150m / 300m / 500m）で正確か
4. MIN_PLACES=12 補填ロジックが「multi-iteration 抜けなし」で動くか
5. 既存 area filter / anchor bypass / theme keyword 拡張との統合に regression がないか

## 9. 完了基準

- [ ] `_generate_keywords` test (~9 件、auto/theme/anchor + tag 重複 + 回帰) PASS
- [ ] `_classify_bucket` test (~11 件、mixed category 優先順位含む) PASS
- [ ] `_merge_anchors_and_search` quota + 距離ガード + 補填 test (~12 件、境界値含む) PASS
- [ ] 既存 builder test の regression なし
- [ ] `pytest -m "not integration"` 全 PASS
- [ ] Codex review 2 回目で blocker 指摘なし
- [ ] commit 提案前に **secret プリフライト 0 hit** 確認（CLAUDE.md 新ルール）
- [ ] commit + push（user 手動）→ Vercel/Render auto deploy → **Run 8 で `transit_matrix` が ≥ 1 件取れる + `/plan/[id]` まで遷移 + Phase 2.2 の budget context が prompt に乗る**

## 10. 参考

- 元の bug: `tasks/todo.md` の Phase 1.10 本番 E2E Run 7 節
- 関連実装: `apps/api/src/evidence/builder.py` (`_generate_keywords` line 186, `_merge_anchors_and_search` line 292), `apps/api/src/evidence/places.py` (`search_by_text` line 64, `_to_place_point` line 157)
- Phase 1.10 validator の category allowlist パターン: `apps/api/src/llm/validator.py` の `_MEAL_CATEGORIES` / `_LODGING_CATEGORIES`
- Codex 1 回目相談: thread `019dcac1-efb0-7210-aa69-3eaf5bb076a3`（🅒 主軸 + 🅐 最小併用 + 距離ガードを推奨）
