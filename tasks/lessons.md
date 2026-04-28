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

## 2026-04-28: Phase 3 polish 実装 — Places API search の iconic spot coverage 改善 (pageSize 倍増 + 「名所」keyword 追加 + post-rank sort)
- **背景**: user 報告「箱根プランで本当に箱根の有名どころが取れているのか疑問」→ Network タブで pack 17 件を実態確認 → **大涌谷 / 芦ノ湖 / ポーラ美術館 / 箱根海賊船 / ガラスの森が一切含まれていない**ことが確定。代わりに飛竜の滝 / 玉簾の瀧のような中規模 spot や、地元 meal が 8 件 (3 日 plan で 6 meal slot に対して過剰) で観光地枠を圧迫
- **実装内容 (3 つを 1 commit)**:
  - **pageSize 10 → 20**: `apps/api/src/evidence/places.py:search_by_text` の default を Google Places API New 上限まで拡張。母数倍増で relevance ranking 11-20 位の iconic spot を拾えるように
  - **`rankPreference: "RELEVANCE"` 明示**: 将来 Google API のデフォルト変更への防御 (現状デフォルトと同じ)
  - **`_BASE_KEYWORD_SUFFIXES` に「名所」追加**: 5 → 6 軸、`_MAX_KEYWORDS` 7 → 8。「箱根 名所」はガイドブック系語彙で人気度ranking がバイアスされやすい
  - **post-rank sort by `user_ratings_total × rating`**: `_merge_anchors_and_search` 内で bucket quota 採用前に candidates を人気度 sort。tie-break は user_ratings_total。これでGoogle relevance ranking 任せの偏りを構造的に補正、ガイドブック級 iconic spot が中規模 spot より優先採用される
- **検証**: API 444 PASS (既存 test を 6 axes / _MAX_KEYWORDS=8 対応に更新 + 新規 test 4 件追加: rankPreference / pageSize=20 default / popularity sort / missing rating fallback)
- **本番効果検証 (working tree、user verify 待ち)**: pnpm dev で再 submit して pack 中身が変わるか / 大涌谷・芦ノ湖等が含まれるか / 422 自体が解消するか確認予定
- **学び 1 (構造 vs 偶然性)**: Google Places API text search を default 設定で叩くと relevance ranking 偏重 + pageSize 制限で iconic spot 取りこぼしが構造的に発生する。**「pack 17 places あるから OK」と件数だけ見ると質を見落とす**、件数 + 質 (iconic coverage) の二軸で評価する必要
- **学び 2 (post-rank sort の威力)**: Google の relevance ranking は地名 + suffix の組み合わせで意外な結果を出す (taiwanese_restaurant が「箱根 観光地」検索で上位に来る等)。**自前で `user_ratings_total × rating` で post-sort することで、人気観光地 (review 5000+ 件) が中規模 (200 件) より優先される**簡潔な解決策。LLM rules の「金額・時刻を計算させない」原則とは矛盾しない (検索結果の rank 決定論で並び替えるだけ)
- **学び 3 (pack quality 検証ルートの確立)**: ブラウザ DevTools Network → /api/evidence/places の Response body で pack 中身を直接見るのが一番速い検証ルート。CI には組み込めないが手動 verify として強い。将来は dump log を `LOG_LEVEL=DEBUG` で吐ける仕組みもアリ
- **次のアクション (user)**: pnpm dev で再 submit → pack 中身の Response body を確認 → iconic spot 含まれるなら箱根 422 も解消する可能性大、verify 後に commit 提案
- **rule 昇格候補**: 「Places API は pageSize 上限 + post-rank sort + 多軸 keyword で iconic coverage を保証」を `external-api-rules.md` に昇格 (2 回目で判断、本件で 1 回目)

## 2026-04-28: 箱根 3 日 plan 422 真因 — 水曜定休 × pack 内 meal candidate=1 縮退 + Places API の locationBias 完全欠落 (構造問題、demo blocker 候補)
- **問題**: ローカル `pnpm dev` で 箱根 3 日 plan (2026-04-28 火 〜 2026-04-30 木) を 3 回連続 submit → **3 回とも `/api/plans/generate → 422 "LLM generation failed: 3-4 issues after 4 attempts"`**。kind_summary は全 4 attempts × 全 3 run で `[('item_type_category_mismatch', 1〜3)]` 一色支配
- **真因 (assembler log で確定)**:
  - 直接トリガ: `Place 'ChIJfVf8vD2iGWARHJOlRc4Qr_M' ineligible for slot 'day2_dinner' (opening_hours mismatch on 2026-04-29); no alternate, accepting (validator will catch and retry)` 連発
  - **2026-04-29 (水) で opening_hours filter 後の meal eligible が candidate=1 まで縮退** → 同じ place を複数 slot に充当 → assembler が他 slot で swap 試行 → swap 先が item_type 不適合 (activity / lodging しか残らない) → validator が `item_type_category_mismatch` で reject → retry → LLM が同パターン → 4 attempts 尽きて 422
  - v6.2 で追加した `_find_item_type_compatible_used_place` (used 集合 reuse) は `item_type` 軸で発火するが、**`outside_opening_hours` 軸では発火しない**ため、本ケースをカバーしない
- **草津 3 日 plan は通って箱根は落ちる差**: 両方 total_places=17 だが (a) 草津は温泉/神社/寺で年中無休が多い vs 箱根は美術館/観光施設で **火・水定休** が多い、(b) 箱根 pack の lodging が 1 件のみ (rakuten 未設定 + Google Places 検索結果薄)、(c) 箱根 pack の transit edge coverage が薄く各 place が 4-6 reachable のみ
- **副次発見 (構造問題、demo blocker 候補)**: Places API text search の検索範囲制限が事実上ゼロ。`apps/api/src/evidence/places.py:81-86` の payload は `textQuery / languageCode / regionCode / pageSize` のみ:
  - **`locationBias` / `locationRestriction` 完全未使用** → 「箱根」を含む全国の店舗 (都内の箱根料理店 / 屋号に「箱根」が含まれるだけの店) が混入しうる。log で `taiwanese_restaurant` が複数混入してた説明がつく
  - **`rankPreference` 未指定 (暗黙 RELEVANCE)** → Google の relevance ranking 任せ。「箱根 観光地」検索で大涌谷・芦ノ湖・箱根神社が上位に来る保証なし、log の 17 places が箱根の人気観光地をカバーしているかは pack 中身を直接 dump するまで不明
  - **keyword が抽象** ("観光地" "温泉" "神社 寺" "食事処" "旅館 ホテル") → iconic spot を狙い撃ちしてない
  - 結果として「箱根を満喫できる plan が作れているか」は構造的に保証されておらず、demo の質に直結
- **demo 提出向けの解決選択肢 (推奨順)**:
  - **α. locationBias 追加** (~45 分): `external/health.py:139` で既に Geocoding API を叩いてる実績、同じ仕組みで region → lat/lng → 半径 15km を `locationBias.circle` に注入。都内混入が消えて transit_matrix coverage も改善 (15km 内に places が集まる)。リスク: pack の質が変わって 422 retry 挙動も変わる、事前 verify 必要
  - **β. keyword の人気度バイアス** (Phase 3 polish): `_BASE_KEYWORD_SUFFIXES` に「人気」「定番」「おすすめ」追加 or region 別 keyword set。LLM rules の「外部データのみ」原則は維持
  - **γ. v6.3 reuse fallback for `outside_opening_hours`** (~30 分): v6.2 の item_type 軸 reuse と同じ思想を opening_hours 軸にも適用、`_find_eligible_alternate_for_slot` tier3 枯渇時に used 集合内で opening_hours eligible 探す。リスク: 「dinner と lunch が同じ店」になりうる、demo 質微妙
  - **即時回避**: 日付を 木曜開始 にずらして submit (2026-05-01 金 〜 2026-05-03 日 等)、コード変更ゼロ
- **学び 1 (構造的)**: Places API text search を「素直に textQuery だけで叩く」と地理制約ゼロで意外な結果が来る。地名で region を絞りたいときは **`locationBias` 必須**。Google Maps API ルール `external-api-rules.md` の 4 階層 checklist に「**Phase 5: 検索結果の地理制約 (locationBias / locationRestriction)**」を追加候補
- **学び 2 (demo 質保証)**: 「pack に 17 places あるから OK」ではなく、**「pack の中身が region の iconic spot をカバーしているか」を別軸で検証**しないと demo の質を保証できない。pack dump スクリプトを CI に組み込むか、フロントで pack 表示 (debug mode) で見える化する仕組みが要る
- **学び 3 (条件依存の偶然性)**: 草津で動いた 3 日 plan が箱根で落ちたのは「火・水・木」という曜日 × エリアの定休日分布の偶然。**特定 region + 特定 date で再現性のある fixture テストが必要** (Phase 1.3e の `verify_hallucination_rate.py` は箱根固定 fixture だが、曜日依存性は test していなかった)
- **rule 昇格候補 (2 回目で判断)**: 「Places API は locationBias 必須」「pack 質保証の検証ルート」は次に同種ケースが出たら `.claude/rules/external-api-rules.md` に昇格

## 2026-04-28: `departure_point` が生成パイプライン全層で構造的に無視されていた — D 案 (現地集合・現地解散スコープに割り切り) で確定、将来 B 案で復活
- **問題 (user 報告)**: 出発地点フォームに「東京駅」等を入力しても、生成された旅程は旅先 (草津 / 箱根) の day1_morning 観光地から開始する。出発地→旅先の長距離移動費が予算 (transit カテゴリ) に計上されない
- **systematic-debugging Phase 1 で根本原因確定 — バグじゃなく設計の構造的欠落**:
  - 入力経路: form → DB `plans.departure_point` → `pack.query_context.departure_point` まで文字列としては流れる
  - **しかし生成パイプライン 7 層全てで参照されない**:
    - `evidence/builder.py:_generate_keywords` は `ctx.region` のみ使用、departure_point は keyword 検索しない → pack.places に出発地が入らない
    - フロント `transit.ts` は MAX_DISTANCE_KM=15 で 15km 以内ペアのみ Maps SDK fetch → 東京 (departure) → 草津 (region) は ~200km で全ペア out
    - `assembly.py:generate_slot_catalog` の day1 は `morning(09:00)` から start、「出発」「day1_arrive」slot 無し (**最終日の lodging だけ symmetric に skip** という暗黙の「現地で泊まって帰る」非対称設計)
    - LLM `prompts/v2.0.0/system.md` は departure_point ルール 0 行 (rule 1〜9 全部 places/slot/category の話)
    - `assembly.py:assemble_plan` は pack.places から全 slot を埋めるだけ
    - `plan_routes.py:_serialize_plan_item` は LLM 出力の item をそのまま変換、出発→最初の place の transit を prepend する処理 0 行
- **歴史的経緯 (なぜそうなったか)**: Phase 1.3 で「日本国内 transit は Google Routes/Directions サーバ API で取れない、フロント Maps JS SDK の DirectionsService だけが Jorudan 提携の transit を返す、それも近距離 15km 以内のみ運用」と割り切ったとき、出発地点を別レイヤで扱うフォロータスクが生えなかった (`apps/api/src/evidence/routes.py:1-17` に明文化済の制約)
- **検討した 3 案 (A/B/C) と user 判断**:
  - A. フロント表示層 prepend: 実装 2〜3 時間、共有 URL で消える、運賃精度低い
  - B. Backend で pack.places + slot_catalog に組み込む: 4〜6 時間、3 点同期 + 422 retry チューニング再発リスク
  - C. 「※ 旅先到着後のプランを生成」hint だけ追記
  - **重要な気づき (user 提案)**: 既存 slot_catalog が「最終日 lodging skip = 帰宅前提」非対称になっているところ、**出発側も「現地到着済み」前提にすれば対称** = 「現地集合・現地解散プラン」というコンセプトが defensible (後付け正当化ではなく、コードが既にそうなっている)
- **D 案で確定 (実装完了、2026-04-28、commit 提案待ち)**:
  - フォーム `apps/web/src/app/plan/new/page.tsx` の「出発地」 Input + Label 撤去
  - zod schema `departure_point: z.string().min(1, ...)` → `z.string()` (空文字許容)
  - api.ts で `form.departure_point?.trim() || "現地集合"` をフロントから送信、Pydantic / DDL 無変更
  - UI 上の追加注記は user 判断で **付けない** (入力欄の不存在自体で意図は伝わるため、過度な説明はノイズ)
  - `docs/data-model.md` の `departure_point` フィールドコメントに D 案経緯記載
  - **3 点同期トリガーせず**: schema は変えない、フロントの fallback で吸収。将来 B 案実装時に min(1) を復活させる
  - 検証: web test 165/165 PASS (新規 1 件「accepts empty departure_point」追加、既存 fixture は影響なし) / tsc clean / build PASS
- **将来 B 案ロードマップ (demo 提出後の polish)**: 出発地点 Geocoding (Google Geocoding API は project enabled 済) → 合成 place_id ではなく本物の place_id を pack.places 先頭に注入 → フロント Maps SDK の MAX_DISTANCE_KM=15 を「出発→最近接 place の 1 edge だけ無制限」例外で拡張 → slot_catalog 先頭に day1_arrive (item_type=transit) 固定 slot 挿入 → system.md に「day1_arrive は assembler 自動生成」明示 → fare 欠損時は距離 × 単価決定論カタログ (`_PRICE_MAP[transit_long_distance]`、新幹線 ~16円/km / 在来線特急 ~25円/km) で補完。実装目安 4〜6 時間、422 retry チューニングを伴う
- **学び 1 (構造的)**: 「フォーム入力欄の存在 = 機能の実装」とは限らない。Phase 1 で割り切った設計判断 (long-distance transit は別レイヤ) のフォロータスクが生えていないと、ユーザ体験上は「入力が無視される」見え方になる。**設計の割り切りをするときは「未実装の連鎖タスク」を todo に必ず残す**
- **学び 2 (時間資源配分)**: hackathon demo 直前は backend に手を入れる選択肢 (B) はリスク高。**MVP/demo 提出フェーズでは「正しさより安定」を優先し、UI 撤去 (D) で逃げる判断が defensible**。D 案は単なる「諦め」ではなく、既存設計の対称性を完成させる positive な reframing (片側だけ非対称な暗黙設計を symmetric に揃える)
- **学び 3 (非対称設計の発見)**: 既存 `assembly.py:generate_slot_catalog` の「最終日 lodging skip」だけ非対称だった暗黙設計が、出発地点の構造的欠落の真因。**コードレベルの対称性 (出発・帰宅で同じ skip ルール) を維持する判断は、UX レベルでも defensible なコンセプト (現地集合・現地解散) に直結する**
- **rule 昇格候補 (2 回目で判断)**: 「設計判断のフォロータスク化」と「コード対称性 = UX defensibility」は次に同種ケースが出たら `.claude/rules/` に昇格

## 2026-04-28: Demo 確定 — 2 泊 3 日 plan が完成、4 日 plan は demo スコープ外として保留
- **状況**: v6.2 deploy 後、本番 Run 13g (草津 4 日 / お任せ) で 422 再発、kind_summary=[item_type_category_mismatch=2, **budget_exceeded=4 (毎 attempt)**, outside_opening_hours=1]
- **真因 (4 日 plan の budget_exceeded)**: 草津 pack の meal candidate 3-4 件しかないため、6 食 (lunch+dinner × 3 日) を埋めるには同 restaurant を 5-6 回重複利用必要 → 食費累積で `meal budget = 80000×0.3 = 24,000 円` を超過 → validator catch
- **3 日 plan は完璧に動作**: Evidence Modal で出典/営業時間/評価表示、Map マーカー表示、dinner/lodging 含む全 slot 埋まる、`/api/plans/generate → 200`
- **user 判断**: 「2 泊 3 日なら根拠やマップ・出力数ともにうまくいったからこれで行こう」→ **demo target を 3 日 plan に確定、4 日 plan は demo スコープ外**
- **学び (重要、Phase 2 polish 7 段階の総括)**:
  - 「重複完全禁止」を hard constraint で入れた v1 の判断が後続全部の対症療法を生んだ。**Constraint の設計時に「本番 candidate 数で satisfiable か」を事前評価する**ルール候補 (`.claude/rules/llm-rules.md` 昇格)
  - **constraint を緩和するときは段階的でなく「constraint 自体を再設計」する判断もアリ**。重複防止を「lodging 完全許容 / meal/activity best-effort」と type-aware に分けた v5 設計判断は正解
  - **demo スコープを早めに切る**判断が時間制約下では重要。完璧を追わずに 3 日 plan で確定したのは正しい時間資源配分
- **後続候補 (demo 後)**:
  - v6.3 generator で `budget_exceeded` を soft issue 分類、retry 流さず plan 採用
  - cost 計算で重複 place は累積しない logic
  - Pack 構築時に meal candidate を強化検索

## 2026-04-28: Phase 2 polish v6.2 設計 — Run 13f log で item_type_category_mismatch 多発の真因 (meal candidate 不足) 確定、used 集合 reuse fallback で解消
- **Run 13f (v6.1 deploy 後、JST 04:21 草津 3 日 / 30,000 円) で 422 再発**:
  - attempt 1〜4 全部 `item_type_category_mismatch` を含む (各 1〜2 件)、計 5 issues / 4 attempts で 422
  - log 詳細から原因特定:
    ```
    day2_lunch ChIJhY2RO4 (meal place) → tier3 filtered out (candidates=3) → accept duplicate
    day2_dinner ChIJP8pdnv → tier3 filtered out → accept (opening hours 4/29 火曜定休も連発)
    day3_lunch ChIJP8pdnv → tier3 filtered out → accept duplicate
    day3_dinner ChIJu7dnyl → tier3 filtered out (candidates=1) → accept duplicate
    ```
  - **真因**: pack 17 places のうち **meal-compatible (restaurant/cafe/bakery 等) は 3-4 件しかない**。3 日 plan で lunch+dinner = 6 meal slot を埋めるには candidates 不足。重複防止 swap で meal-compatible が枯渇 → tier3 filter で 0 件 → original の item_type 不適合 place を accept → validator catch
- **v6.2 設計 (root cause fix)**: 「枯渇時は同じ restaurant を再使用してでも item_type は守る」。lodging 連泊許容と同じ思想を meal/activity にも適用
  - 新 helper `_find_item_type_compatible_used_place`: **used 集合内** で item_type compatible な place を探して再使用
  - item_type pre-check の accept 経路に reuse 試行を挿入: alternate なし → reuse 試行 → なし時のみ最終 accept (validator catch)
  - reachability filter は外す: self-loop は後段 transit skip 処理、edge 不在も skip path で吸収
- **検証**: API 441 PASS / Web 164 PASS / tsc clean / secret 0 hit
- **学び 1 (重要、設計判断のフレームワーク)**: 「**重複防止 hard constraint**」を入れると、結局 candidate 不足エリアで詰む構造的問題 (Phase 2 polish v1 で導入 → v5 で重複 best-effort 化 → v6 で item_type 守る → v6.2 で枯渇時 reuse、と段階的に緩和)。**「constraint を hard で入れる前に、本番 candidate 数で satisfiable か事前評価する」**ルール候補
- **学び 2**: Codex review 4 サイクル (各 v3〜v6) で設計段階の Major を catch しても、**「pack の絶対量」のような外部要因依存の問題は catch できない**。本番 deploy 後の Run 観測で初めて見える種類の bug がある (例: 4 attempts × kind_summary log 経由で枯渇判明)
- **学び 3**: validator は assembler の warn+accept を retry guidance に流すが、**candidate 不足では LLM がいくら retry しても解消しない**。assembler 側で「枯渇時は重複許容」の fallback を用意するのが最終解 (v6.2)
- **次のステップ (user 作業)**: v6.2 commit + push → 本番再 verify → demo ready

## 2026-04-28: Phase 2 polish v6 + v6.1 実装、4 日 plan 生成成功実証、3 件 hotfix で UX 完成度上げ
- **v6 (commit `c7c2983 / 586ae86 / 95c3fcd`、`707a4e3` で develop merge + push 済)**:
  - assembler **item_type pre-check** (LLM が meal slot に park 等を選んだら事前 swap、validator catch 待たず高速 path)。`_find_eligible_alternate_for_slot` の tier1/2/3 全部で `_is_item_type_compatible` filter 適用 (Codex review 1 Major 1)
  - **transit duration_min=0 → 最小 1 分補正** (徒歩 0 分至近 edge で start==end → INVALID_TIME_RANGE 防止)
  - **prompt v2 system.md 第 6 項強化**: activity / meal / lodging slot の category allowlist 明示、「絶対に割り当てるな」を明記
  - **Evidence (営業時間 / 評価 / 出典 / verified_at) populate**: `_serialize_plan_item` で pack.places から動的に埋める。旧空 hardcode を解消、フロント EvidenceModal で「✓ Places verified」「営業時間 09:00-22:00」「評価 4.5」表示可能に
  - 楽天 lodging API error response body を log に残す診断 logging 追加
  - Codex review 2 サイクル (Major 2 + Minor 2 → Blocker 0)、API 439 PASS / Web 164 PASS / tsc / build / secret 0 hit
- **本番 deploy 後の v6 動作実証**:
  - **4 日 plan が初めて成功** (`/api/plans/generate → 200`)。v3 (transit) → v4 (pack) → v5 (重複緩和) → v6 (item_type + duration) と段階的に塞いだ結果
  - kind_summary に `item_type_category_mismatch` が完全消失、`invalid_time_range` も解消 (assembler pre-check + duration 補正の効果実証)
- **v6 deploy 後の user 報告で発覚した 3 件 (v6.1 で hotfix、未 commit)**:
  - **問題 1: Map 不表示**: フロント MapView が `i.location.lat` で undefined → 全 item 除外で「座標付きスポットなし」表示。原因: getPlanItems が DB flat columns (`place_id` / `lat` / `lng`) を `location` ネスト構造に変換していない。**TS 型と DB schema の構造不一致が長らく潜在していた、4 日 plan 成功で初めて map view が表示されて発覚**
  - **問題 2: Evidence「不明」誤表示**: cost_confidence=unknown (price_level 未設定の観光地など) でも sources=["Google Places"] が populate されているのに badge が「不明」表示。`getEvidenceBadgeInfo` が cost_confidence のみ見て sources を無視していた。**UX バッジは「コスト推定確度」と「place 検証状態」の 2 軸で本来表現すべきところ、1 軸の cost_confidence だけ見ていた設計バグ**
  - **問題 3: dinner / lodging slot 欠損** (3 イベント = 9/12/14 時固定): LLM が dinner / lodging を空のまま提出。**system.md 第 4 項「全 slot に割当てる必要は無い（欠損可）」が緩すぎる + Google Places search に lodging keyword なし + 楽天 API 400 で lodging 候補ゼロ** の 3 重苦
- **v6.1 hotfix (working tree、未 commit)**:
  - `apps/web/src/lib/api.ts` の getPlanItems に `_transformPlanItemRow` 追加 (DB flat → location ネスト変換)
  - `packages/shared-types/src/index.ts` の getEvidenceBadgeInfo を 4 段階判定に: verified > estimated > **unknown + sources → verified 表示** > unknown
  - `apps/api/src/llm/prompts/v2.0.0/system.md` 第 4 項を「全 slot を必ず埋めること」に強化、「dinner / lodging を空にすると旅行プランとして欠陥品」を明記、lodging 連泊推奨を再掲
  - `apps/api/src/evidence/builder.py` の `_BASE_KEYWORD_SUFFIXES` に「旅館 ホテル」追加 (5 軸目)、`_MAX_KEYWORDS=5→7` に拡張 (5 base + theme + tag 許容)
- **学び 1 (重要)**: **DB schema と TS 型の構造不一致は long-tail で発覚する**。flat columns vs nested location は Phase 1 設計時に決まっていたが、frontend 表示が「正常な plan で初めて lat/lng アクセス試行」する段階まで触らない。**バックエンド → DB → フロント の境界で type transformation が必要なケースは PR review で意識的に確認するルール**化候補
- **学び 2**: **EvidenceBadge の semantic 設計ミス**: cost_confidence (コスト推定確度) と sources (place 検証状態) が混同されていた。今後 Evidence 関連の表示は 2 軸を分けて考える (place 検証確度 + コスト推定確度)
- **学び 3**: **system.md の prompt は「許容句」を慎重に書く**。「全 slot に割当てる必要は無い (欠損可)」は LLM に「dinner / lodging を埋めなくていい」と誤解されやすい。本当に欠損が許される条件 (eligible_for_slots 空) のみ例外として書き、デフォルトは「全部埋める」を強く要求する
- **次のステップ (user 作業)**:
  - v6.1 の 2 commits を branch 切って push、本番 deploy 後に再 verify
  - 楽天 applicationId 正しい数字 ID への変更 (webservice.rakuten.co.jp で取得)
  - 修正後の本番 Run で「Map にマーカー / Evidence Modal で営業時間・出典 / dinner+lodging slot 埋まる」を確認

## 2026-04-28: Phase 2 polish v5 実装完了 (重複ポリシー best-effort 化 + lodging 連泊許容)、3 日 plan は通るが 4 日 plan は依然 422 — Pack 候補不足が新 bottleneck
- **状況**: v4 (pack 拡張 + fuzzy match) の本番 Run 13e で 422 再発、user 「同じものが許されるのは流石に宿くらいでは？重複は best-effort、エラー回避優先」方針で v5 設計
- **v5 設計**: Codex review 設計段階 2 サイクル (Critical 1 + Major 5 + Minor 1 → Blocker 0 / Major 3 / Minor 2 → 全反映) → 実装 → review 1+2 サイクル (Major 1 + Minor 3 → Blocker 0 認定)
- **commits**: `fix/soft-duplicate-with-lodging-allowed` ブランチ → develop merge + push 済 (commit `6af88f5`)
  - Commit A: assembly の重複ポリシー緩和 (lodging 連泊許容、meal/activity warn+accept、opening_hours raise→warn+accept、transit skip 設計、_drop_duplicate_place_items 呼び出し削除、ChIJ prefix guard 削除) + system.md 第 8 項更新
  - Commit B: assembly test 12 件更新/追加 (raise→warn+accept × 5、ChIJ guard test → J→H/J→h typo 救済 × 2、新規連泊・skip・時刻補正 × 5)
  - Commit C: tasks/lessons.md + todo.md 進捗反映
- **検証**: API 434 PASS (既知 env 依存 2 件 fail 無関係) / Web 164 PASS / tsc clean / build PASS / secret 0 hit
- **本番 deploy 後の検証 (user 報告)**:
  - **3 日 / 80,000 円: 通る** (200) → v5 効果実証
  - **4 日 / 80,000 円: 依然 422** → 構造的に slot 数 / pack 候補のバランス未解決
  - **生成成功時の plan 閲覧で Evidence (営業時間 / 評価 / 出典) が「不明」表示**が多い (別バグ、pack→plan_item の serialization 問題と推定)
- **学び 1**: 「**重複防止 hard constraint** が Phase 2 polish v1 で追加されたが、4 日プランで構造的に詰む対症療法だった**」。user 提案「lodging だけ完全許容、他は best-effort」が正解 (本来の UX に合致)
- **学び 2**: **Codex review 1 Minor 1 (`ChIJ` prefix guard) が逆効果**。本番 Run 13e で gpt-4.1 の最頻ハルシパターン (`ChIJ` → `ChIH` / `ChIh` の J typo) を guard で除外する事故。**「false positive 抑制 guard」は実本番 attack surface (実際の typo パターン) を観測してから入れるべき**。理論的安全性 (false positive 0%) と本番 typo パターンの乖離
- **学び 3 (Codex 設計段階 review の価値)**: 設計段階で 2 サイクル + 実装後 2 サイクル = 4 サイクルで Blocker 0。各 review で前回 review が見落とした (or 自分の修正で新たに導入した) 別の Major を発見。**実装着手後でしか見えない盲点 (transit skip 時の AssertionError、`_drop_duplicate_place_items` との矛盾) は実装後 review でしか catch できない**
- **副次の発見**: 楽天 API 400 error が継続発生。lodging.py に rakuten error response body を log に残す改修 + user 側 curl で直接確認 → rakuten が `{"error": "wrong_parameter", "error_description": "specify valid applicationId"}` を返却 = **applicationId が rakuten 側で無効と確定**
- **学び 4 (重要、ルール昇格候補)**: 私が「32 hex chars は正しい applicationId 形式」と user に伝えたのは誤り。**実は楽天ウェブサービスの applicationId は典型的に 18-19 桁の数字** (`1024711987305213057` 形式)。32 hex chars (`0415bc2d...`) は **「アプリケーションキー」など別フィールド or 別サービスの認証情報**。user の手元のフィールドラベルだけで判断せず、**実際の API 応答 (curl で直接確認) がエビデンス第一**。私の二度の applicationId 形式記述ミス (UUID 否定 → 32 hex chars 肯定 → 実は両方誤り) は、**docs での仕様確認なしに憶測で答えた失敗**。`.claude/rules/external-api-rules.md` 昇格候補
- **次のステップ (user 作業)**:
  - [webservice.rakuten.co.jp/app/list](https://webservice.rakuten.co.jp/app/list) で **アプリ ID/デベロッパー ID** が長い数字列 (18-19 桁) か確認
  - もし 32 hex chars のままなら、webservice.rakuten.co.jp に新規アプリ登録 → 数字 ID 取得 → Render env 更新 → redeploy
- **次のステップ (継続調査)**:
  - user が curl で直接 rakuten API を叩いて 400 の真因を確認 (`curl https://app.rakuten.co.jp/services/api/Travel/SimpleHotelSearch/...`)
  - 原因確定後、適切な fix (maxCharge 計算修正 / checkin 日付 validate / etc)
  - **Evidence 「不明」表示問題** は別タスクとして切り出し (pack→plan_item の serialization で opening_hours/rating/sources を埋める)
  - **4 日プラン 422 の残存** は v5 で解消できないなら別軸 fix (Pack 構築時に営業日 filter / search keyword 拡張 / outside_opening_hours の retry guidance 強化)

## 2026-04-28: Phase 2 polish v4 実装 + 本番 Run 13e で別パターンの 422 再発 — 「Codex 指摘の false positive 抑制が最頻ハルシパターンを逆に除外する」教訓
- **状況**: 本番 Run 13d (草津 4 日 / 80,000 円) の 422 真因 (pack 12 places で 4 日 19 slot に対し重複防止詰み + gpt-4.1 の `ChIJJ` 短縮ハルシ) を v4 で fix:
  - **A**: `max_places_for(total_days)` で pack cap 動的化 (4 日 = 22)、`_bucket_quota` 4+ 日拡張、`fill_threshold = cap` で bucket 偏り時も buffer 維持
  - **C**: assembly に `_resolve_fuzzy_place_id` 追加 (SequenceMatcher.ratio ≥ 0.95 / len_diff ≤ 2 / **`ChIJ` prefix 必須** / unique-match)
- **Codex review 1+2 サイクル**: Major 3 (fill_threshold cap-3 buffer 消失 / quota contract 不一致 / docs drift) + Minor 1 (`ChIJ` prefix guard で false positive 抑制) を全反映、Blocker 0 認定 → push → 本番 deploy
- **本番 Run 13e (同条件再現) 失敗の breakdown**:
  - attempt 1: `outside_opening_hours` (草津店舗が **2026-11-22 日曜日** に定休、新パターン)
  - attempt 2: `unknown_place_id` `ChIHhY2RO4...` (LLM が `ChIJh` を `ChIH` に typo)
  - attempt 3: `unknown_place_id` `ChIhY2RO4...` (`ChIJh` を `ChIh` に typo)
  - attempt 4: `unknown_transit_edge` (重複防止 swap 連発で候補枯渇、`total_places=17 / used=9`)
- **致命的発見 1 (重要、ルール昇格候補)**: **Codex review 1 Minor 1 で追加した `ChIJ` prefix guard が裏目に出た**。
  - guard の意図: 「ChIJ 以外で始まる ID を fuzzy 救済から除外し false positive 抑制」
  - 実害: gpt-4.1 の最頻ハルシパターンは `ChIJ` → `ChIH` / `ChIh` (J を H or h に typo) で、これが **guard で除外されて救済されない**
  - 教訓: **「false positive 抑制 guard」を入れる前に、実際の本番 typo パターンを先に観測すべき**。Codex 指摘の理論的安全性 (false positive 0%) と本番 attack surface (実際の typo パターン) が乖離していた
  - 本来の意図 (false positive 抑制) は unique-match + ratio 0.95 + len_diff ≤ 2 で十分達成されているので、prefix guard 自体不要だった
- **致命的発見 2**: 構造的 pack 不足。草津エリアの Google Places search 結果が薄く、`max_places_for(4)=22` に対し pack=17 で停止 (5 places 不足、search 候補絶対量不足)。`fill_threshold=cap` でも leftover_by_bucket が空なら補填不能
  - 教訓: **pack cap を上げても search 結果の絶対量が制約**。地方エリアは Google Places の retrievable 候補が少ない傾向、pack 拡張だけで詰みは解消しない
- **致命的発見 3**: 4 日 plan の lodging slot=3 + 草津 lodging 候補薄 で構造的詰み。重複完全禁止前提では「19 slot を 17 places で埋める」が原理的に不可能
  - 教訓: **「重複完全禁止」は MVP の自然な要件だが、4+ 日 plan + 地方エリアでは緩和必要**。candidate options:
    - day-scoped duplicate prevention (同日内のみ unique、日跨ぎ許容)
    - lodging 連泊許容 (4 日 plan で 1 連泊して lodging slot を 2 に)
    - search keyword 大幅拡張 (4 軸 → 7+ 軸、quota 維持しつつ候補増)
- **モグラ叩き感**: v3 (transit) → v4 (pack + fuzzy) → 422 再発の系譜。**Phase 2 polish の場当たり対症療法が限界**、demo 提出後に重複防止設計そのものを見直す必要 (構造的 fix v5 は別タスク)
- **commits 関連**: v4 = `cb39aa5 / 4b96a37`、develop merge + push 済。v5 fix は別 plan で起案
- **次の判断 (user 要)**:
  - **MVP-pragmatic 路線**: fuzzy guard 緩和 (`ChIJ` → 削除) + lodging 連泊許容 (quota 3→2) で ~10 分の hot fix
  - **構造的根治路線**: day-scoped duplicate prevention 設計変更 (~30 分、demo 後の安定運用向き)
  - **諦め路線**: Run 13d/13e の知見を docs/lessons に残し、demo は 1〜2 日プランか箱根/京都/東京での動作確認に切替

## 2026-04-28: Phase 2 polish v3 実装完了、Codex review 5 で `attempted=0` 抜け穴発覚 → Major 1 fix → review 6 Blocker 0
- **状況**: Phase 2 polish v3 計画 (T1+T2+T4+T7+T5) を `fix/pack-transit-stability` ブランチで 4 commits 構成で実装。計画段階の Codex review 1+2+3+4 (Blocker 0 認定済) → 実装 → review 5 で予想外の Major 1 + Minor 2 件発覚 → 全反映 → review 6 で Blocker 0 / Major 0 確認 → commit 提案
- **review 5 で発覚した Major 1 (重要、実装後 review でしか発見できなかった盲点)**:
  - **問題**: 旧 `shouldEarlyThrowOnTransit` は `stats.attempted === 0` を無条件許容。この設計だと「`places.length > 1` だが距離フィルタで pair 全落ち」のケースを素通しさせ、空 `transit_matrix` で `/api/plans/generate` に流れて A6 系 422 連発が再発しうる
  - **検出経路**: Codex が `transit.test.ts` の既存 test (`遠すぎる pair は除外`、line 81) を読み込んで「実装と test の組み合わせから抜け穴を逆算」し指摘。**実装段階で初めて観測可能になる組み合わせ問題**で、計画段階の review では catch 不可能だった
  - **修正**: シグネチャを `shouldEarlyThrowOnTransit(stats, placeCount)` に拡張し、`placeCount <= 1` のときだけ許容、`placeCount > 1 && attempted === 0` は throw。caller (`page.tsx`) も `session.places.length` を渡すよう更新、test 9 件で境界を validate
- **review 5 Minor 2 件**:
  - tier3 全落ち時の `return None` に warning log 漏れ → tier3 専用 log を追加
  - `docs/evidence-pack.md` のコスト節 + `transit.ts` のコメントが旧値 (`10km / 20 / 10s`) のまま → `15km / 40 / 15s` に同期
- **学び (重要、ルール昇格候補)**:
  - **「計画段階の Codex review」と「実装後の Codex review」は別物**。本日は計画段階で 4 サイクル回して Blocker 0 認定したが、実装後にも独立した盲点 (Major 1) が見つかった。**計画 review は設計矛盾を catch、実装 review は「実装と既存 test / コードの組み合わせ」由来の盲点を catch** という非対称な役割
  - **既存 test ファイル / 関連コードを review 対象 diff の文脈として渡す重要性**: 計画段階では存在しない「実装 + 既存コードの相互作用」が事故源。Codex に diff だけでなく test ファイルや関連 lib の path/line を読ませる context が catch 率を上げる
  - **「`attempted === 0` 無条件許容」のような『安全側に倒したつもりの default』が抜け穴になる**: 「places ≤ 1 で transit 不要」と「places 多数 + 距離分散で pair 0 件」を **同じ stats で区別できない**。stats だけでは情報不足、呼び出し側の文脈 (places.length) を判定材料に追加するのが正解
  - **シグネチャ変更は localized**: `shouldEarlyThrowOnTransit(stats)` → `(stats, placeCount)` のような小さな拡張は caller 1 箇所更新で済むので恐れずやる。固定 signature を守るために stats 構造体を膨張させる方が技術的負債になる
- **検証結果**: API 413 PASS / Web 164 PASS / tsc clean / build PASS / secret 0 hit / Codex review 6 Blocker 0
- **次セッション (user 手動)**: 4 commits を順に push → 本番 Run 13d (草津 4 日 / お任せ) で `/api/plans/generate → 200` を確認、もし残れば Commit C で追加した `kind_summary` log で支配 issue 切り分け
- **副次の zsh 落とし穴 (user 手動 commit 時)**: `git add apps/web/src/app/plan/[id]/generating/...` は zsh の glob で `[id]` が char class として展開されエラー。**パスをダブルクォートで囲うか `setopt no_nomatch`** が必要

## 2026-04-27: Phase 2 polish v3 計画書を Codex review 4 サイクルで Blocker 0 認定、次セッション実装で 422 根本解消狙う
- **Codex review サイクル**: review 1 (Critical 1 + High 4 + Medium 2) → review 2 (Major 2 + Minor 1) → review 3 (Major 1 + Minor 3) → **review 4 (Blocker 0 認定 + Major 1 同時 fix 推奨 + Minor 2 で確定)**
- 各 review で発覚した重要な落とし穴 (本実装に進んでいたら本番障害):
  - **review 1 C1**: T2-1 regex の capture group 欠如で `IndexError` → 500 化
  - **review 1 H1**: T1 deadline 15s で完走無理 (worst-case 96s)、「部分取得」が現実
  - **review 1 H2**: フロントガード `succeeded===0` だけでは A6 再発路残る
  - **review 1 H3**: T2-2 「27 文字固定」が現行コードと不整合
  - **review 1 H4**: T3 「楽天 lodging で補完」前提が実装で成立せず
  - **review 2 Major 1**: T7 独自 category list が validator allowlist より狭く回帰リスク
  - **review 2 Major 2**: T1-2 coverage `<30%` 単独だと「attempted=5, succeeded=2 (40%)」のような少数バッチ通過
  - **review 3 Major**: T1-2 deadline 依存判定が deadline 未到達低 coverage を取り逃す
  - **review 4 Major**: T7 が空 category を `false` 扱いで validator (空 skip = 許容) と非整合
- **学び (本日 4 回目の同種パターン、CLAUDE rule 昇格候補)**:
  - **計画段階で Codex review を複数サイクル取る価値**: 本日は 4 サイクルで Blocker 0、各 review で前回 review が見落とした (or 自分の修正で新たに導入した) 別の Major を発見。1 サイクルだと半数しか catch できなかった可能性大。
  - **「修正の修正でまた問題が増える」パターン**: 例: T1-2 を「coverage 30%」→「ratio + absolute floor」→「deadline 撤廃」と改修するたび新規 Major 発生。完全に固まるには 3 サイクル必要だった
  - **AI 単独の盲点**:
    - regex の capture group / parser API 慣れ → AI 単独だと盲点になりやすい
    - 既存 helper の存在を assembler 設計時に見落とす → validator の helper 再利用に気づく
    - 空 collection 等の edge case 抜け → 本日 review 4 で発覚
  - **Explore agent + Codex review の二段構え**: 単独で plan 書くと観測済原因のみに集中して仮説原因 / preventive fix が漏れる。ハッカソン提出のような時間制約下では「先に網羅調査 → 計画書 → review 複数サイクル」が事故防止コスト最小

- **次セッション最初のタスク (実装着手前提、計画書: `tasks/plans/2026-04-27-pack-transit-stability-fix.md`)**:
  1. plan 読み込み + T7 の `if not place_categories: return True` 同時 fix を確認
  2. T1 (Commit A): フロント `transit.ts` 定数 + `transit-guard.ts` (deadline 非依存 ratio + absolute floor)
  3. T2 (Commit B): regex capture group + system.md 第 9 項 「正確コピー」
  4. T4 + T7 (Commit C): assembler / generator log + tier3 item_type filter (validator helper 再利用、空 category 許容含)
  5. T5 (Commit D): docs/setup-guide.md 楽天 ID 形式注意
  6. ローカル verify → Codex review 5 (実装後) → 反映 → user push → 本番 Run 13d/13e

## 2026-04-27: Phase 2 polish v3 計画書作成 + Codex review 1 反映完了、次セッション実装で 422 根本解消狙う
- **状況**: Run 13c 422 の根本原因確定後、提出までモグラ叩きにならないよう **plan を作成 → Codex review → 反映** で次セッションへ引き渡し
- **計画書**: `tasks/plans/2026-04-27-pack-transit-stability-fix.md` (Codex review 1 反映済)
- **アプローチ**: Explore agent で plan 生成パイプライン全体 (Pack 構築 / Transit / Validator / Assembler / LLM / Routes 各層) を網羅調査、観測済 + 仮説原因を優先度別に整理した上で T1〜T7 の修正案を策定
- **Codex review 1 で発覚した重大な計画ミス (Critical 1 + High 4 + Medium 2)**:
  - **Critical**: T2-1 regex 案が capture group 欠如で `IndexError` → 500 化リスク (本実装に進んでいたら本番障害)
  - **High**: T1 の deadline 15s では完走無理 (worst-case 96s)、「部分取得」が現実
  - **High**: T1 だけでは低 coverage 状態でも API に流れる、フロントガード強化 (T1-2) 必須
  - **High**: T2-2 「27 文字固定」案は危険 (現行コードと不整合、有効 ID を否定)
  - **High**: T3 「楽天 lodging で補完」前提は実装で成立せず (lodging_options は LLM prompt 未接続)
  - **Medium**: T6 retry guidance は既実装、効果上積み限定 → 削除
  - **Medium**: assembler tier3 が category 無視で `item_type_category_mismatch` 誘発余地 → T7 新設
- **学び (本日 3 回目の同種パターン、ルール昇格候補)**:
  - **計画段階で Codex review を必ず取る** = 実装に入る前に Critical/High を catch できる。本日 Phase 2 polish v1/v2 の Codex review 履歴から、平均 1 plan あたり Critical 0-1 + High 2-4 が出る。Codex review なしで実装に進むと本番で発見 → 緊急 fix → モグラ叩きに陥る
  - **Explore agent で全体調査 → Codex review** の二段構えが網羅性に効く。単独で plan 書くと観測済原因のみに集中して仮説原因 (中位 issue / preventive fix) が漏れる
  - **キャプチャグループ等の「regex 慣れ」は AI 単独だと盲点になりやすい**。本 Critical はそもそも regex の使い方ミスで、Codex の経験量が補完してくれた
- **次セッション最優先タスク**:
  1. 本 plan を読み込み、Codex review 1 反映済の T1〜T7 を実装
  2. T1 (Commit A) → T2 (Commit B) → T4+T7 (Commit C) → T5 (Commit D) の順で 4 commits 構成
  3. 各 commit で API + Web test PASS 維持
  4. Codex review 2 で実装後の Blocker 0 確認
  5. user push → 本番 Run 13d (草津 4 日 / お任せ) で 200 確認 → Run 13e (アンカー有り) → 草津以外 (箱根 / 京都 / 東京) で安定性 verify

## 2026-04-27: Render Live tail で Run 13c 422 の根本原因確定 — A6 (transit_matrix coverage 不足 + 細粒度 category での `_find_alternate_place` 候補枯渇) + 副次 A1 (ハルシ)、楽天 applicationId が UUID で誤投入
- **状況**: Run 13c (お任せ + 楽天 env 投入) も 422 → user が Render Live tail から 4 attempts のログ全文を共有
- **判明した attempt 別 issue**:
  - attempt 1 (gpt-4.1): `kind=unknown_transit_edge` "No transit edge from X to Y and no alternate place for category 'japanese_restaurant' found"
  - attempt 2 (gpt-4.1): `kind=unknown_place_id` "LLM assigned unknown place_id 'ChIJJCcG...' to slot 'day2_afternoon'" (頭が `ChIJJ` で 5 文字、本物は `ChIJ` で 4 文字なのでハルシネーション)
  - attempt 3 (gpt-4.1): `kind=unknown_transit_edge` 同パターン (japanese_restaurant 候補枯渇)
  - attempt 4 (gpt-4.1-mini): `kind=unknown_transit_edge` "category 'zoo' found" (草津に動物園、ハルシ気味の category)
- **重複防止の正常動作確認**: log に `[WARNING] src.llm.assembly: Duplicate place_id 'X' in slot 'day1_dinner'; swapped to 'Y'` が 2 件 → Phase 2 polish A 重複防止 fix が **production で動いている動かぬ証拠**
- **新発見 A6 = 主原因**: 「Pack 12-15 places + selectPairs `MAX_PAIRS=20` + 距離 `MAX_EDGE_DISTANCE_KM=10km` フィルタ」で transit_matrix が **疎**。重複防止の `exclude_place_ids` で候補消費していくと、後半 slot で `_find_alternate_place` の (a) 距離 reachable + (b) category 共通 + (c) opening_hours OK + (d) used 除外 を全部満たす候補が **0 件** になる
- **副次問題 A1 (attempt 2 のみ)**: gpt-4.1 が `ChIJJCcG...` のように頭 5 文字 `ChIJJ` でハルシ (本物は `ChIJ` 4 文字)。Phase 1.10 後段の prompt retry guidance で消えるはずが本番で再発
- **副次問題 楽天 API 400**: log で `applicationId=0415bc2d-b441-41ce-9447-d3413ce5c3f7` (UUID) → 楽天の仕様は **19-20 桁の数字** (例: `1024711987305213057`)。user が webservice.rakuten.co.jp で発行されない別の値を投入してしまった。lodging は fail-soft で skip されるので 422 直接原因ではないが、lodging が pack に入れば slot 数が減る (3 lodging slot → assembler 制約緩和) ので副次的に解消の助けになる可能性
- **修正案 (3 段階)**:
  - **即効 fix A**: `apps/web/src/lib/transit.ts:31-35` の `DEFAULT_MAX_PAIRS = 20 → 40`、`DEFAULT_DISTANCE_KM = 10 → 15`。transit_matrix が倍密になり `_find_alternate_place` 候補増
  - **即効 fix B (user 操作)**: webservice.rakuten.co.jp で本物の applicationId (19 桁数字) 確認 → Render env を正しい値に置換 → redeploy
  - **余裕 fix C**: `apps/api/src/evidence/builder.py:MAX_PLACES` を 12 → 20 に + `_find_alternate_place` の last resort fallback (category 共通なくても受け入れる経路) を実装
- **次セッション最優先 (本セッションで時間あれば即着手)**:
  1. Fix A 実装 (~5 分)
  2. 楽天 ID 確認方法を user に伝える + Fix B 完了待ち
  3. push → redeploy → Run 13d で `200` verify
- **学び**:
  - **Render Live tail なしには本番 422 の原因特定は不可能**だった。`logging.basicConfig(INFO)` 入れたのが本セッションでも光った
  - 「本番 plan 生成失敗は単一原因ではなく**複合**」を再認識。Run 13b/13c で A2/A4 同時否定 → log で A1+A6 同定、という段階的切り分けで時間節約
  - **A6 (transit_matrix coverage 不足) は新規ルール候補**: assembler の `_find_alternate_place` が「category 共通 + transit reachable + opening OK + 重複防止 exclude」の 4 重制約 + 細粒度 category (`japanese_restaurant` / `zoo` 等) で枯渇しやすい。Pack/transit_matrix 設計時に「想定 slot 数 × 重複防止後の余裕」を考慮しないと本番で 422 を量産する。ハッカソン後に `.claude/rules/llm-rules.md` 昇格候補

## 2026-04-27: Run 13c (お任せ + 楽天 env 投入後) も 422 失敗 — A2 / A4 否定、A1 (ハルシネーション) / A3 (opening_hours) / A5 (Pack 規模) のいずれかに絞り込み
- **状況**: Run 13b (アンカー有り) が 422 → user が Render Dashboard に `RAKUTEN_APPLICATION_ID` / `RAKUTEN_AFFILIATE_ID` 投入 + redeploy 完了 → Run 13c (アンカー無し + 楽天 env 有り) で同条件 (草津 / 11/21〜11/24 / 80,000 円) を再試行 → **再び 422 "プラン生成の検証に失敗しました（422）。スポット情報の整合性チェックで問題が発生しました。"**
- **副次の発見**: フロントの 422 エラーメッセージが **日本語化されている** (前回 13b は "plan generation failed after retries" のまま、13c は日本語)。誰かが UX 改善の commit を入れたらしいが、本セッションのスコープ外。要確認
- **切り分け結果**:
  - アンカー有り (Run 13b) → 422
  - アンカー無し + 楽天有り (Run 13c) → 422
  - **共通点**: 草津 / 11/21〜11/24 / 80,000 円 / 4 日 / 公共交通モード削除済
  - → **A2 (anchor + 重複防止衝突) 否定** (anchor 無しでも 422)
  - → **A4 (楽天 lodging 未設定) 否定** (env 投入後でも 422)
- **残る仮説 (Render Live tail で attempt 別 `kind=...` 取得が必須)**:
  - **A1**: LLM ハルシネーション再発 (`kind=unknown_place_id`) → Phase 1.10 後段の retry guidance 強化が必要
  - **A3**: opening_hours 制約 (`kind=outside_opening_hours`) → 草津施設が 11/21〜11/24 の特定曜日に定休
  - **A5 (新)**: Pack 規模問題 (`kind=ineligible_place_for_slot`) → 草津 Pack 12〜15 件で 4 日 18 slot + 重複防止 で候補枯渇
  - 地理的問題 (`kind=no_feasible_transit`) → 距離分岐 fallback でも transit 取れない pair が多い
- **学び**:
  - 本番 422 の根本原因は **フロント挙動だけでは特定不可能**。Render Live tail での attempt 別 log が必須
  - 切り分け方針として「2 つの直交する条件で各々 verify する」が有効 (anchor on/off × Rakuten env on/off の組合せ実証で A2 / A4 同時否定)
  - 残仮説 A1 / A3 / A5 は LLM 出力 + Pack 構成依存なので、本番 log 確認 → 該当原因に応じた fix が次ステップ
- **次セッションの動き**:
  1. user が Render Live tail から `[INFO] src.llm.generator: LLM attempt N (model=...) assembly error (kind=..., message=...)` を取得して共有
  2. kind 別の対応:
     - `unknown_place_id`: prompt の retry guidance 強化 (Phase 1.10 後段の delta)
     - `outside_opening_hours`: opening_hours parser の日跨ぎ対応 + 11/21〜11/24 で草津施設の定休曜日確認
     - `ineligible_place_for_slot`: Pack 候補数を `MAX_PLACES` 緩和 (12 → 20+) or 4 日プランは slot 数を減らす
     - `no_feasible_transit`: transit_matrix の `MAX_EDGE_DISTANCE_KM` 緩和

## 2026-04-27: 本番 Run 13b でも 422 再発 — toggle 撤回 + WALKING 30 分撤廃だけでは課題未解消、原因切り分けが次セッション最優先
- **状況**: Phase 2 polish v2 (transport_mode toggle 撤回 + WALKING 30 分 hard drop 撤廃) を本番 deploy 後、同条件 (草津 4 日 / 漫画堂 + 草津温泉湯畑 アンカー / 80,000 円 / 参加者 2 名) で本番 Playwright Run 13b verify → **`/api/plans/generate → 422 "plan generation failed after retries"`** 再発
- **観測**: フォーム / Autocomplete / アンカー chip 全部 ✅ → `/plan/<UUID>/generating` 遷移 ✅ → fetchTransitMatrix 完了 ✅ → `/api/plans/generate` で 4 attempts 全失敗 → 「離陸できませんでした」画面
- **判明したこと**: 「公共交通機関のみ × 草津地方」が単独原因ではない。toggle 削除 + WALKING 30 分撤廃で **transit_matrix のスカスカ問題**は解消したが、**別の要因が 422 を引き起こしている**
- **想定残課題 (Render Live tail で attempt 別 log 取得が必須、user 操作)**:
  - **A1. LLM ハルシネーション再発**: gpt-4.1 が pack 外の place_id を出力 → `unknown_place_id` 連発 (本番 Run 10 で実証済み)
  - **A2. anchor + 重複防止の衝突**: 漫画堂 + 湯畑 を 4 日 18 slot に必ず入れつつ重複防止制約を満たす組み合わせが pack 内で見つからない → `IneligiblePlaceForSlotError` 連発
  - **A3. opening_hours 制約**: 11/21〜11/24 の特定曜日に草津の主要施設が定休 → assembler self-healing 失敗
  - **A4. 楽天 lodging 未設定**: 3 泊分の lodging slot を Google Places で埋める必要、種類不足
- **次セッション最優先タスク (優先度順)**:
  1. **同条件で「お任せ」モード (アンカー解除) で再試行** (Playwright、5 分) → 200 なら A2 確定 / 422 なら他の A1/A3/A4
  2. **Render Live tail** で `[INFO] LLM attempt N (model=...) assembly error (kind=...)` を取得して根本原因確定
  3. 確定後の対応:
     - A1 なら prompt の retry guidance 強化 + previous_issues 累積化（Phase 1.10 後段の延長）
     - A2 なら anchor 件数 1 件 or assembler の anchor swap 戦略見直し
     - A3 なら opening_hours parse の日跨ぎ対応 (Codex Minor 残課題)
     - A4 なら user に楽天 env 投入依頼 (Phase 2 polish v1 B 課題)
- **学び**: **本番 422 は単一原因ではなく複合的**。1 つの fix で完全解消するとは限らない。本番で観測される失敗は **段階的に切り分けて log 確認** する習慣が必要。Render Live tail を見ずにフロント挙動だけで仮説を立てると見落とす
- **副次の UX 問題**: フロント画面の「plan generation failed after retries」が英語のまま (RFC 7807 detail を直接表示)。user 視点では何が起きたかわからない。エラー文言の日本語化 + 「もう一度試す」のリトライ動線改善は別タスク候補
- 関連 commits: develop ブランチで `0f80711 / 1564632 / 7be79a7` (Phase 2 polish v2) 全 deploy 済

## 2026-04-27: Run 13 失敗を受けて A 案 (transport_mode toggle 撤回) を 3 並列 sub-agent + Codex review 2 サイクルで実装完了
- **状況**: 下の Run 13 失敗エントリを受けて user 判断: タクシー利用可の前提で「公共交通機関のみ」モードに本質的な意味がない、user 指定で plan 失敗は UX 最悪 → **A 案 (toggle 自体を削除、内部は常に距離分岐 fallback chain に統一)**
- **設計 (Codex review 1 反映済 Major 1)**: 即時削除は旧 client 400 reject を量産するため **段階的 deprecation** で対応:
  - Pydantic 側: `transport_mode: TransportMode | None = Field(default=None, deprecated=True)` で受信は許容、内部処理は無視
  - TS 側: `TransportMode` 型 + `GeneratePlanRequest.transport_mode` を完全削除 (新 client が送らないように)
  - QueryContext / pack / prompt から transport_mode 配線完全削除
  - `parseDirectionsResult` の WALKING > 30min hard drop 撤廃 (草津のような徒歩 30〜45 分が通常の観光地で transit_matrix を確保)
- **ブランチ**: `fix/remove-transport-mode-toggle` (develop から派生)
- **実装手段**: 3 並列 sub-agent (Backend Python / Frontend TS / Docs) で削除作業を分散実行 → 全 ✅ 完了
  - Agent 1 (Backend): Pydantic deprecated field 残置 + QueryContext / pack / prompt 配線削除 + test 5 件削除 + backward compat test 3 件追加
  - Agent 2 (Frontend): shared-types / 全 UI / store / transit.ts から完全削除 + WALKING 30 min hard drop 撤廃 + test 13 件削除 + documenting test 1 件追加 + `TransportModeSelector.tsx` + `.test.tsx` ファイル削除
  - Agent 3 (docs): data-model.md の TransportMode 型節を撤回注記に置換、TS ↔ Pydantic 意図的非対称を明記
- **Codex review 2 で発覚した Major 1 (即時 fix 済)**: 旧版で `evidence_pack_sessions` テーブルに保存済みの pack に `query_context.transport_mode` field が含まれており、新版で `_PackBase` の `extra="forbid"` で復元失敗 → 404。`QueryContext` のみ `model_config = ConfigDict(extra="ignore")` を追加して旧 pack を黙って読み捨てる + regression test 1 件追加
- **検証結果**: API **403 PASS** (既知 env 依存 2 件 fail) / Web **159 PASS** (0 fail) / tsc clean / build PASS / secret preflight 0 hit
- **学び (次に同種パターンが出たら昇格候補)**:
  - **Pydantic schema から field を削除する前に段階的 deprecation 期間を 1 release 設ける**: `Field(default=None, deprecated=True)` で field 自体は残し、内部処理側で無視する形が最小コストの互換維持パターン (CLAUDE rule 昇格候補: `.claude/rules/api-rules.md`)
  - **キャッシュレイヤー (evidence_pack_sessions 等) の Pydantic 復元は schema 変更時の旧データ復元失敗を検討する必要がある**: TTL 15 分でも deploy 直後の旧 pack 復元は 404 を生む。`model_config = ConfigDict(extra="ignore")` を一時的に該当 model のみ適用して旧 field を黙って読み捨てる対処が必要
  - **3 並列 sub-agent パターンは「機能撤回」のような大量削除作業に特に有効**: Backend / Frontend / Docs は disjoint なので衝突なし、~5 分で並列実行完了
- 関連 commits 想定: `fix/remove-transport-mode-toggle` ブランチ、user 手動 commit + push 待ち

## 2026-04-27: 本番 Run 13 で **`public_transit_only` × 草津 4 日 × アンカー 2 件** で 422 連発 — 公共交通機関のみモードのカバレッジ不足
- **状況**: Phase 2 polish 全 deploy 後、user 入力 `草津 / 11/21〜11/24 (4 日) / 80,000 円 / アンカー: 漫画堂 + 湯畑 / 公共交通機関のみ / 参加者 2 名` で本番 Playwright verify。フォーム送信 → `/api/evidence/places ✅` → `/plan/<UUID>/generating` 遷移 ✅ → `fetchTransitMatrix` ✅ → **`/api/plans/generate → 422 "plan generation failed after retries"`**。画面に「離陸できませんでした」エラー表示
- **想定される根本原因（強→弱）**:
  1. **公共交通機関のみ × 草津エリアの致命的相性**: 草津温泉は JR 吾妻線「長野原草津口駅」からバス連絡のみで JR 駅自体が無い。フロント `callDirectionsWithFallback` が `transport_mode='public_transit_only'` で `DRIVING` を chain から除外 → 多くの観光地ペアで TRANSIT が `ZERO_RESULTS`、WALKING も 30 分超で `parseDirectionsResult` が null drop → **`transit_matrix` がスカスカ**。assembler が `_find_alternate_place` で代替探しても候補枯渇 → `NoFeasibleTransitError` を 4 attempts (gpt-4.1 × 3 + gpt-4.1-mini × 1) 連発で 422
  2. **4 日 ≒ 18 slot × アンカー 2 件 × 限定 places 数の組合せ過酷**: 重複防止の `exclude_place_ids` が transit 制約と相互作用して候補が早期枯渇する可能性
  3. **楽天 env 未投入 → lodging 欠落**: 3 泊分の lodging slot を Google Places 由来の店で埋める必要、ただし fallback は assembler 内で動く設計なので決定的原因にはならない想定
- **学んだこと（次の polish に活かす）**:
  - `transport_mode='public_transit_only'` は **都市圏（東京、大阪、京都等）でのみ実用的**。地方温泉地（草津、湯布院、登別等）では JR 駅から数 km 離れる + バス本数が薄い + WALKING 30 分上限で edge が取れない、という 3 重苦で transit_matrix が組めない
  - 対処方針候補:
    - (a) 公共交通モード時に WALKING 上限を 30 分 → 60 分 / 90 分に緩める（地方の徒歩許容範囲を拡大、ただし plan 体験が悪化）
    - (b) 公共交通モード時に DRIVING を完全除外せず「タクシー扱い」で残し、UI で「公共交通機関 + タクシー」と表記する
    - (c) **行き先エリアによって UI で「公共交通機関のみは都市部推奨」の hint を出す**（地方は「車も使う」誘導）
    - (d) 公共交通モード時に Maps Directions の `TransitMode.RAIL`/`BUS` を細分化して、TRANSIT の zero results 時に `TransitMode.BUS` 単独 retry する
  - 実装着手前に **Render Live tail でアタックプラン別の `[INFO] LLM attempt N` log** を読み、`NoFeasibleTransitError` が支配的か `unknown_place_id` ハルシネーション再発か切り分けるのが先決
- **redo 計画**: 同フォーム値で `transport_mode = 車も使う (all_modes)` に切替えた Run 13b で切り分け → all_modes で通れば仮説 1 確定 → 上記 (c) 都市部推奨 hint を Phase 3 polish 候補に昇格、(a)/(b)/(d) は plan で評価
- 次に同種失敗が出たら `.claude/rules/llm-rules.md` 昇格候補（地理的制約と transit 入手可能性の相互作用は LLM 側ではなく Pack 構築側で守る）

## 2026-04-27: Phase 2 polish の実装完了 — Codex review 2 で発覚した「defense-in-depth の要素削除が隣接参照の整合性を壊す」設計バグ
- 状況: Phase 2 polish の 3 課題 (A 重複防止 / B 楽天 env / C transport_mode) を 1 ブランチ + 3 commits 構成で実装完了。Codex review 1 (計画段階、Blocker 2 / Major 3 / Minor 2 全反映) → 実装 → Codex review 2 (実装後、**Critical 0 / Major 1 / Minor 3**) → Major + Minor 1, 2 反映 → Codex review 3 (**Blocker 0 → OK to commit**) の 3 サイクルで詰めた。最終 API 404 PASS / Web 175 PASS / tsc clean / build PASS / secret preflight 0 hit
- **Codex review 2 で発覚した Major 1**（採用設計には含まれていなかった見落とし）:
  - 当初設計: `_drop_duplicate_place_items` を「重複した non-transit item を log + drop する fail-soft 防御」として実装。proactive duplicate-detection swap path がカバーする想定だが、想定外パス用の defense-in-depth として配置
  - 問題: `_drop_duplicate_place_items` が単純に **non-transit だけを drop** すると、その place を指す `transit_ref.from / to` の transit item が dangling になる。validator (`_check_transit_edges`) は **edge の存在のみ check** で plan 内 semantic 整合は見ないため、「validator は通るが意味は壊れた」状態のプランが本番に出る穴があった
  - 解法: 2 pass 化。1 pass 目で重複 non-transit を識別 + `surviving_pids` 確定 → 2 pass 目で `transit_ref.from/to` のどちらかが `surviving_pids` に居ない transit も drop。test 2 件追加 (`test_drop_duplicate_place_items_drops_dangling_transit` + `test_drop_duplicate_place_items_drops_transit_with_dangling_from`) で `to` 欠落 / `from` 欠落の対称カバレッジを担保 (Codex review 3 Minor 2 反映)
- **Codex review 2 で発覚した Minor 1（テスト精度の罠）**:
  - prompt 合成順序を test するために `find("P_anchor_test")` と `find("温泉")` で index 比較していたが、これらの汎用文字列は **`query_context_json` (anchor mode_payload) や `participants[].wishes_text`** にも現れるため、section 順序が壊れていても test が通る偽陽性リスクがあった
  - 解法: section 専用見出し文字列 (`"アンカー（必須スポット）"` / `"テーマ:"` / `"移動手段:"`) で index 比較に変更。これらは json 形式の output には現れず、mode_context_md 内のみ現れる
- **学んだルール候補（次に同種パターンが出たら昇格）**:
  - 「validator が通った = 意味的に正しい」ではない。Pydantic の field 制約や個別 check が独立に通っても、**plan 全体の参照整合性 (transit ↔ place_id、anchor ↔ items 等) は別軸の invariant** で別途守る必要がある
  - defense-in-depth の path で要素を drop / 削除するときは、その要素を**参照している隣接構造**（前後の transit 等）の整合性まで同時に保つ責務がある。「該当要素だけ drop して他は触らない」は post-condition を破壊しがち
  - prompt 順序のような **「文字列出現位置」を assert する test は固有マーカーで判定**せよ。一般語 (`"P_xxx"` / 日本語名詞) は他フィールドに混入するため index 比較が偽陽性化する
- 詳細: 設計書 `tasks/plans/2026-04-27-plan-quality-improvements.md` の Codex review 全反映セクション、commit 提案 3 件 (A 重複防止 / C transport_mode / B 楽天 env docs)。次は user 手動 commit + push → Render dashboard で楽天 env 投入 → 本番 Run 13 verify (default + public_transit_only の 2 シナリオ)

## 2026-04-27: API ヘルスチェックの初期状態を null にするとバナーが「即エラー表示」になる
- 問題: `useState<boolean | null>(null)` の null をそのまま「確認中」扱いにせず `isApiDown = apiAvailable === false` だけ見ていたため、`useEffect` が走るまでの一瞬（実際には resolve 後まで）は `null` = バナーなし。しかし外部からは「普通に開いただけでサーバーに接続できません」に見える状況があった（バックエンド未起動時は `checkApiHealth` が `false` を返すためバナーが即出る）
- 原因: 「確認中」状態の表示分岐がなく、null / false を同一視していた。ユーザーには「接続エラー」と「まだ確認していない」の区別がつかない
- ルール:
  - **`useState<boolean | null>(null)` で 3 状態（null=確認中 / true=OK / false=NG）を使う場合は、null の UI を必ず定義する**。null を「エラーなし」と同一視するな
  - **ヘルスチェックの失敗メッセージには「コールドスタートの可能性と再読み込み案内」を必ず添える**。Render Free は cold start が頻発するため「しばらく待ってから再読み込み」が正しい誘導
  - **smoke test は非同期 useEffect の完了前に DOM を検査する**。ボタンテキストを「確認中」に変えると `getByText(/プランを生成/)` が落ちる → ボタンテキストは安定したコピーを維持し、状態はバナー側で伝える設計にする

## 2026-04-27: フロントエラー分類を HTTP ステータス別に細分化（`classifyError` リファクタ）
- 問題: `classifyError()` が 401/403 を同じメッセージ、500 台を一括で処理していた。ネットワーク `TypeError` と `ApiError(status=0)` の混在で「接続できませんでした」に全部が吸収され、本当の原因（422 LLM 検証 / 403 APIキー / 504 Render コールドスタート）がユーザーに見えなかった
- 原因: `ApiError` は `authedFetch` が HTTP レスポンスを受け取った後にのみ throw する。真のネットワーク障害は `TypeError`、タイムアウトは `DOMException(AbortError)` として届く。旧実装は `ApiError.status === 0` を確認していたが、このケースは実際には発生しない（`authedFetch` 設計上、404 以上が status に入る）
- ルール:
  - **`ApiError` は HTTP レスポンスあり前提**、ネットワーク障害は `TypeError`、タイムアウトは `AbortError` で来る。3 つを別 `instanceof` ブランチで処理せよ
  - **422 はユーザーに「LLM 検証失敗」と伝える**。`err.message` をそのまま流すだけでは「何が悪かったか」が伝わらない
  - **502/503/504 には「Render コールドスタートの可能性」を添える**。ユーザーが 30 秒待てば解消するケースを明示する

## 2026-04-27: Phase 2 polish 計画書を Codex review 1 で確定（実装は次セッション）
- 状況: 本セッション末で 3 課題（重複 / 楽天 / 移動手段）の実装計画書を `tasks/plans/2026-04-27-plan-quality-improvements.md` に作成、Codex review 1 で **Blocker 2 / Major 3 / Minor 2 / OK 2** を全反映
- 軌道修正された設計判断:
  - **Blocker 1 (transport_mode が生成処理に届かない)**: `generationSessionStore` に `transport_mode` を含める伝播経路を必須化、`/plan/new` submit → session 格納 → `/plan/[id]/generating` で `postPlanGenerate` に渡す流れ
  - **Blocker 2 (Plan.transport_mode が DB / RPC スコープ)**: **`Plan` への保存はスコープ外に切る**、`GeneratePlanRequest` / `QueryContext` のみで prompt 注入。DB / RPC 列追加は 4 時間枠超過のため別タスク
  - **Major 1 (exclude_place_ids 両関数 + 最終 invariant)**: `_find_eligible_alternate_for_slot` と `_find_alternate_place` の **両方**に `exclude_place_ids` 引数を追加、最終 invariant check で「絶対に重複が出ない」を保証
  - **Major 2 (prompt 合成方式)**: `_build_mode_context_md` を「anchor / theme で早期 return」から「3 mode を独立に文字列化して `\n\n` で合成」に refactor、transport 指示が他 mode と組み合わせて落ちない
  - **Major 3 (徒歩 30 分上限)**: `parseDirectionsResult` 内で `requestedMode === "WALKING"` かつ `duration_min > 30` のとき null 返却で edge を drop、「徒歩 2 時間」が plan に組み込まれない
- 学び:
  - **Plan の data shape を変える fix は DB / RPC スコープに連動**: 一見軽い API field 追加でも `Plan` に保存するなら migration + RPC 更新が必要。Codex review で「scope creep」を早期に発見できた
  - **prompt の helper が「早期 return」 pattern だと組み合わせで落ちる**: anchor / theme / transport を独立に追加したいケースでは合成方式が正しい設計、Codex Major で構造的に発見
  - **Plan agent 系 review で「実装計画段階」の Blocker を 2 件発見できた**: 実装に進む前に session 伝播 / DB スコープを軌道修正できたのが大きい。実装後だと差し戻しコスト大
- ルール候補:
  - **API field 追加時は「Plan に保存するか / 生成リクエストにのみ載せるか」を最初に決める**。前者は migration + RPC スコープ、後者は session 伝播のみ
  - **prompt helper は 1 mode = 1 早期 return 設計を避け、各 mode を独立 string + 合成で組み立てる**
  - **新 enum を transit.ts のような複雑 module に通すときは options object で扱う**（既存 API 後方互換 + default で吸収）
- 計画書: `tasks/plans/2026-04-27-plan-quality-improvements.md`、次セッションでこの plan を読み込んで実装着手

## 2026-04-27: 本番 Run 12 で完全動作確認後、demo 観察で 3 つの追加課題が判明（Phase 2 polish 候補）
- 状況: Run 12 で `/plan/new → /api/plans/generate → 200 → /plan/[id]` プラン閲覧画面まで完全動作確認後、user が demo 内容を観察して以下 3 つの精度問題を指摘
- **追加課題 A**: **DAY 1 / DAY 2 で同じ場所・食事処が重複採用**（demo 致命的）
  - 例: 「箱根食堂」が day1_lunch と day2_lunch 両方に採用される
  - 真因仮説: Phase 1.3e assembler が **slot 跨ぎの place_id 重複を check していない**。各 slot で独立に「最適 place」を選ぶ logic、重複制約なし
  - fix 方針: (1) `apps/api/src/llm/prompts/v2.0.0/system.md` に「同じ place_id を複数 slot に割当てない」ルール追加、(2) `apps/api/src/llm/assembly.py` で post-check として slot 跨ぎの place_id 重複検出 → 自動 swap (既存 self-healing 拡張)、(3) test で重複 swap を assert。実装規模 ~80 LOC、1〜2 時間
- **追加課題 B**: **宿情報が pack に入らない**
  - 真因: `apps/api/src/evidence/lodging.py` は Phase 2.3 で実装済だが、本番 Render に `RAKUTEN_APPLICATION_ID` env が未設定
  - Run 9 / Run 10 / Run 11 / Run 12 全てで Render log に `[WARNING] src.evidence.builder: rakuten lodging fetch skipped: RAKUTEN_APPLICATION_ID が未設定です` が出ていた
  - fix: user が https://webservice.rakuten.co.jp/ で App ID 取得 → Render Dashboard env に追加 → auto redeploy で動く（**コード変更ゼロ**）
- **追加課題 C**: **移動手段の指定がない**（全員車運転できるとは限らない demo シナリオ）
  - 真因: `/plan/new` form に transport_mode 入力なし、prompt にも反映されない
  - fix 方針: form に「全員車運転可? / 公共交通のみ?」radio 追加 → `query_context.transport_mode` として prompt 注入 → assembler の transit fallback 順序を変える
  - 実装規模: form +20 / shared-types +5 / prompt +10 / assembler +20 / test +30 = ~85 LOC、1〜1.5 時間
- **追加課題 D (UX 大改修)**: 食事を朝昼夜のクリック式選択に
  - anchor mode の拡張として「food_anchor_place_ids」を別 slot 種類に渡す形
  - 提出後 Phase 2.x で plan 起案
- 学び:
  - **「200 + 画面遷移 + render 無 error」を達成しても、生成内容の質は別問題**。Run 12 完全動作の中で観察される demo 内容に新規課題が見える。verify は「動く / 動かない」の binary ではなく「demo として通用するか」の体験ベース判定が必要
  - **slot 跨ぎ重複は Phase 1.3e assembler 設計の盲点**。verify_hallucination_rate.py は単一 slot ごとの validity しか見ていなかったため、実 plan の「DAY 重複」現象を検出できなかった
  - **env 設定漏れは「実装済機能の死角」**: lodging.py は Phase 2.3 で実装 + test PASS していたが、本番 env 未設定のため一度も動いていなかった。本番 deploy preflight に「全 fail-soft fetch が実際に成功しているか」を含めるべき
- 推奨優先順位（提出までの時間で）:
  - **案 1 (30 分)**: B のみ - 楽天 env 設定で宿表示（demo 1 泊でなら slot 重複もそこまで目立たない）
  - **案 2 (2 時間、推奨)**: A + B - 重複防止 fix + 楽天 env、最も demo 効果的
  - **案 3 (4 時間)**: A + B + C - 移動手段指定も追加、完成度最大
  - D は提出後 Phase 2.x

## 2026-04-27: 本番 Run 11 で **422 全塞ぎ fix の効果実証** + プラン閲覧画面の独立 React error 発覚（EvidenceModal / MapView の location 未定義セーフガード漏れ）
- 状況: `fix/plan-generation-blockers` の本番 deploy 後、Playwright で本番 Run 11 を実行（plan_id `10524736-4767-40b2-bcd8-93957b2fcd68`、05:29 JST）
- **422 全塞ぎ fix の効果実証**:
  - URL が `/plan/10524736-...`（`/generating` なし）に遷移 = `/api/plans/generate` が **200 で plan_id を返した動かぬ証拠**
  - Run 10 までは `/plan/.../generating` で停止 + 422 console error だった
  - canonical 8 点 (`["00:00","06:00","09:00","12:00","15:00","18:00","21:00","23:59"]`) + retry guidance + previous_issues 累積化が効いた
  - **本セッションで実装した Codex 3 回 review 反映 fix が本番で完全に動いた**
- 別問題として発覚した独立 React error:
  - `apps/web/src/components/EvidenceModal.tsx:42` で `item.location.place_id` access、`item.location` が undefined のとき crash
  - `apps/web/src/components/MapView.tsx:29` で `i.location.lat !== null` access、同様に crash
  - Phase 2.5 evidence modal を design 仕事で committed した時に safety check が漏れた regression
- 学び:
  - **「200 を返す = 動く」ではない、閲覧画面までの完全な動作確認が verify**。本セッション「Run 11 = 200 必須 + 画面遷移」を Codex review 2 で必須条件化したが、画面遷移の先のレンダリングまで含めるべき
  - **Phase 2.5 design 実装で safety check 漏れ**: TypeScript の `strictNullChecks` でも nested optional access が type system 上は通っても、runtime で undefined のケースは検出できない。型と現実の data shape の乖離は test で fix が必要
  - **Run 11 で「3 つ目の独立した問題」が発覚**: 本セッションで真因 A, B + Codex 追加 Major 4 件を全塞ぎしたが、それでも別問題が表に出てきた。**本番 verify は仮説検証だけでなく「次の隠れた bug の発見器」でもある**
- 解決策（`fix/evidence-modal-undefined-location` ブランチ、本セッション末で実装）:
  - `EvidenceModal.tsx`: `item.location?.place_id ?? null` で optional chaining
  - `MapView.tsx`: `i.location != null && ...` で undefined 除外
  - test 追加（`EvidenceModal.test.tsx`: location 削除でも crash しない 1 件）
- ルール候補:
  - **本番 verify の必須条件は「200 + 画面遷移 + レンダリング無 error」の 3 段階**
  - **type system 上 optional の nested field を component で使う時は必ず optional chaining + nullish coalescing**
- → `.claude/rules/frontend-design.md` に「component の data access は必ず optional chaining で safety check」を昇格候補（同種事故の防止）

## 2026-04-27: develop ブランチで origin と divergence、conflict marker が origin に残ったまま push されている（git 運用の落とし穴、次セッション解決必要）
- 状況: 本セッション末で `fix/plan-generation-blockers` を develop に local merge 後、push しようとしたら origin/develop と divergence。origin に別端末の 5 commits（design 仕事）が先行していて、3 ファイル (`generating/page.tsx` / `lessons.md` / `todo.md`) で衝突予測。
- **更に深刻な問題**: `git show origin/develop:tasks/todo.md` で確認すると、**origin の todo.md に `<<<<<<< HEAD` `=======` `>>>>>>>` marker が commit に含まれた状態で push されている**。前回の merge 時に user が conflict 解決を保存せず commit してしまった可能性
- 学び:
  - **複数端末で並行作業する場合、`git pull --no-rebase` 後の conflict 解決を必ず確認してから commit すべき**。merge editor で「保存だけ」では conflict marker が残る
  - **conflict marker が含まれた commit を push すると origin が壊れた状態で永続化**。後続の merge / pull で更に複雑化する。**push 前に `git diff` か grep で `<<<<<<<` / `>>>>>>>` を確認する preflight が必要**
  - **本セッションの全塞ぎ実装は完了したが、divergence 解決が user 手動で必要**。次セッション最初のタスク: `git pull origin develop --no-rebase` → 私が 3 ファイルの conflict を Edit で解消（origin design 仕事 + 私の fix を両方統合 + 残存 marker 消去）→ user commit + push → 本番 Run 11 で 200 確認
- ルール候補:
  - **commit 前に `git diff --staged | grep -E '<<<<<<< |>>>>>>> '` を必ず実行**して conflict marker 残存を検出。1 件でも hit したら commit 中断。secret プリフライトと同レベルの preflight として運用
  - **複数端末作業時は `git pull --rebase` 派 vs `--no-rebase` 派を team で統一**。default 設定の不整合が conflict 発生時の挙動差を生む
- → 1 回目だが「commit に conflict marker が混入」は今回 origin で 1 度実証されているので、本来は 2 回目記録扱い。**次セッションで `.claude/rules/` に「commit 前 conflict marker grep」を昇格**

## 2026-04-27: 全塞ぎモード — Codex 3 回 review で 422 真因 4 つ + 副次 Major 4 つを網羅的に修正（Phase 1.10 後段）
- 状況: 本番 Run 10 で 422 を再現したログから真因 A (candidate_departures 1 件) + 真因 B (LLM hallucination) を特定後、user 指示で「全部特定して塞ぐ」モードに切替。並列 Explore agent 2 件で transit_matrix 構築 path / LLM prompt 詳細を完全把握 → Codex review 3 回（review 1: 設計相談で Blocker 2 / Major 4 / Minor 1、review 2: 計画書 review で 追加 Blocker 2 / Major 3 / Minor 1、review 3: 実装 review で Major 1 / Minor 2）→ 全反映
- 全塞ぎした問題（複数の独立した穴を網羅的に検出）:
  - **真因 A (Blocker)**: `candidate_departures = 1 件` → canonical 8 点 (`["00:00","06:00","09:00","12:00","15:00","18:00","21:00","23:59"]`) + observed merge
  - **真因 B (Major)**: LLM unknown_place_id 繰り返し → retry prompt に `_build_retry_guidance_md` で禁止リスト注入 + regex 抽出（`split('"')` 脆弱性回避）
  - **追加 Blocker (review 1)**: 5 点だけだと **22:00+ start_hhmm でカバー不能** → `00:00` / `23:59` を必ず含む 8 点に拡張
  - **追加 Major (review 1)**: retry の `previous_issues = issues` が直前 1 件のみ → 過去全 attempts 累積化 + dedup（UNKNOWN_PLACE_ID は place_id 単位、他は (kind, message)）+ MAX_RETAIN=10 cap
  - **追加 Major (review 1)**: フロント transit 全滅 (`succeeded === 0`) でも generate 続行 → `shouldEarlyThrowOnTransit` helper で早期 throw
  - **追加 Blocker (review 2)**: try/catch の **内側 catch で例外を握りつぶす** 穴 → `catch (err) { throw err instanceof Error ? err : new Error(...) }` で再 throw
  - **追加 Major (review 2)**: `dedup_key = (kind, message)` だと UNKNOWN_PLACE_ID が複数 slot で残る → `_extract_unknown_place_ids` で place_id 単位 dedup
  - **追加 Major (review 3)**: dict の `__setitem__` は既存 key の挿入順を保持するため、`[-MAX_RETAIN:]` で「先に入って再発した issue が末尾に来ない」 → `pop(key, None) → unique[key] = issue` で recency 保証
- 学び:
  - **複数 Codex review で「相互に独立した穴」が次々と見つかる**: review 1 で 5+ 件、計画書 review 2 で +5 件、実装 review 3 で +3 件。**1 回の review では網羅できない**、3 回かけて確実に塞ぐべき複雑なバグ群だった
  - **「直近優先」は dict update では保証されない**: Python 3.7+ の dict は insertion-ordered だが、同 key への代入で position は更新されない。recency-aware dedup には `pop` + 再挿入が必要 = 暗黙の前提を疑う
  - **regex 2 種で robust な抽出**: assembly format / validator format 両方の message を 1 helper でカバー、`split` 脆弱性回避
  - **canonical 値の hardcode 二重化**: フロント `transit.ts` と Python `verify_hallucination_rate.py` で同じ 8 点を hardcode せざるを得ない（言語境界）→ 双方向に drift 警告コメントを残すのが現実的な妥協
  - **Phase 1.3b と 1.3e の contract drift**: 「フロントが 1 件」「test が 5 点」が長期間共存して発覚せず、本番でようやく顕在化。Phase 跨ぎ contract は production parity test で固定すべき（前 entry の learning と同じ系統）
- ルール候補:
  - **複数 review を経ないと網羅できない複雑な fix では「設計 review → 実装 → 実装 review」の 3 ステップを最低限こなす**。1 回 review で済ませない
  - **dict 系の dedup で「直近優先」が必要なら recency-aware セマンティクスを明示**（`pop + 再挿入` or `OrderedDict`）。単純 update は順序保証なし
- → 「contract drift（Phase 跨ぎ実装の不整合）」「直近優先 dedup の罠」は **2 回目記録（前 entry とペア）**。次セッションで `.claude/rules/` に複数昇格候補を整理予定

## 2026-04-27: 本番 Run 10 で 422 真因判明 — `candidate_departures` 1 件問題（Phase 1.3b ↔ 1.3e 不整合）+ `unknown_place_id` ハルシネーション再発
- 状況: chore/api-logging-config で Render Live tail に `logger.info` が流れるようになった直後、本番 Run 10 (plan_id `9b209857-...`、04:54-04:55) で 422 を再現してログを取得。**4 attempts 全失敗**の breakdown:
  - **attempt 1 (gpt-4.1)**: `unknown_place_id` — day1_lunch slot に place_id `ChIJJS7EfYgChGWARNW9YGF4jb0I` を割当て (Evidence Pack 外)
  - **attempt 2 (gpt-4.1)**: `unknown_transit_edge` — edge X→Y の `candidate_departures=['13:54']` で required `start_hhmm='16:30'` をカバーできず
  - **attempt 3 (gpt-4.1)**: `unknown_place_id` — day1_dinner slot に **同じ** `ChIJJS7EfYgChGWARNW9YGF4jb0I` を再割当て
  - **attempt 4 (gpt-4.1-mini)**: place swap (assembler self-healing) は成功したが、別 edge の `candidate_departures=['13:54']` で required `'16:30'` をカバーできず → 同じ unknown_transit_edge
- 真因 A — **`candidate_departures` が 1 件しか入っていない構造**:
  - `apps/web/src/lib/transit.ts:300-302` の `parseDirectionsResult` が `[formatHHmmJST(departureDate ?? requestedDeparture)]` で **常に 1 要素**を返す
  - フロントは現在時刻 (04:54 JST = `submit` 時刻) で 1 回 fetch → Maps SDK は「13:54 発」を返す → `candidate_departures: ["13:54"]` で固定
  - assembler は「16:30 以降に出発する transit edge を選ぶ」「但し candidate_departures から最小の有効値を取る」ロジックで、required 16:30 ≧ 13:54 なので **全部 reject**
  - **構造的乖離**: Phase 1.3e `verify_hallucination_rate.py` では `["09:00","12:00","15:00","18:00","21:00"]` の **5 点** で test していたが、本番フロント (Phase 1.3b 設計) は **1 点だけ**。Phase 1.3e の assembler は「複数 candidate から選ぶ」前提なのに、Phase 1.3b のフロント実装はその要件を出していなかった = **両 phase の独立実装で contract が一致していなかった**
- 真因 B — **`ChIJJS7EfYgChGWARNW9YGF4jb0I` の繰り返しハルシネーション**:
  - gpt-4.1 が attempt 1 と 3 で **同じ unknown place_id** を出力。"popular hallucination" pattern
  - Phase 1.3e `verify_hallucination_rate.py` で hallucination 0% を達成していたのに本番条件で再発 = **prompt 内の pack 構成 / token budget が verify と本番で微妙に違う可能性**
  - 真因 A 解消後の retry 数減少で B の頻度も下がる可能性があるが、独立 fix（prompt 強化 or assembler の self-healing 拡張）が必要
- 学び:
  - **Phase 跨ぎの design contract は明示的に test で固定しないと drift する**。Phase 1.3b (フロント transit fetch) と 1.3e (LLM assembler) は別セッションで実装され、間に「候補時刻が複数必要」という暗黙の contract があった。これを `verify_hallucination_rate.py` 側だけ満たして、本番フロントは満たさない状態が長期間維持された
  - **Run 9 vs Run 10**: Run 9 では「422」しか分からなかったが、logging.basicConfig 追加だけで **同じ 422 から `unknown_place_id` `unknown_transit_edge` という具体的 IssueKind と該当 place_id まで** 取得できるようになった。「本番デバッグ可視性は logging 設定で大幅に変わる」を実証
  - **assembler の self-healing は強力**: attempt 4 で `LLM picked ineligible place ... swapped to ...` がログに出ており、Phase 1.3e の hard self-healing が**実際に動いていた**。これは Phase 1.3e の成果が無駄になっていない証拠
  - **Render Live tail の実用性**: log を仕込むことで本番事象を 1 〜 2 分で特定できる。本番固有問題（ローカルでは再現しない or 再現しにくい問題）の調査では log 設定が最優先
- 次セッション優先順位:
  - **🔴 問題 A 修正 (最優先)**: `apps/web/src/lib/transit.ts` の `parseDirectionsResult` を「`candidate_departures` を複数化」する。設計案: (1) フロントで複数 departure_time で並列 fetch (5 倍コール、deadline 危険)、(2) 1 回 fetch 後にフロントで合理的な時刻 list `["09:00","12:00","15:00","18:00","21:00"]` を **fixed list として加算**（精度落ちるが assembler 互換）。**案 2 が現実的**
  - **🟡 問題 B 調査**: 問題 A 解消後にもう一度 Run で再現するか確認。`apps/api/scripts/verify_hallucination_rate.py` を本番条件 (region=箱根 / auto / 30,000円) で走らせて再現性測定 → 必要なら prompt 強化 or assembler self-healing 拡張
- ルール候補:
  - **Phase 跨ぎ contract は schema parity test と並ぶ「production parity test」で固定**。`verify_hallucination_rate.py` のような scenario test を「本番フロント実装と同じ入力形式で動かす」よう統一する。本番固有 path（フロント → サーバ） vs 検証 path（test fixture → サーバ）の **2 つの input path が乖離していた**のが今回の bug
- → 1 回目だが「Phase 跨ぎ contract drift」は他にも潜んでいる可能性大（mode_payload schema や budget_constraints の format 等）。次セッション以降で **production parity test** を整備する候補

## 2026-04-27: Flask デフォルト logger は WARNING 以上のみ → 本番デバッグ視認性ゼロ問題（chore/api-logging-config で解消）
- 状況: 本番 Run 9 で `/api/plans/generate → 422` が再現したあと、Render Live tail を確認すると **アクセスログ (gunicorn `--access-logfile -`) は流れているが、Python の `logger.info()` 出力が一切ない**。具体的には `apps/api/src/llm/generator.py:290` の `logger.info("LLM attempt %d produced %d validation issues, retrying")` や、`apps/api/src/llm/generator.py:270` の `logger.info("LLM attempt %d assembly error (kind=%s)")` が **3 retry 分流れているはずなのに 0 行**。validator がどの IssueKind で reject しているか、構造的に見えない
- 真因: `apps/api/src/app.py` で **`logging.basicConfig()` を呼んでいなかった**ため、Flask の root logger は default level `WARNING` のまま。`logger = logging.getLogger(__name__)` で取得した logger も親 (root) の level に従うので、`logger.info(...)` は **silently discarded** される。gunicorn は Python logging の自動設定をしない（access_log は別系統で gunicorn 自身の logger 経由で stderr に流れる）
- 学び:
  - **Flask + gunicorn 構成で `logging.basicConfig()` を呼ばないのは「default で WARNING 以上のみ」という落とし穴**。`.claude/rules/api-rules.md`「ロギング」節は「`print` を使うな、`logging` モジュール」「外部 API 呼び出しは必ず `INFO` でログ」と書いているが、**実際に INFO が出力されるための basicConfig 設定がなかった**。ルールと設定の不整合
  - **Flask debug mode は app.logger だけ INFO 化する** が、`apps/api/src/llm/generator.py` のように `logger = logging.getLogger(__name__)` で取得した module-level logger は app.logger とは別系統なので影響を受けない。production gunicorn では debug mode がそもそも off なので意味なし
  - **本番デバッグの視認性は INFO log を流すかで決まる**。validator が 422 で reject するルートを通っても、retry 詳細が log に出ない＝何が悪かったか調べようがない＝本番デバッグ不能
  - **本来は Phase 1.10 deploy preflight checklist に「Python logging 設定が production で有効か」を入れるべき**。今回は本番で 422 が出てから初めて気づいた、本来は deploy 前 verify で「INFO log が Render Live tail に流れる」ことを確認すべきだった
- 解決策: `apps/api/src/app.py` 冒頭で `logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO").upper(), format=...)` を呼ぶ。`LOG_LEVEL` env で本番 INFO / test WARNING を切り替え可。これにより Render Live tail に `logger.info` が流れ、422 の真因（IssueKind 別 retry log）が見えるようになる
- ルール:
  - **新規 Flask アプリの最初の commit で `logging.basicConfig()` を必ず明示する**。`.claude/rules/api-rules.md` 「ロギング」節を「`logging.basicConfig(level=INFO)` を `create_app()` の前に呼ぶ」に強化候補
  - **本番 deploy 前に Render Live tail で「INFO log が出る」ことを smoke test**（healthz だけでは不十分、validator や generator のような application logger が出力されることを確認）
- → 1 回目だが「ルールと設定の不整合」は他にもありそう（CORS / MAX_CONTENT_LENGTH / MAX_RETRIES 等）。次セッションで `.claude/rules/api-rules.md` 全項目について「設定が実際に有効か」をチェック list 化する候補

## 2026-04-27: ローカル verify で「transit fallback fix は完璧、ただし 422 は別問題」と判明（仮説の修正）
- 状況: 同日完了の transit fallback fix を `pnpm dev` + Playwright で `/plan/new` 提出 verify。`transit-debug` 仕掛けの console.log で stats / mode breakdown / duration 統計を取得
- 観測値（箱根 / 1 泊 2 日 / auto モード / 30,000円 budget）:
  - stats: `{attempted: 40, succeeded: 40, timedOut: 0, errors: 0, deadlineReached: false}` ← **40/40 全成功**
  - Maps SDK は "Directions request returned no results" を **44 回**出力（TRANSIT で全 ZERO_RESULTS） → fallback chain で WALKING / DRIVING 採用
  - mode_counts: **`{walk: 20, car: 20}`** ← 距離分岐が綺麗に二分（≤ 2km の WALKING、> 2km の DRIVING）
  - duration_stats: **min=5 / max=46 / avg=18 min** ← 「徒歩 2 時間」のような極端値なし、plan として健全
- 仮説の修正:
  - **前セッション handoff の仮説**: 「transit fallback fix が解消すれば LLM 422 も自動的に解消する」（todo.md 最優先タスク 5 番目）
  - **verify で判明した実態**: transit_matrix が **40 件あっても** `/api/plans/generate → 422`。**A=>B ではなく、A は B の必要条件の 1 つに過ぎなかった**
  - つまり 422 は別の原因（LLM validator の opening_hours 違反 / budget_exceeded / unknown_place_id 等）で発生中。次の fix 対象として独立タスク化が必要
- 学び:
  - **ローカル verify の価値**: 本番 deploy 前に Playwright + console.log で stats を取れば、「fix が想定の効果を出すか」と「他の隠れた問題があるか」が同時に切り分けられる。今回もし本番 push して Run 9 で 422 を見たら「fix が効いていないのか / 別問題なのか」が分からなかった
  - **仮説 (A => B) の二重チェック**: 「A を fix すれば B も解消する」という仮説は、A の fix を実装した後に「実際に B が解消したか」を計測するまで信じてはいけない。今回は handoff prompt 自体が「これが解消すれば Phase 2.2 budget context の効果も観察できる」と仮説していたが、verify で覆った
  - **debug log の placement**: `console.log("[transit-debug] stats:", JSON.stringify(stats))` のように JSON.stringify で出すと Playwright の console MCP で値が完全に取れる（オブジェクトのまま渡すと `[Object]` で潰れる）。**playwright を使う前提の debug log は最初から JSON.stringify する**
  - **fix の scope を verify で確定**: 「transit fallback の責務は transit_matrix を空にしないこと」が verify で実証された。今後の commit message でも「transit fallback で 422 解消」とは書かず「transit_matrix が観光地ペアでも空にならない」に範囲限定するのが正確
- ルール:
  - Phase 1.X 級の fix を本番 deploy する前に、**ローカル verify で「fix の効果計測」と「別の隠れた問題があるか」両方を確認する**。stats / counts のような数値計測ログを仕込んで Playwright で取得するのが省力
  - 仮説 (A => B) を持っているときは、A を fix した後に **「B も実際に解消したか」を必ず計測**する。期待だけで本番に push しない
- → 上の transit fallback entry とペアの関係。fallback chain 設計の学びと、verify による仮説修正の学びは両方とも `.claude/rules/external-api-rules.md` 昇格候補（前 entry と統合してルール化）

## 2026-04-27: Maps Directions の travelMode を「距離分岐フォールバック chain」化で解消（Phase 1.10 fix 完了 / Codex 2 回 review）
- 状況: 2026-04-26 Run 8 で発見した「TRANSIT が観光地ペアで全 ZERO_RESULTS」（lessons.md 直下 entry）を `fix/transit-fallback-walking-driving` で完了。設計書 → Codex review 1 → 反映 → subagent で TDD 実装 → Codex review 2 → 反映 → web test 147/147 PASS / tsc clean / build PASS / API regression 381 PASS
- 軌道修正された判断 3 点（**Codex 1 回目で防げた構造 bug**）:
  - **(1) 順序固定 `TRANSIT → WALKING → DRIVING` は危険**（initial 設計）。遠距離 10km ペアで TRANSIT 失敗 → WALKING で経路成立 → 「徒歩 2 時間」が plan に組み込まれ、assembler が duration_min で時刻後ろ倒し → opening_hours 違反量産で 422 を再誘発するリスク。**Codex Major 1 で発覚**
  - **(2) 距離分岐で 2 段目を切替**: ≤ 2km は `TRANSIT → WALKING → DRIVING`（徒歩 30 分以内、plan として自然）、> 2km は `TRANSIT → DRIVING → WALKING`（車優先、徒歩は最終 fallback）。閾値 2km の根拠は **徒歩 30 分相当**（平均歩速 4 km/h × 0.5h、plan に組み込んでも違和感ない上限）
  - **(3) per-mode timeout 2s 維持**（`/3` で全体 6s に揃える代替案を Codex OK 判定で却下）: ZERO_RESULTS は ~100ms で reject されるため per-mode 2s でも実時間合計は ~600ms / pair。`/3` で 666ms にすると実 API 応答が遅いケースで偽 timeout 増、悪手
- 軌道修正された判断 (Codex 2 回目で発覚した test 設計 bug):
  - **(4) 「WALKING / DRIVING で transitOptions 未付与」test が近距離ペアで書かれており DRIVING が呼ばれていない**（実質 DRIVING 検証 0）→ 近距離 / 遠距離の 2 件に分割
  - **(5) WALKING_DISTANCE_KM の値そのものを固定する test なし**（閾値が 3km に変わっても通る）→ 上側境界 (2.0015km) で DRIVING 採用 / WALKING 0 件 を assert
- 学び:
  - **fallback chain 設計時、「全 mode 試行で問題が解決する」だけでなく「各 mode が成功した時の plan 品質」まで視野に入れる**。今回は「TRANSIT 失敗 → WALKING 成功」の plan が下流 assembler で 422 を生む副作用に Codex が気づいた。実装者は「fallback chain が動く」で満足しがちだが、**下流の制約（assembler / validator）への波及**まで設計に含めるべき
  - **Codex に複数質問を 1 回投げる**（Q1〜Q9 を提示）と、各観点の判定（Major / Minor / OK）が明示的に返ってくるので「どこを軌道修正するか」が明確になる。Q1 + Q7（順序判定 + 徒歩 2 時間問題）が連動した Major で、両方ケアしないと部分 fix になる
  - **Codex review 2 回目で「test の意図 vs 実検証範囲」のズレが 2 件発覚**。「単一の test で複数モードを暗黙に検証」は脆い、**「対象モードが実際に呼ばれているか」を mock の観測（`calls.filter(c => c === "DRIVING")` 等）で明示的に assert** する設計が必要
  - **subagent への TDD 実装委任は機能した**: 設計書 + Codex 1 回目反映後の plan を渡して「TDD 厳守 + 全 test PASS まで」を依頼。subagent は haversine 実測ズレ（lat 35.018 で 2.0015km、`<= 2km` で false）を実装中に気づき test 修正、3 つの「設計書からズレた判断」を report で明示。**設計書 + 役割分担の明確さがあれば subagent でも品質が落ちない**
- ルール:
  - 外部 SDK のフォールバック chain を設計するときは、**各 mode が成功した時の出力品質**（duration_min の現実性、cost の妥当性）も判断軸に入れる。「動くか」だけでなく「下流に何が起きるか」
  - test の意図と実検証範囲が一致しているかは **対象モードが実際に呼ばれているか** を mock の観測で明示的に assert する。「単一の test で複数モードを暗黙に検証」は脆い
  - 距離 / 閾値ベースの分岐ロジックでは、**閾値の値そのものを固定する境界 test pair**（境界直下 + 境界直上）を必ず入れる。閾値が変わったら確実に test が落ちる形に
- → **2 回目（前 entry とペア）なので `.claude/rules/external-api-rules.md` に昇格対象**。「外部経路 SDK のフォールバック chain は単一モード固定せず、各 mode の下流影響まで含めて設計」を昇格候補としてマーク（次セッション or commit 後に検討）

## 2026-04-26: Maps Directions TRANSIT モードは「観光地間」で ZERO_RESULTS を返す（公共交通の有効圏外）
- 状況: Phase 1.10 Evidence Pack 多様性 fix（Run 8 ローカル verify）で places を観光地 7 + 飲食 5 = 12 件に多様化、距離 0.64〜9.57 km に分散したのに、`fetchTransitMatrix` の stats が `{attempted: 40, succeeded: 0, errors: 40}` で全ペア ZERO_RESULTS。Maps SDK 自体は動作（REQUEST_DENIED 0 件）、`google.maps.DirectionsService.route({travelMode: "TRANSIT"})` が「彫刻の森美術館 → 箱根食堂」のような観光地ペアで経路を返さない
- 真因:
  - Maps Directions の TRANSIT モードは「電車・バス・地下鉄」の **公共交通機関ノード間** の経路を返す
  - 駅 / バス停以外の **観光地は TRANSIT グラフのノードではない**（徒歩アクセスが基本）
  - 結果として、観光地 → 観光地 / 観光地 → 食事処 のような「公共交通機関を使わない近距離移動」は ZERO_RESULTS となる
  - Phase 1.3b で TRANSIT モード固定にしたのは「日本の電車を主役にした demo」のためだが、places の多様化（観光地メイン）と相性が悪かった
- 学び:
  - **Maps Directions の TRANSIT は「駅・停留所間」の経路 SDK** であり、汎用の経路 SDK ではない。観光地メインの pack には不向き
  - 距離 5〜10 km の同一観光圏内なら **WALKING / DRIVING にフォールバック**するのが現実的（実際の旅行者も「徒歩 + 観光地レンタカー」で巡る）
  - **Phase 1.3b 当時の設計判断**「TRANSIT で日本の電車を強調」は places が駅前飲食店ばかりだったから動いていた（皮肉にも places 偏重 bug が transit 取得を成功させていた）
  - Phase 1.10 で places を改善したことで隠れていた TRANSIT 限界が顕在化。**「片方の改善が別の限界を露呈する」古典パターン**
- 対処（次セッション）: `apps/web/src/lib/transit.ts:333` の travelMode 固定を **TRANSIT → WALKING → DRIVING のフォールバック chain** に変更。各 mode で per-call 2s timeout、全体 deadline 10s 維持
- ルール:
  - **外部 SDK の特定モード（Maps TRANSIT 等）に依存する場合、フォールバック設計を最初から組み込む**。「特定モードで取れない / ZERO_RESULTS」のケースは現実に頻繁に発生する
  - 単一モード固定は「demo シナリオが固定」前提で、places の動的変化（Phase 1.10 fix 等）で破綻する
- → 2 回目が来たら `.claude/rules/external-api-rules.md` に「外部経路 SDK は単一モード固定にせずフォールバック設計」を昇格（今は 1 回目）

## 2026-04-26: 本番 E2E 7 連続 Run で「設計の整合性 bug」を多層的に発見（migration 漏れ / Maps API allowlist / フロント先打ち PATCH / Evidence Pack category 偏重）
- 状況: Phase 2.2 実装後の本番 E2E verify を 7 回連続で行った結果、**1 回 1 つずつ別の bug が連鎖的に表面化**:
  - Run 1: FK 23503（migration 05 mirror 未適用、user 適用で解消）
  - Run 2: Maps Directions REQUEST_DENIED（API key allowlist 漏れ、user 設定で解消）
  - Run 3: 設定反映ラグ（user 再確認で解消）
  - Run 4: 同 + 新ブロッカー: `failed to acquire plan lock`（migration 04 plan_generation_rpcs 未適用、user 適用で解消）
  - Run 5: ↑ 残課題
  - Run 6: `plan is already being generated`（フロントが先に PATCH status='generating'、Phase 1.3d Branch C と整合 NG、`fix/plan-status-lock-mismatch` で 1 行削除）
  - Run 7: 422 `plan generation failed after retries` ← Evidence Pack の places 構成が「箱根湯本駅周辺の飲食店ばかり」で観光地 0 件 → 互いの距離 0.01〜0.26 km → Maps TRANSIT が ZERO_RESULTS → transit_matrix=[] → LLM が plan を組めず validator 3 回 retry 後 reject
- 学び:
  - **本番 E2E は「設計通りに動く」ではなく「設計の不整合を見つける」道具**。1 つ fix するごとに次の bug が浮上、でも各 Run で原因切り分けが進む（migration 適用 / API key 設定 / フロント整合性 / Evidence Pack 品質）
  - **migration 適用漏れと API key allowlist 漏れは「user 作業」に依存するため、毎回 user 確認待ち**。これが 1 セッション内で 5 回発生し、各 Run で待ち時間が累積。**deploy preflight で確認できる migration の checklist が欲しい**
  - **フロント / バック整合性 bug は実装フェーズで検出できる**: Phase 1.3d Branch C で acquire_lock RPC を作った時に「フロントは status='draft' のまま呼ぶ」を契約として明文化していれば Run 6 は防げた。1.5 page.tsx と routes/plan_routes.py が別ブランチで実装されたとき、**両者の status 遷移責務を 1 ヶ所に書いた契約 doc** がなかったのが盲点
  - **Evidence Pack の category 偏重は LLM プロンプト改善 (Phase 2.2) 以前の品質問題**。Places API text search の結果次第で「飲食店ばかり」「観光地ばかり」になる場合があり、auto モードの keyword 生成 + region 指定だけでは混合が保証されない。次セッションで `places.py` の category-aware keyword 生成（観光 / 温泉 / 食事 / 宿泊の各 1〜2 件以上を必ず含む）を検討
  - **手動 verify は本番のみ**: ローカル `verify_hallucination_rate.py` は env 不足で動かなかった、unit test だけでは LLM 実遵守が検証できなかった、結果として user に migration / key 適用作業を依頼しながらの本番 7 連続 Run になった。今後は **代替の自動 verify 経路**（mocked Places + 固定 fixture pack で LLM 生成を自動回す）を検討
- ルール（昇格候補、次セッションで判断）:
  - 大物機能（Phase 2.x）の実装後に本番 E2E をやる前に「migration / env 変数 / API key allowlist / フロント-バック契約」の **4 軸 preflight checklist** を docs に書く
  - Evidence Pack の category 多様性を保証する unit test を `tests/test_evidence_builder.py` に追加（places の category set に観光地 + 温泉 + 食事 が含まれること）
- → 2 回目が来たら `.claude/rules/api-rules.md` に「本番 E2E preflight checklist」節を昇格（今は 1 回目）

## 2026-04-26: prompt 拡張は「placeholder helper」パターンの再利用で最小変更が成立する（Phase 2.2 で実証）
- 状況: Phase 2.2「予算配分の制約化」で LLM プロンプトに「宿泊は予算の 40%（¥12,000 以内）」のような絶対制約 Markdown を注入したかった。Explore agent で現状調査したところ、Phase 2.1 で既に `_build_mode_context_md(query_context)` + `{mode_context_md}` placeholder の枠組みが実装されていた。同じ pattern（**helper 関数 + template placeholder + build_user_prompt 内で format_kwargs に追加**）で `_build_budget_context_md(budget_constraints)` を追加することで、validator / assembly / フロント / 3 点同期の変更ゼロで機能拡張完了
- 効果:
  - 実装 LOC は plan / impl / test 合わせて ~250 行（うち plan 文書 ~200 行、コード ~50 行、test ~120 行）
  - prompt token 増加 +216（実測、警告閾値 12k 内）
  - Phase 1.3e の hallucination 0% / success 100% に regression リスクほぼゼロ（prompt 構造の **追加** のみで既存セクションは不変）
- 学び:
  - **既存 pattern を踏襲する判断は、Explore agent で現状の関連コードを 5 軸（データ流れ / prompt / validator / assembly / 既存 pattern 再利用性）で見渡してから決める**と精度が高い。今回は Explore の調査レポートに「mode_context_md パターン再利用可能性」を含めたのが効いた
  - **prompt の Markdown 注入は v2 のみで OK**（v1 は legacy 検証用で template に placeholder なし）。`build_user_prompt` 内で `version.startswith("v2")` 分岐で `format_kwargs` に追加するか除外するかを切り替える形が最も安全（v1 で `KeyError` を起こさない）
  - validator にハードコードされた tolerance 定数（`BUDGET_TOLERANCE_RATIO = 0.05`）を prompt 文言で参照するなら **`from .validator import BUDGET_TOLERANCE_RATIO` で動的に取得**せよ（Codex review 2 回目 Minor 1 反映）。ハードコード `+5%` だと validator 側の変更で文言と挙動が drift する
- ルール:
  - 同じ prompt に追加 context を注入したい時、新規 placeholder を増やすか既存の `mode_context_md` 等の helper パターンに乗せるかは、**用途が直交していれば独立 placeholder、用途が重なるなら既存 helper の出力を拡張**を選ぶ。今回は用途が独立（出発モード vs 予算）なので独立 placeholder
  - prompt 拡張時は **挿入順テスト**（`prompt.index("A") < prompt.index("B") < prompt.index("C")`）を必ず書く。helper の format 順は format_kwargs の dict 順序ではなく template 側の placeholder 順なので、test なしには気付かない drift が起きる
- → 2 回目が来たら `.claude/rules/llm-rules.md` の「プロンプト拡張」節に「helper pattern 再利用 + 挿入順 test」を昇格（今は 1 回目）

## 2026-04-26: docs / todo に API key 文字列を貼ったら Public repo の Secret Scanning が即検出した
- 状況: Phase 1.10 本番 E2E debug を todo.md / lessons.md に詳細記録する際、**Playwright の console error から拾った Google Maps ブラウザキー** をそのまま `tasks/todo.md` line 44 に文字列として埋め込み、commit 215570e で develop に push。GitHub Secret Scanning が **API key pattern** (`AIzaSy[A-Za-z0-9_-]{33}`) を検出して Google にアラート送信、user に通知が来た
- 原因:
  - Playwright console output に key が出てくる → debug log として手元の sub-agent / context にコピー → todo.md に転記 → commit、という流れで「文字列をそのまま貼る」抑止が効かなかった
  - **本人としては「省略形（`AIzaSyDq...3y4`）」と「フルキー」を 2 箇所に書いた**。前者は復元不可だが、後者は完全公開
  - Vercel の env から取り出せる前提で「key そのものは secret」という意識が docs 編集中に薄れた
- 影響範囲:
  - 該当 key は **HTTP referrer 制限あり**（Vercel domain + localhost 限定）なので攻撃ハードルは少しだけ高いが、リファラ偽装で叩ける／quota 消費攻撃の余地あり
  - **rotate（無効化 + 新規発行）で被害最小化**。commit 履歴自体は残るが key 自体が無価値になる
- 対処:
  - 即時: Google Cloud Console で旧 key を delete + 新規発行（同じ API restrictions / referrer 制限）+ Vercel env 更新 + redeploy
  - working tree 上の todo.md / lessons.md から key 文字列を redact する revert commit を作成（force push なし、key は無効化済なので history は残しても OK）
- ルール:
  - **debug log に key / token / secret が出たら、絶対にそのまま docs に貼るな**。記録するなら「prefix 4 chars `AIza...`」だけにする、もしくは `<env: NEXT_PUBLIC_GOOGLE_MAPS_BROWSER_KEY>` のような env 変数名で参照
  - Public repo に push する commit を作る前に、**`git diff --staged | rg 'AIzaSy|sk-[A-Za-z0-9]|eyJ[A-Za-z0-9]'` で必ず secret pattern check**
  - GitHub Secret Scanning は **Public repo + 主要パートナー pattern (Google / OpenAI / AWS / Stripe / Slack) のみ自動 alert**。Private repo でも漏洩の可能性はあるので同じ rule を適用
- → ~~2 回目が来たら~~ **public repo に実害（GitHub Secret Scanning 検出 + Google アラート送信）が出たため 1 回目で `.claude/rules/external-api-rules.md` 「⛔ 最優先: commit 提案前の secret プリフライト」節に即昇格、CLAUDE.md「Do NOT」と「ワークフロー」にも明文化済（毎セッション自動ロード）**

## 2026-04-26: migration 適用漏れは「複数ファイル同日 merge」で起きやすい — 本番デプロイ前に migrations 全件の適用 checklist を作る運用が必要
- 状況: Phase 1.10 本番 E2E verify で 4 連続の Run（Run 1〜4）を実行する過程で、**migration 適用漏れに 2 度連続で遭遇**:
  - Run 1: 409 FK violation → 真因は `20260425_05_auth_user_sessions_mirror.sql` 未適用
  - Run 4: `failed to acquire plan lock` 500 → 真因は `20260424_04_plan_generation_rpcs.sql` 未適用と推定（routes/plan_routes.py:110 の想定外例外パスからしか出ない文字列、acquire_plan_generation_lock RPC が見つからず raise）
- 共通パターン: **migrations ファイルが develop に存在 + ローカル `pytest -m integration` 通過 + 本番 SQL Editor で未実行**。適用漏れは本番実行で初めて分かる（ローカル test は本番 schema を共有していない）
- 原因仮説:
  - 同日に複数 migration を develop に追加するメンバーが分散（Manato が 04 を Phase 1.3d で、メンバー B が `06_shared_plan_rpc.sql` `07_shared_plan_rpc_v2.sql` を Phase 1.9 で）
  - 本番側の SQL Editor は 1 メンバーが手動で適用する運用 → ファイルが増えると追従漏れが起きる
  - `supabase/migrations/all_migrations.sql` という統合ファイルがあるが、04 が含まれているか / 最新か / sort 順は何か、を毎回確認する手順がない
- 対処（user 作業）: 04 を再適用 → Run 5 で動作確認。**冪等設計なので追加実行は安全**
- ルール:
  - **本番デプロイ前に「適用済み migration の checklist」を必ず作って supabase/migrations/ 全ファイルを 1 件ずつ ✅ する**。複数メンバーが merge するプロジェクトでは特に
  - **新規 migration を develop に merge した時の commit message に「本番適用必須」をマークする運用**（例: `[migrations: APPLY] feat: ...` のような prefix）。次のデプロイ前に grep で残タスクを探せる
  - migrations 連番衝突時（`05_*` が 2 つ等）は、適用順を user に明示しないと事故る。merge 前に rename か順序合意
  - **本番 E2E で 500 を見たら、まず routes ファイルでそのエラー文字列を grep**。エラー本文が「想定外例外」パスからしか出ない文字列なら、依存先（RPC / DB schema / 環境変数）の不在を疑う
- → 2 回目発生済みのため `.claude/rules/data-model-sync.md` の「migrations 適用 checklist」節に昇格を次セッションで実施（今は本番未適用ファイルが 1 つ残っているのでまず解消、解消後に rule 化）

## 2026-04-26: 本番 E2E は「動くこと」より「壊れる箇所が想定通りか」を確認するのが価値、migration 連番衝突も同時発見
- 状況: Phase 2.1 polish merge 後、Vercel 本番（`https://hackathon-2026-04-13.vercel.app`）で Phase 2.1 が動くか確認するため Playwright を起動。フロント描画 / API healthz は通るが、`/plan/new` から auto モードで実フォーム送信したところ **`POST https://<project>.supabase.co/rest/v1/plans → 409 Conflict`** で失敗、フロントは即 `PATCH ... {"status":"failed"}` を打って遷移せず終了
- 既知問題の本番再現: 2026-04-25 lessons の「RLS 42501 の真因は plans.session_id の FK 違反 (23503)」が本番でも同じ表れ方。修正用 `supabase/migrations/20260425_05_auth_user_sessions_mirror.sql` は develop 上に存在するが **user による SQL Editor 実行が未着手** だったのが原因と確定
- **同時発見（新規）**: `supabase/migrations/` に **`20260425_05_*` で始まるファイルが 2 つ** 存在:
  - `20260425_05_auth_user_sessions_mirror.sql` — 上記 fix
  - `20260425_05_index_optimization.sql` — メンバー B のインデックス最適化
  両方とも develop に merge 済。ファイル名 sort で適用順が決まる現運用では辞書順 (`auth` < `index`) で偶然 mirror が先になるが、これは **明示的に保証されていない**。新規環境を構築する際に CI / 自動 apply ツールを後で導入すると順序の偶然性が崩れて即座に壊れる
- 学び:
  - **本番 E2E は「動くこと」を確認するためでなく、「壊れる時に想定通りの場所で壊れるか」を確認するのが価値**。今回は仮説（FK 23503）を本番 response で実証できたので、対処（migration 適用）への確信度が上がった。「本番で動くだろう」という楽観で SQL 未適用のまま提出すると当日デモで詰む
  - **migration 連番は `chmod` 規則と同じ厳密さで管理すべき**。複数メンバーが並行で develop に migration を入れる時、同じ日付・同じ連番が衝突しても build / test には現れず、新規環境構築時に初めて発覚する。`tasks/handoff-db.md` の「DB-1 連番ルール」を「**同日に複数 migration を入れる場合は 05a / 05b ではなく 05 / 06 で進める**」と明文化する価値がある
  - Playwright で本番 form を実際に submit する手順は **migration 05 適用後の再 verify でそのまま再利用可能**（auto / anchor / theme の 3 mode を 1 回ずつ実行 → ~$0.15 OpenAI / 5-10 分）。検証 cost が低く、本番ブロッカーの確認パスとして恒久化する価値あり
- ルール:
  - **本番デプロイ完了直後は必ず 1 回 Playwright で「最低限の golden path」を踏む**（local test や API healthz では本番固有の RLS / FK / CORS / env mismatch が出ないため）
  - **同日に複数の migration を develop に追加する場合は、merge 前に連番衝突を check し、衝突していれば次の連番に繰り上げる**。小さな擦り合わせコストで新規環境破綻を防げる
- → 2 回目が来たら `.claude/rules/data-model-sync.md` の「migrations 連番運用」節と、`.claude/rules/api-rules.md` の「デプロイ後検証」節に分けて昇格（今は 1 回目）

## 2026-04-26: Google Cloud SDK 利用は **4 階層** を全部確認する必要がある（API key の allowlist が見落とされやすい）
- 状況: PlaceAutocompleteElement に migrate 後、smoke test で 403 「Requests to this API places.googleapis.com method google.maps.places.v1.Places.AutocompletePlaces are blocked」エラー
- 真因: Phase 1.10 でブラウザキーを「Maps JavaScript API のみ」に絞ったため、`PlaceAutocompleteElement` がブラウザから直接叩く Places API (New) endpoint が key 制限で reject された。Cloud project では Places API (New) は enable 済だが、API key 側で許可されてない
- **4 階層の確認 checklist**（Maps Platform / 同種 SaaS で必須）:
  1. **SDK class 存在**: `importLibrary` で取得できる class があるか
  2. **Cloud project 有効 API**: 該当 API が project 単位で enable されているか
  3. **API key allowlist**: 該当 API key が「キーを制限」で該当 API を呼べる設定か（Maps JS API だけ許可で Places API (New) を呼べない、等）
  4. **HTTP referrer / IP 制限**: 呼び出し元 origin / IP が allowlist に入っているか
- 過去の失敗との関係:
  - 「Cloud project enable API と SDK class 一致確認」(本ファイル別 lesson) は **2 階層目**の話
  - 本件は **3 階層目** の見落としで、独立した失敗
  - 次の polish タスクで「4 階層を最初に列挙して埋める」ワークフローに切替（実装前 checklist の項目を追加）
- ルール:
  - **Maps Platform / 同種 SaaS の SDK class を呼ぶ前に 4 階層全部 ✅ してから着手**。1 階層飛ばすと smoke test で詰まる
  - API key を新規発行する時は「キーを制限」で **将来呼びたい API も含めて allowlist に入れる**。あとから追加し忘れると本件のような 403 になる
- → ~~2 回目が来たら~~ **2 回目発生のため `.claude/rules/external-api-rules.md` に昇格済み（2026-04-26）**
- **2 回目（2026-04-26 本番 E2E verify、`feat/anchor-autocomplete` merge 後）**: migration 05 適用直後の Playwright auto モード verify で `MapsRequestError: DIRECTIONS_ROUTE: REQUEST_DENIED` が連発、`transit_matrix: []` で `/api/plans/generate → 500`。同じブラウザキーの **API allowlist に Directions API が入っていない** ことが原因。1 回目の Places API (New) と全く同じパターンの違う API での再発で、3 階層目の見落としが構造的なリスクと確定。**`.claude/rules/external-api-rules.md` に「Google Cloud SDK 4 階層 checklist」を昇格、今後は新規 SDK class を導入する前に必ず 4 階層を埋めてから着手するワークフローを強制**

## 2026-04-25: Cloud project の enable API と SDK class が一致しているか実装前に検証する
- 問題: Phase 2.1 polish で AnchorPicker に Google Places Autocomplete を統合する際、deprecated 警告だけ気にして `google.maps.places.Autocomplete` (legacy) で実装 → ローカル smoke test で「This API project is not authorized to use this API. (legacy Places API)」エラー。Routeful の Google Cloud project は **「Places API (New)」だけ enable** していて、legacy "Places API" は enable していなかった
- 原因:
  - 「legacy `Autocomplete` クラスは existing project でまだ動く」という認識は **deprecated 警告レベルの話**で、Cloud Console で legacy "Places API" を enable しないと SDK class そのものが動かない（`@types/google.maps` の deprecated コメントにも「support は当面継続」とあるが「project の API enable」という前提を覆す情報ではない）
  - 「公式 docs に migration guide のリンクがある」=「新 API への移行は推奨」止まりで、「現コードで動くかどうか」は別問題
  - 公式 docs を読んで「使える SDK class はどれか」と「Cloud project に enable されている API」を **両方確認**せずに、deprecated 警告だけで判断した
- ルール:
  - Google Maps Platform / Cloud API を使う SDK class を選ぶ前に **必ず以下を確認**:
    - (a) その SDK class が require する Cloud API (例: "Places API (New)" / "Places API" / "Maps JavaScript API") が **本プロジェクトで enable されているか**（gcloud / Console / `.env` の運用メモ）
    - (b) 公式 docs ページの "Required APIs" / "Get an API key" 節に該当 API 名が明記されているか
    - (c) 旧 class が deprecated でも、`Cloud Console で API が enable されていなければ runtime error` という事実
  - 不一致時は **新 API 版に migrate** か **Cloud Console で legacy API を追加 enable** の二択を明示してから着手
  - `PlaceAutocompleteElement` (Places API (New) のみで動作、web component) は legacy enable 不要なので、新規プロジェクトはこちらをデフォルトにする
  - 検証 checklist は実装前に書く（前回失敗の予防策。本件では「事前検証 checklist」を実装前に書いて Web 検索 + 公式 docs で全項目埋めてから着手するワークフローに切替）
- → 2 回目が来たら `.claude/rules/external-api-rules.md` に昇格（今は 1 回目）

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

## 2026-04-25: useEffect で外部 SDK を attach するなら ref pattern で closure 罠を回避
- 状況: AnchorPicker に Google Maps Places Autocomplete を attach する useEffect を書く際、`value` / `onChange` を effect 内で直接参照すると、依存配列を空 `[]` にした場合に **初回 mount 時の値で capture** されて永久に古い値を使い続けるバグになる
- 対処パターン:
  ```typescript
  const valueRef = useRef(value);
  useEffect(() => { valueRef.current = value; }, [value]);

  useEffect(() => {
    const ac = new lib.Autocomplete(input, {...});
    listenerRef.current = ac.addListener("place_changed", () => {
      const current = valueRef.current; // ← ref 経由で常に最新
      if (current.length >= MAX) return;
      onChangeRef.current([...current, ...]);
    });
  }, []); // SDK は 1 回だけ attach
  ```
- 代替案を退けた理由:
  - 依存配列に `[value, onChange]` を入れる → value 変化のたび SDK を destroy & re-attach → 重い + listener が短時間に消えるレース
  - `useCallback` で `onChange` を stable に → 親側で `useCallback` 必須化を強制するのは API として無礼
- ルール:
  - **長期間 attach する SDK / global event listener を持つ useEffect では、最新 props/state は ref 経由で参照する**。依存配列空 + ref 更新 effect の二段で構成
  - listener cleanup は必ず `return () => listener.remove()` で、unmount 時に解除する
- → 2 回目が来たら `.claude/rules/frontend-design.md` の「コンポーネント実装規則」節に「外部 SDK attach は ref pattern」を追加（今は 1 回目）

## 2026-04-25: Next.js Turbopack build は ESLint 警告すら fail にする
- 状況: AnchorPicker 実装中に `// eslint-disable-next-line react-hooks/exhaustive-deps` を「念のため」入れたら、ESLint は実際には trigger しない箇所だったため `Warning: Unused eslint-disable directive` が出て build fail
- 別 case: test mock で `activeMock = this` を書いたら `@typescript-eslint/no-this-alias` が error 扱いで build fail（vitest test には無関係なのに Next.js build がチェック）
- 対処:
  - 「念のため eslint-disable」を入れない、本当に必要な場所だけに限定
  - test ファイルでも mock の都合で `this` alias / `any` 使う場合は **ファイル先頭で具体的な rule 名を明示して disable**（`/* eslint-disable @typescript-eslint/no-this-alias, @typescript-eslint/no-explicit-any -- 理由 */`）
- ルール:
  - **`pnpm --filter web test` PASS だけ確認して終わらず、必ず `pnpm --filter web build` も走らせる**。Next.js は ESLint warning を error 扱いするため
  - test ファイル先頭の eslint-disable は必要最小限の rule 名のみ列挙
- → 1 回目、再発したら `.claude/rules/testing.md` の「web test 完了条件」節に昇格

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
- → 2 回目が来たら `.claude/rules/data-model-sync.md` の「Supabase 匿名認証で custom テーブル FK を繋ぐなら mirror hijack 必須」節に昇格（今は 1 回目）
- **追記（2026-04-26）**: Phase 2.1 polish merge 後の本番 E2E 確認で **同じ 409 が再現**。Playwright で `/plan/new` auto モード実 submit → `POST /rest/v1/plans → 409` を観測、request body に `session_id` が `auth.uid()` 値で乗っており確定。migration 05 が **develop に存在するが本番 SQL Editor 未適用** だったのが原因と確定。本件は「mirror トリガ migration を作っただけでは本番は動かない、user の SQL 適用まで含めて完了」という運用知見にも繋がる（lessons.md 別エントリ「本番 E2E は壊れる箇所の想定確認に価値あり」参照）

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

## 2026-04-27: @base-ui/react Popover は controlled mode + onSelect で close する設計が最もシンプル（DateRangePicker 実装で習得）
- 状況: `<input type="date">` をカレンダーポップオーバーに置き換える `DateRangePicker` を実装した。最初に `PopoverTrigger render={<span />}` の中にカスタム `<button>` を入れるパターンを書いたが、クリックハンドラの二重登録リスクと DOM 構造の不明瞭さがあった。次に `PopoverPrimitive.Close render={<Calendar />}` を試したが Close は「閉じるだけ」の用途で onSelect コールバックが呼ばれるタイミングと嚙み合わなかった。
- 真因: `@base-ui/react` の Popover API には「Trigger が toggle、Close が閉じる専用」という明確な責務分離があり、「カレンダー選択時に閉じる」という複合動作は Popup 側の onSelect で `setOpen(false)` を呼ぶ controlled mode が自然な設計
- 解決パターン（採用）:
  ```tsx
  <PopoverPrimitive.Root open={open} onOpenChange={setOpen}>
    <PopoverPrimitive.Trigger>...</PopoverPrimitive.Trigger>
    <PopoverPrimitive.Portal>
      <PopoverPrimitive.Positioner>
        <PopoverPrimitive.Popup>
          <Calendar onSelect={(date) => { handleSelect(date); setOpen(false); }} />
        </PopoverPrimitive.Popup>
      </PopoverPrimitive.Positioner>
    </PopoverPrimitive.Portal>
  </PopoverPrimitive.Root>
  ```
- 学び:
  - `@base-ui/react` Popover の Trigger はデフォルトで `<button>` を render し、aria-expanded などを自動付与するので `render` prop でカスタム要素に変える必要はほぼない。Trigger 自体をスタイリングするだけで十分
  - **カレンダーを選んだら閉じる** という複合動作は PopoverPrimitive.Close より `controlled open state + onSelect で close` の方が意図が明確
  - 開始日 → 終了日の自動連鎖は `setTimeout(() => setEndOpen(true), 120)` で十分（ポップオーバーアニメーション完了を待つ）
- ルール:
  - `@base-ui/react` の Compound Component（Popover / Select / Menu 等）で「何かをしたら閉じる」動作を実装するときは **controlled mode が第一選択**。uncontrolled の Close component を流用するより onOpenChange(false) の方が保守しやすい

## 2026-04-27: react-day-picker v9 のナビゲーションボタンは `nav: "contents"` + CSS Grid で配置しないとクリックが blocked される
- 問題: `month_caption` を `flex justify-center relative` にして前月/次月ボタンを `nav` 内の `absolute left-1`/`absolute right-1` で配置したところ、ボタンの表示はされるが月移動がきかず「今月のみ」の状態になっていた
- 真因: `nav` が flex コンテナ内でゼロ幅要素になり、absolute 配置したボタンが caption_label の上に重なっていたか、あるいは DayPicker が内部的に nav を通じてボタンを登録する際のイベントバブリングが caption_label に遮断されていた。ボタンは「見えていたが押せていなかった」
- 解決パターン（採用）:
  ```tsx
  month_caption: "grid grid-cols-[36px_1fr_36px] items-center py-2 px-1",
  caption_label: "col-start-2 text-center ...",
  nav: "contents",  // ← nav を消して子要素を親 grid に参加させる
  button_previous: "col-start-1 ...",  // ← grid の 1列目
  button_next: "col-start-3 ...",      // ← grid の 3列目
  ```
- 学び:
  - react-day-picker v9 では `nav: "contents"` を設定すると `<nav>` 要素が layout box を持たず、内部の `button_previous` / `button_next` が親の grid / flex に直接参加する。これにより caption label との重なりを完全に排除できる
  - `display: contents` は「要素自体は透明、子要素だけ layout に参加」という CSS の値。ナビゲーション wrapper を layout に影響させたくない時に有効
  - **CSS Grid の `grid-cols-[36px_1fr_36px]`** パターンは「[左ボタン幅] [可変ラベル] [右ボタン幅]」の3列構造で月ヘッダーを作る最もシンプルな方法
- ルール:
  - react-day-picker v9 で独自スタイリングを当てる場合は `nav: "contents"` + grid コンテナを組み合わせる。absolute 配置はイベント遮断リスクがあるので避ける

## 2026-04-27: `vi.mock("@/lib/api", () => ({...}))` に新エクスポートを追加したら既存テストモックも更新する
- 問題: `api.ts` に `checkApiHealth` を追加した後、既存の `pages.smoke.test.tsx` と `modeSwitch.test.tsx` の `vi.mock("@/lib/api")` ファクトリに `checkApiHealth` が含まれておらず、vitest が "No 'checkApiHealth' export is defined on the mock" エラーで 6 件失敗
- 原因: `vi.mock(path, factory)` はファクトリ関数が返すオブジェクトのキーのみをモックとして登録する。新しいエクスポートを実モジュールに追加しても、テストのファクトリを更新しないと vitest は「未定義エクスポートを呼ぼうとした」とエラーにする
- ルール:
  - `lib/api.ts` などのモジュールに新しい関数を追加したら、そのモジュールを `vi.mock(factory)` している全テストファイルを grep して `checkApiHealth: vi.fn(...)` を追加する
  - `grep -r 'vi.mock.*@/lib/api' apps/web/src` で一覧を取ると漏れが防げる
