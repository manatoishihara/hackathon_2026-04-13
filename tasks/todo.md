# TODO: Routeful 実装計画

ハッカソン出品までの実装計画。Phase 1 は MVP として必ず完成させる。
各タスクは TDD 形式（テスト先行 → Red → Green → Refactor → 検証）で進める。

---

## 🏁 進捗サマリ（2026-04-28 更新、v6 deploy で 4 日 plan も初成功、v6.1 で UX 完成度 hotfix 中）

**Phase 2 polish v6 (2026-04-28、本番 deploy 完了): 4 日 plan 生成成功実証**: 🟢 commits `c7c2983 / 586ae86 / 95c3fcd`、`707a4e3` で develop merge + push 済。
- 主要変更:
  - assembler **item_type pre-check** (LLM が meal slot に park 等を選んだら事前 swap)
  - **transit duration_min=0 → 最小 1 分補正** (INVALID_TIME_RANGE 防止)
  - prompt v2 system.md 第 6 項で activity / meal / lodging slot の category allowlist 厳守強調
  - Evidence (営業時間 / 評価 / 出典 / verified_at) を pack.places から populate
  - 楽天 lodging API error response body を log に残す診断 logging
- Codex review 2 サイクル (Major 2 + Minor 2 → Blocker 0)、API 439 PASS / Web 164 PASS
- **本番効果実証**: 4 日 plan が初めて 200 達成 (`/plan/[UUID]` 直行)、kind_summary から `item_type_category_mismatch` + `invalid_time_range` が消失

**Phase 2 polish v6.1 (2026-04-28、deploy 後 UX hotfix、user 報告で発覚した 3 件、working tree、未 commit)**:
- **問題 1: Map 不表示** → `apps/web/src/lib/api.ts` の getPlanItems に `_transformPlanItemRow` 追加 (DB flat columns → `location` ネスト変換)
- **問題 2: Evidence「不明」表示** → `getEvidenceBadgeInfo` 4 段階判定に: verified > estimated > unknown+sources → verified 表示 > unknown
- **問題 3: dinner / lodging 欠損 (3 イベント = 9/12/14 時固定)** → system.md 第 4 項を「全 slot 必ず埋めること」に強化 + builder.py の `_BASE_KEYWORD_SUFFIXES` に「旅館 ホテル」追加 + `_MAX_KEYWORDS` 5→7 拡張
- API 439 PASS / Web 164 PASS / tsc / build / secret 0 hit
- **次のアクション (user)**: v6.1 を 2 commits + push、楽天 applicationId を正しい数字 ID に更新、本番再 verify

**Phase 2 polish v5 (2026-04-28、本番 deploy 完了): 3 日 plan が通るようになった**: 🟢 commits `e911d86 / 898f6e8 / 25a9805 / fa1f7d0 / cef1d92 / 92ae85a`、`6af88f5` で develop merge + push 済。重複ポリシーを best-effort 化、lodging 連泊許容、transit skip + ChIJ guard 削除。Codex review 4 サイクル Blocker 0。

---

## 🏁 進捗サマリ（2026-04-28 旧、v5 で 3 日 plan は通過、4 日 plan は構造的に依然 422 — v6 で解消）

**Phase 2 polish v5 (2026-04-28): 実装 + Codex review 4 サイクル Blocker 0 + push + deploy 完了**: 🟢 user 提案「lodging だけ重複完全許容、meal/activity は best-effort 重複回避 + エラー回避優先」を反映した設計変更を `fix/soft-duplicate-with-lodging-allowed` ブランチで commits 3 件、develop merge + push 済 (commit `6af88f5`)。
- **検証結果 (本番 deploy 後 user 報告)**:
  - **3 日 / 80,000 円: 通る** (200 ✅) → v5 効果実証
  - **4 日 / 80,000 円: 依然 422** → 構造的に slot 数 / pack 候補のバランス未解決
  - **生成成功時の plan 閲覧で Evidence (営業時間 / 評価 / 出典) が「不明」**多発 → 別バグ (pack→plan_item の serialization 漏れ)
- **副次発覚**: 楽天 API が `{"error": "wrong_parameter", "error_description": "specify valid applicationId"}` 返却 = **applicationId が rakuten 側で無効**。user 手元の 32 hex chars 値 (`0415bc2d...`) は楽天ウェブサービスの applicationId 形式 (18-19 桁数字) ではない。**user 作業: webservice.rakuten.co.jp で正しい数字 ID 取得 + Render env 更新が必要**
- **lodging.py 改修 (working tree、未 commit)**: rakuten error response body を log に残す診断 logging 追加。本診断のおかげで 400 真因が即判明
- **次のタスク優先順位**:
  1. **user 作業**: 楽天 applicationId を正しい数字 ID に更新 (上記)
  2. **Claude 作業**: Evidence 「不明」表示問題 (pack→plan_item の serialization で opening_hours/rating/sources 埋め) の修正
  3. **継続**: 4 日 plan の 422 残存問題 (Pack 構築時に営業日 filter / search keyword 拡張 / outside_opening_hours retry guidance 強化のいずれか)
- 詳細学び: lessons.md「2026-04-28: Phase 2 polish v5 実装完了 (重複ポリシー best-effort 化 + lodging 連泊許容)」エントリ参照

**Phase 2 polish v4 (2026-04-28): 実装 + push 完了、ただし本番 Run 13e で 422 再発、追加 fix が必要**: 🔴 **`fix/pack-expansion-fuzzy-match` ブランチで A (pack 拡張) + C (fuzzy match) を 2 commits 実装 → develop merge + push 済 (commit `cb39aa5 / 4b96a37`) → 本番 deploy 完了**。**Codex review 1+2 サイクル Blocker 0 認定**。しかし **本番 Run 13e (草津 4 日 / お任せ / 80,000 円) で `/api/plans/generate → 422` 再発**。
- **Run 13e 4 attempts breakdown**:
  - attempt 1: `outside_opening_hours` (草津店舗が 2026-11-22 日曜定休、新パターン)
  - attempt 2: `unknown_place_id` `ChIHhY2RO4...` (`ChIJ` → `ChIH` typo、**Codex review 1 Minor 1 の `ChIJ` prefix guard で fuzzy 救済対象外**)
  - attempt 3: `unknown_place_id` `ChIhY2RO4...` (`ChIJ` → `ChIh` typo、同じく guard で除外)
  - attempt 4: `unknown_transit_edge` (重複防止 swap 連発で候補枯渇、`total_places=17 / used=9`)
- **致命的発見 1**: Codex Minor 1 で追加した `ChIJ` prefix guard が **逆効果**。`ChIH` / `ChIh` の J typo が最頻パターンなのに guard で除外。false positive 抑制 (理論) vs 実本番 typo パターン (実害) の乖離
- **致命的発見 2**: pack cap=22 でも search 結果が薄く pack=17 停止。草津エリアは Google Places retrievable 候補絶対量不足
- **致命的発見 3**: 4 日 lodging slot=3 + 草津 lodging 薄候補で重複完全禁止前提が原理的に不可能
- **v5 fix 候補 (user 判断待ち)**:
  - **MVP-pragmatic** (~10 分): fuzzy guard `ChIJ` → 削除 + lodging 連泊許容 (quota 3→2)
  - **構造的根治** (~30 分): day-scoped duplicate prevention (同日内 unique、日跨ぎ許容)
  - **諦め路線**: Run 13d/13e の知見を残し、demo は 1〜2 日プランか箱根/京都/東京で動作確認に切替
- 詳細: lessons.md「2026-04-28: Phase 2 polish v4 実装 + 本番 Run 13e で別パターンの 422 再発」エントリ
- **モグラ叩き感**: v3 (transit) → v4 (pack + fuzzy) → 422 再発、Phase 2 polish の対症療法が限界。demo 提出後に重複防止設計そのものを見直す必要

**フロント UX: API ヘルスチェックバナーの UX 改善**: ✅ **2026-04-27 完了（commit 提案待ち）**。ページ読み込み直後に「サーバーに接続できません」と表示されていた問題を修正。
- `apiAvailable === null`（確認中）のとき: スピナー + 「サーバーの状態を確認中...」バナー表示、submit ボタンは disabled のまま「プランを生成」
- `apiAvailable === false`（失敗）のとき: 「APIサーバーが起動していません（コールドスタートの可能性）。30秒ほど待ってからページを再読み込みしてください。」+ ボタンに「APIサーバーに接続できません」
- smoke test の `getByText(/プランを生成/)` がボタンテキスト変更で壊れる問題を検出・修正（ボタンは確認中も「プランを生成」を維持）
- web test **158/158 PASS** / tsc clean

**フロント UX: エラー原因の詳細化**: ✅ **2026-04-27 完了（commit 提案待ち）**。`classifyError()` を HTTP ステータス別に分岐し、メッセージ + 詳細説明の 2 段表示に刷新。
- `apps/web/src/app/plan/new/page.tsx`: `classifyError()` を `{ message, detail? }` 返却に変更。422（LLM 検証失敗）/ 429（レート制限）/ 401（セッション認証切れ）/ 403（APIキー制限）/ 404（Evidence Pack 有効期限切れ）/ 502-504（Render コールドスタート）/ 500（サーバー内部エラー）を個別に分類。`TypeError`（ネットワーク失敗）と `AbortError`（タイムアウト）も個別分岐。エラー UI を「太字メッセージ + secondary カラーの詳細説明」2 行表示に変更
- `apps/web/src/app/plan/[id]/generating/page.tsx`: `ApiError` import 追加、catch ブロックで同等のステータス別分岐
- web test **158/158 PASS** / tsc clean


**Phase 2 polish v3 (2026-04-28): 実装完了 + Codex review 5+6 Blocker 0 認定 + 4 commits 提案 → user push 待ち**: 🟢 **`fix/pack-transit-stability` ブランチに T1+T2+T4+T7+T5 を 4 commits で実装**。計画書段階の Codex review 1+2+3+4 で Blocker 0 認定済 → 実装 → **Codex review 5 で Major 1 (`attempted=0 && places.length>1` 抜け穴) + Minor 2 件発覚 → 全反映 → Codex review 6 で Blocker 0 / Major 0 認定**。
- **実装内容** (4 commits 構成、T3/T6 は計画書段階で却下/削除):
  - **Commit A (T1 + Major 1 fix)**: フロント `transit.ts` の `DEFAULT_MAX_PAIRS 20→40`/`DEFAULT_DISTANCE_KM 10→15`/`DEFAULT_GLOBAL_DEADLINE_MS 10_000→15_000`、`transit-guard.ts` の `shouldEarlyThrowOnTransit(stats, placeCount)` シグネチャ拡張で deadline 非依存の常時 coverage チェック (placeCount<=1 許容 / placeCount>1 && attempted=0 throw / succeeded<10 throw / coverage<30% throw)、page.tsx caller 更新、test 9 件
  - **Commit B (T2)**: `_UNKNOWN_PLACE_ID_PATTERNS` に capture group 付き regex `(ChIJ[A-Za-z0-9_\-]{20,30})` 追加、`system.md` v2.0.0 第 9 項「正確コピー」追加 (短縮/省略/推測/合成禁止)、test 3 件
  - **Commit C (T4 + T7 + Minor 1 fix)**: assembly に新 helper `_is_item_type_compatible` (validator helper 再利用、空 category 許容)、`_find_eligible_alternate_for_slot` tier3 に item_type filter + tier3 全落ち専用 warning log、`_find_alternate_place` 候補枯渇 warning log、generator の validate 失敗 log に `kind_summary` (Counter most_common 5)、test 6 件
  - **Commit D (T5 + Minor 2 fix + plan + 進捗)**: `setup-guide.md` 楽天 ID 19-20 桁数字注意、`evidence-pack.md` 距離/最大/秒の数値ドリフト解消、`plans/2026-04-27-pack-transit-stability-fix.md` 計画書、tasks/* 進捗反映
- **検証結果**: API 413 PASS (既知 env 依存 2 件 fail = test_supabase 無関係) / Web 164 PASS / tsc clean / build PASS / secret preflight 0 hit / Codex review 6 Blocker 0
- **Codex review 5 で発覚した Major 1 (重要)**: 旧設計の `attempted === 0` 無条件許容には「places 多数 + 距離フィルタで pair 全落ち」抜け穴があり、空 transit_matrix で `/api/plans/generate` に流れて A6 系 422 連発しうる。`shouldEarlyThrowOnTransit` のシグネチャを `(stats, placeCount)` に拡張、`placeCount > 1 && attempted === 0` で early throw する設計に変更
- **次のアクション (user)**:
  1. 4 commits を順に commit (zsh の `[id]` glob 対策でパスをクォート、Commit A だけ注意): `git add "apps/web/src/app/plan/[id]/generating/transit-guard.ts" ...`
  2. develop merge → push
  3. Vercel + Render auto deploy 完了待ち (~3 min)
  4. **本番 Run 13d (草津 4 日 / 80,000 円 / お任せ、アンカー無し)** で `/api/plans/generate → 200` 期待
  5. **Run 13e (同条件 + 漫画堂 + 湯畑 アンカー)** で 200 確認
  6. (理想) 箱根 + 京都 + 東京 各 1 回 200 確認
- もし 422 残るなら Render Live tail で **Commit C で追加した `kind_summary` log** を確認 → 支配 issue を切り分けて追加 fix を判断可能
- 詳細: `tasks/plans/2026-04-27-pack-transit-stability-fix.md` + lessons.md「2026-04-28: Phase 2 polish v3 実装完了、Codex review 5 で `attempted=0` 抜け穴発覚 → Major 1 fix → review 6 Blocker 0」エントリ
- **副次の UX 課題**: フロント画面の「plan generation failed after retries」が英語のまま (RFC 7807 detail 直接表示)、リトライ動線も不親切。エラー文言日本語化 + 「もう一度試す」改善は別タスク候補

**Phase 2 polish v2 完了部分 (Run 13b 失敗とは独立で価値あり)**: 🟢 **実装 + Codex review 2 + Major 1 fix + 本番 deploy 完了**。toggle UI 削除と段階的 deprecation 自体は完成、UX 改善 (移動手段選択の本質的不要性除去) は実現。Run 13 失敗を受けて user 判断: タクシー利用可前提で「公共交通機関のみ」モードに本質的意味なし、user 指定で plan 失敗は UX 最悪 → toggle 撤回。3 並列 sub-agent で実装、~5 分で完了。
- **設計** (Codex review 1+2 全反映): `parseDirectionsResult` の WALKING > 30 min hard drop 撤廃 + `callDirectionsWithFallback` から DRIVING 除外 logic 削除、常に距離分岐 fallback chain (≤ 2km: TRANSIT → WALKING → DRIVING / > 2km: TRANSIT → DRIVING → WALKING) で全 mode 利用可能
- **Agent 1 (Backend) 完了**: Pydantic `transport_mode: TransportMode | None = Field(default=None, deprecated=True)` で受信のみ許容 (旧 client 互換)、QueryContext / pack / prompt から配線削除、test 5 件削除 + backward compat test 3 件追加
- **Agent 2 (Frontend) 完了**: shared-types / transit.ts/.test.ts / planForm / store / page 2 箇所 / api.test.ts から transport_mode 完全削除 + WALKING 30 min hard drop 撤廃 + `TransportModeSelector.tsx`/`.test.tsx` ファイル削除、test 13 件削除 + documenting test 1 件追加
- **Agent 3 (docs) 完了**: data-model.md の TransportMode 型節を撤回注記に置換、TS ↔ Pydantic 意図的非対称を明記
- **Codex review 2 Major 1 fix**: 旧版で `evidence_pack_sessions` に保存済 pack の `query_context.transport_mode` を新版で復元時 `extra="forbid"` で 404 エラー → `QueryContext` のみ `model_config = ConfigDict(extra="ignore")` 追加で旧 pack を黙って読み捨て、regression test 1 件追加
- **検証結果**: API **403 PASS** (既知 env 依存 2 件 fail = test_supabase、無関係) / Web **159 PASS** (0 fail) / tsc clean / build PASS / secret preflight 0 hit / Codex review 2 **Blocker 0 → OK to commit**
- **次のアクション (user)**: commit 提案を実施 → develop merge → push → Vercel + Render auto deploy → 本番 Run 13b verify (草津 4 日 + 漫画堂/湯畑 アンカー、移動手段 selector が UI から消えた状態で `/api/plans/generate → 200` 期待)
- 詳細学び: lessons.md「2026-04-27: Run 13 失敗を受けて A 案 (transport_mode toggle 撤回) を 3 並列 sub-agent + Codex review 2 サイクルで実装完了」エントリ参照

**Phase 2 polish v1 (撤回中): 3 課題（重複防止 / 楽天 lodging / 移動手段指定）実装 + 本番 Run 13 で `public_transit_only` × 地方温泉地の課題発覚**: 🔴 **実装 + push + deploy 全完了、ただし本番 Run 13 (草津 4 日 / アンカー 2 件 / 公共交通機関のみ) で `/api/plans/generate → 422 "plan generation failed after retries"`**。**Codex review 全 3 回**: review 1 (計画段階、Blocker 2 / Major 3 / Minor 2 / OK 2 全反映) → 実装 → review 2 (実装後、**Critical 0 / Major 1 / Minor 3**) → 反映 → review 3 (**Blocker 0 / OK to commit**)。 **C (移動手段) は v2 で撤回中、A 重複防止 / B 楽天 env は維持**。
- **本番 Run 13 失敗**: フォーム / Autocomplete / TransportModeSelector / アンカー chip / 全フロント機能 ✅、`/api/evidence/places` ✅、`/plan/<UUID>/generating` 遷移 ✅、`fetchTransitMatrix` ✅、ただし `/api/plans/generate` が 4 attempts 全 422
  - **想定原因 (詳細は lessons.md 「2026-04-27: 本番 Run 13 で `public_transit_only` × 草津 4 日…」エントリ)**:
    - **草津エリアは JR 駅から離れたバスのみのアクセス**で `public_transit_only` モードでは TRANSIT が ZERO_RESULTS、WALKING も 30 分超 drop で transit_matrix がスカスカ → `NoFeasibleTransitError` 連発
  - **次のアクション (推奨順)**:
    1. 同フォーム値で `transport_mode = 車も使う` に切替えた **Run 13b** で切り分け → all_modes で通れば transit カバレッジ問題確定
    2. Render Live tail で attempt 別 `[INFO] LLM attempt N` ログを取得、`NoFeasibleTransitError` 支配か `unknown_place_id` 再発か切り分け
    3. 確定後 Phase 3 polish 候補:
       - (a) 公共交通モード時 WALKING 上限を 30 → 60/90 分に緩める
       - (b) DRIVING 完全除外せず「タクシー扱い」で残す
       - (c) 行き先エリアによって UI で「公共交通機関のみは都市部推奨」hint を出す
       - (d) `TransitMode.BUS` 単独 retry path 追加
- (A) DAY 跨ぎ place 重複: `apps/api/src/llm/assembly.py` に `used_place_ids` 追跡 + `_find_eligible_alternate_for_slot` / `_find_alternate_place` の両方に `exclude_place_ids` 引数追加 + 最終 `_drop_duplicate_place_items` (Codex review 2 Major 1 で発覚した「単純 drop が dangling transit を作る」を 2 pass で transit 整合保持に修正)。`prompts/v2.0.0/system.md` 第 8 項「同 place_id 重複禁止」独立追加。test 8 件追加 (3 重複 swap + 5 invariant / dangling)
- (B) 宿情報欠落: コード変更ゼロ。`render.yaml` に `RAKUTEN_APPLICATION_ID` / `RAKUTEN_AFFILIATE_ID` を `sync: false` で追加、`docs/setup-guide.md` に env 取得 + Render Dashboard 投入手順を追記。**user 手動作業**: webservice.rakuten.co.jp で App ID 発行 → Render env 投入 → auto redeploy
- (C) 移動手段指定: 3 点同期 (`docs/data-model.md` → `packages/shared-types` → `apps/api/src/schemas` + parity test) で `TransportMode = "all_modes" | "public_transit_only"` 追加。`Plan.transport_mode` は **DB / RPC スコープ外で除外** (Codex Blocker 2 で軌道修正)。フロー: `/plan/new` の `TransportModeSelector` → `generationSessionStore.transport_mode` (Codex Blocker 1) → `/plan/[id]/generating` で `fetchTransitMatrix({ transportMode })` → `callDirectionsWithFallback` が `public_transit_only` で DRIVING を chain から除外、`parseDirectionsResult` が WALKING で 30 分超を null drop (Codex Major 3)。prompt `_build_mode_context_md` を anchor / theme / transport の独立合成方式 (`"\n\n".join(filter(None,[...]))`) に refactor (Codex Major 2、anchor + transport 併用で transport 落ち回避)。test +13 件追加 (TransportModeSelector 4 / planForm 4 / transit 5)
- **検証結果**: API 404 PASS (既知 env 依存 2 件 fail = test_supabase、無関係) / Web 175 PASS / tsc clean / build PASS / secret preflight 0 hit
- 全 commits は `cba2274 / 1bfe503 / 98fb8b8 / a113c55 (merge)` で develop merge 済 + push 済
- 詳細学び: lessons.md「2026-04-27: 本番 Run 13 で `public_transit_only` × 草津 4 日 × アンカー 2 件 で 422 連発」+「2026-04-27: Phase 2 polish の実装完了 — Codex review 2 で発覚した『defense-in-depth の要素削除が隣接参照の整合性を壊す』設計バグ」

**Phase 1.10 後段 fix: EvidenceModal / MapView の location undefined セーフガード (`fix/evidence-modal-undefined-location`)**: ✅ **2026-04-27 セッションで実装 + push + 本番 Run 12 で動作確認完了**（develop merge + push 済、commit 72b2c93 / 96e228b）。本番 Run 11 で `/api/plans/generate → 200` 達成 + `/plan/[id]` 遷移成功を確認したあと、**プラン閲覧画面で React render error** (`Cannot read properties of undefined (reading 'place_id')`) が発覚。Phase 2.5 evidence modal の design 仕事で safety check が漏れた regression。`apps/web/src/components/EvidenceModal.tsx:42` の `item.location.place_id` access を optional chaining (`item.location?.place_id ?? null`) に修正、`apps/web/src/components/MapView.tsx:29` も `i.location != null && ...` で undefined 除外。`EvidenceModal.test.tsx` に「location 削除でも crash しない」1 件追加。test 148/148 PASS（既知 6 件 pre-existing は本変更無関係）。push → Vercel auto deploy → プラン閲覧画面で正常 render すれば demo 完全完成。詳細は lessons.md「2026-04-27: 本番 Run 11 で **422 全塞ぎ fix の効果実証** + プラン閲覧画面の独立 React error 発覚」エントリ。

**Phase 1.10 本番 Run 11 (2026-04-27 セッション末)**: 🟢 **422 全塞ぎ fix の効果が本番で完全実証**。Vercel + Render auto deploy 完了後、Playwright で `/plan/new` 提出 → URL が `/plan/10524736-4767-40b2-bcd8-93957b2fcd68`（`/generating` なし）に遷移 = `/api/plans/generate` が 200 を返した動かぬ証拠。canonical 8 点 + retry guidance + previous_issues 累積化が効いた。**Run 10 (422)** → **Run 11 (200)** の決定的な転換。ただし閲覧画面で React error 発覚（次の fix で対応中）。

> 📌 **2026-04-27 セッション末の git 状況（本 merge commit で解消）**:
> - ローカル develop の私の 4 commits + origin/develop の design 仕事 5 commits を本 merge commit で統合
> - 自動マージ成功: `apps/web/src/app/plan/[id]/generating/page.tsx`（origin の FlyingPlane 演出 + 私の早期 throw が両方残った）/ `tasks/lessons.md` 等
> - 手動 merge: 本ファイル `tasks/todo.md`（origin の calendar UI / DateRangePicker entry + 私の Phase 1.10 全塞ぎ entry を両方保持、origin に残存していた壊れた marker `>>>>>>> 4fe0c10...` も本 commit で除去）
> - **次セッション最初のタスク**: 本 merge commit を push → Vercel/Render 再 deploy → 本番 Run 11 で `/api/plans/generate → 200` + `/plan/[id]` 遷移を必須条件で確認

**カレンダーナビゲーション UI 改善**: ✅ 2026-04-27 完了（commit 提案待ち）。DateRangePicker の月移動ボタン UX をポリッシュ。
- `apps/web/src/components/ui/calendar.tsx`: 前月/次月ボタンを `ArrowLeft`/`ArrowRight`（Phosphor regular 15px）に換装、`rounded-full` + hover fill navy（primary 色）+ `active:scale-90` プレスフィードバック、`nav: "contents"` + CSS Grid で月移動ボタンが確実にクリック可能に（旧 absolute 配置による blocked クリック問題を完全解消）
- `apps/web/src/app/pages.smoke.test.tsx` / `src/app/plan/new/modeSwitch.test.tsx`: `checkApiHealth` モック追加（`vi.mock("@/lib/api")` が新エクスポートを知らずテスト 6 件失敗していた問題を修正）
- web test **147/147 PASS** / tsc clean

**日付入力 UI 改善 (DateRangePicker)**: ✅ 2026-04-27 完了（commit 提案待ち）。`<input type="date">` のネイティブピッカー（OS/ブラウザ依存で使いにくい）をカレンダーポップオーバーに刷新。
- `react-day-picker@9.14.0` を `apps/web` に追加（date-fns 不要、native Date のみ）
- `apps/web/src/components/ui/calendar.tsx` 新規作成（blue hour デザイントークン適用、日本語曜日ラベル）
- `apps/web/src/components/ui/popover.tsx` 新規作成（`@base-ui/react/popover` ベース、制御モード対応）
- `apps/web/src/components/DateRangePicker.tsx` 新規作成（開始日 → 終了日ポップオーバー自動連鎖、終了日は開始日より前を disabled、後ろにずらすと終了日自動リセット）
- `apps/web/src/app/plan/new/page.tsx` の `start_date` / `end_date` フィールドを `DateRangePicker` に差し替え
- tsc clean / build PASS（`/plan/new` バンドル 417kB、増加なし）

**Phase 1.10 後段: 422 真因全塞ぎ (`fix/plan-generation-blockers`)**: 🟡 **2026-04-27 セッション末で実装完了 → ローカル merge 済 → user push 待ち（divergence 解決必要）**。本番 Run 10 で発見した 2 真因 (candidate_departures 1 件 / LLM hallucination) + Codex review 1+2+3 で発覚した追加 Blocker 2 / Major 4 / Minor 2 を網羅的に修正。フロント canonical 8 点 + 早期 throw、バック retry guidance + previous_issues 累積化 (recency 保証 `pop + 再挿入`) + regex robust 抽出。test 全 PASS / tsc clean / build PASS / Codex 最終 review Blocker 0。push → 本番 Run 11 で **`/api/plans/generate → 200` + `/plan/[id]` 遷移**を必須条件で確認。詳細は `tasks/plans/2026-04-27-plan-generation-blockers.md` + lessons.md「2026-04-27: 全塞ぎモード」エントリ。

**Phase 1.10 後段 chore: Flask logging.basicConfig(INFO) 追加**: ✅ **2026-04-27 セッションで実装 + push + 本番 deploy 反映完了**（`chore/api-logging-config` ブランチ → commit 148f4be → develop merge 13ba685 → push 済）。`apps/api/src/app.py` 冒頭に `logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO").upper(), ...)` 追加。`LOG_LEVEL` env で上書き可。API unit test 381/381 PASS。**効果実証**: 本番 Run 10 で Render Live tail に `[INFO] src.llm.generator: LLM attempt 1 (model=gpt-4.1) assembly error (kind=unknown_place_id), retrying: ...` のような retry 詳細 4 行 + assembler self-healing の `[WARNING] src.llm.assembly: LLM picked ineligible place ... swapped to ...` まで取得できた。詳細は lessons.md「2026-04-27: Flask デフォルト logger は WARNING 以上のみ」エントリ。

**Phase 1.10 本番 Run 10 (2026-04-27 セッション末)**: 🔴 **422 真因が完全に判明**。logging.basicConfig(INFO) 反映後の本番 Run 10 (plan_id `9b209857-c9b2-4dba-acfb-d3352936b293`、04:54-04:55) で Render Live tail から **4 attempts 全失敗の breakdown** を取得:
- attempt 1 (gpt-4.1): `unknown_place_id` (day1_lunch、`ChIJJS7EfYgChGWARNW9YGF4jb0I`)
- attempt 2 (gpt-4.1): `unknown_transit_edge` (`candidate_departures=['13:54']` で required `start_hhmm='16:30'` カバー不能)
- attempt 3 (gpt-4.1): `unknown_place_id` (day1_dinner、attempt 1 と**同じ** ID 再出現)
- attempt 4 (gpt-4.1-mini): place swap 成功 (assembler self-healing 動作) したが、別 edge の `candidate_departures=['13:54']` で `'16:30'` カバー不能

**真因 A（構造、最優先）**: `apps/web/src/lib/transit.ts:300-302` の `parseDirectionsResult` が `candidate_departures` を **常に 1 件しか返さない**。`verify_hallucination_rate.py` は 5 点で test していたが、本番フロント (Phase 1.3b) は submit 時刻 1 点だけ → assembler の「16:30 以降出発」要件を満たせない = **Phase 1.3b ↔ 1.3e の contract drift**。

**真因 B（次点）**: gpt-4.1 が `ChIJJS7EfYgChGWARNW9YGF4jb0I` を 2 回繰り返しハルシネーション。Phase 1.3e で 0% 達成済みのはずが本番条件で再発。問題 A 解消後に再測予定。

詳細は lessons.md「2026-04-27: 本番 Run 10 で 422 真因判明 — `candidate_departures` 1 件問題（Phase 1.3b ↔ 1.3e 不整合）+ `unknown_place_id` ハルシネーション再発」エントリ。次セッション最優先で `tasks/plans/2026-04-28-candidate-departures-multi.md` 起案 → Codex review → 実装。

**Phase 1.10 本番 Run 9 (2026-04-27 セッション中盤)**: 🟢 **transit fallback fix が本番でも実証**。Vercel + Render 両方で `develop` の最新 commit が auto deploy 済、`/plan/new → /plan/<id>/generating` まで遷移、Maps SDK 40 回 ZERO_RESULTS の後 fallback で `/api/plans/generate` まで POST 到達（`transit_matrix=[]` でなくなった）。

**Phase 1.10 fix: Maps Directions travelMode 距離分岐フォールバック**: 🟢 **2026-04-27 セッションで実装完了 + ローカル verify 完了 + 本番 push 完了 + 本番 Run 9 で fix 実証**（`fix/transit-fallback-walking-driving` ブランチ → develop merge → push 済、commit ce3dabd 含む）。`apps/web/src/lib/transit.ts` の travelMode 固定を「距離 ≤ 2km は TRANSIT → WALKING → DRIVING、> 2km は TRANSIT → DRIVING → WALKING」の fallback chain 化。Codex review 2 回（review 1 で「徒歩 2 時間 plan が assembler 経由で 422 を生む」を Major で発覚 → 距離分岐に軌道修正、review 2 で test 設計 bug 2 件発覚 → 反映）。web test 147/147 PASS / tsc clean / build PASS / API regression 381/381 PASS。**ローカル verify**: stats 40/40 全成功、mode_counts walk 20 / car 20、duration 5-46 min avg 18 min。**仮説修正**: 「transit fallback で 422 も解消する」は誤り、422 は LLM validator 側の独立問題（次の Run 10 で詳細 log 取得予定）。詳細は `tasks/plans/2026-04-27-transit-fallback.md` + lessons.md「2026-04-27」3 エントリ。


**DB-4/DB-5 テスト**: ✅ 2026-04-26 完了。`apps/api/tests/test_share_routes.py` を新規作成（11 件）。share_routes.py / plan_cache.py / extensions.py の実装は既完成済みで、テストのみ追加。全 unit テスト 332 件 PASS（既存 2 件の env 依存失敗は本変更と無関係）。

**楽天トラベルAPI連携 (DB-7)**: ✅ 2026-04-26 実装完了。`apps/api/src/evidence/lodging.py` 新規作成（`RAKUTEN_APPLICATION_ID` / `RAKUTEN_AFFILIATE_ID` 環境変数から読み込み、ホテル名・料金・緯度経度・URL を `LodgingOption` で返す、fail-soft 設計）。`pack.py` に `lat`/`lng` フィールド追加、`builder.py` に組み込み（日帰りスキップ）。`tests/test_lodging.py` 5 件 PASS。

**DB-8 Supabase ロギング基盤**: ✅ 2026-04-26 SQL migration 作成完了。`supabase/migrations/20260426_08_logging_setup.sql` を新規作成。`pg_stat_statements` 拡張有効化 + `routeful_query_stats`（上位 50 クエリ、total_time 降順）/ `routeful_slow_queries`（mean_exec_time > 100ms）ビュー + `reset_routeful_query_stats()` リセット関数。**Supabase SQL Editor での適用が必要**（冪等設計）。

**サイトアイコン (favicon / apple-icon)**: ✅ 2026-04-26 完了。`apps/web/public/icon.svg`（Deep Navy 角丸 + Coral 経路曲線 + waypoint ドット）/ `apps/web/src/app/apple-icon.tsx`（Next.js ImageResponse 180×180）/ `layout.tsx` の `metadata.icons` + `openGraph` を設定。

**フロント UX 改善（連続クリック防止・エラー分類・API 死活確認）**: ✅ 2026-04-26 実装完了（commit 提案待ち）。
- `apps/web/src/lib/api.ts` に `checkApiHealth()` 追加（`GET /healthz`、5s timeout、MOCKS 時は常に `true`）
- `apps/web/src/app/plan/new/page.tsx` に以下を追加:
  - マウント時 API ヘルスチェック → `apiAvailable` state。API 未接続時は amber バナー + submit ボタン「サーバー未接続」表示 + disabled
  - `classifyError()` でネットワーク障害 / 5xx サーバーエラー / 401/403 認証エラー を日本語メッセージに分類
  - submit 中は `SUBMIT_STEP_LABELS`（session / plan / evidence の 3 ステップ）をボタン内テキストで逐次表示
  - submit ボタンに `aria-busy` 属性追加（アクセシビリティ対応）
  - エラー表示に `WarningCircle` アイコン追加

## 🏁 進捗サマリ（2026-04-25 更新）

**Phase 0**: ✅ 完了
**Phase 1.1〜1.3d (実装)**: ✅ コード完了（バック: データモデル、Evidence Pack Builder、Transit Validator、LLM 生成 + ハルシネーション検出 + plan_items 保存、RLS E2E、pg_cron）
**Phase 1.3d (実環境検証)**: ⚠️ **未達**。2026-04-25 に `verify_hallucination_rate.py` を計 3 回実行。10 runs × 2 回は hallucination 10%（`unknown_place_id` 主因）、その後 prompt token 圧縮（22,385→11,645、-48%）+ opening_hours 強調 + transit trim を施した 5 runs は hallucination 20% に悪化（`unknown_transit_edge` 7 件が新規噴出、**制約押し出し現象**）。詳細は @tasks/lessons.md 2026-04-25 エントリ

**Phase 1.3e (Structured Plan Assembly, LCaMO 応用)**: 🟢 **β は develop マージ済み・area exclude + case-insensitive + per-slot eligibility hint + hard self-healing は本セッションで実装（uncommitted、commit 提案待ち）**。schema v2 + assembly + prompts v2 + generator v2 分岐 + 代替選定第 1〜2 弾 + β（merged）+ area exclude + case-insensitive matching（曖昧一致は fail-fast）+ per-slot eligibility hint + hard self-healing（ineligible → 同カテゴリ eligible 自動差し替え）+ 全 266 件 unit test PASS。`verify` 反復履歴:
  - run 1〜3（β 前）: hallucination=0% / unknown_transit_edge=3→0 / departure_mismatch=18 等の押し出し
  - run 4: candidate 10 点で prompt 14.6k → hallucination 66.7%
  - run 5（candidate 10→3）: prompt 12,547 tok / hallucination 33.3%
  - **run 6（β 実装後、develop マージ済み）**: prompt < 12k / hallucination 0/3 / success 0/3
  - **run 7（area exclude 実装後）**: success **1/3 (+1 改善)** / hallucination 1/3（gpt-4o-mini case mismatch、3-run noise）
  - **run 8（+ case-insensitive matching、`--runs 5`）**: **success 2/5 (40%) / hallucination 0/5 = 0% PASS**、residual `outside_opening_hours=2/run`
  - **run 9（+ rule 5 強化試行）**: success 0/5 / hallucination 1/5 → **revert**
  - **run 10（run 8 同条件で再検証）**: success 2/5 / hallucination 1/5 → 5-run サンプリングノイズと判明
  - **run 11（per-slot eligibility hint 実装後、外乱含む）**: hallucination 0/5、outside_opening_hours=1（外乱で run 5 件中 2 件汚染）
  - **run 12（再検証、外乱なし）**: hallucination 0/5、outside_opening_hours=9 → soft hint だけでは LLM が rule を無視と判明
  - **run 13（hard self-healing 実装後）**: hallucination 0/5、**outside_opening_hours=6 (run 12 比 -33%)**、budget_exceeded=2。assembler が ineligible pick を 1 attempt あたり 3 件自動 swap

**主目的「hallucination 構造的 0%」+ 副次「success rate 100%」を本セッションで完遂**（11 段の累積改修 + Codex レビュー反映、試行錯誤の物語は @tasks/plans/2026-04-25-structured-plan-assembly.md 末尾「本セッションの試行錯誤の物語」参照）。**(ix) gpt-4.1 採用 + (x) Codex 深掘りレビュー反映で success 100% 到達**:
  - **hallucination 0% (50+ sample 累計 0% 維持)**、**success rate 100% (10/10、2 連続 5-run)**、平均 **4.4 秒/run**（gpt-5 から 38x 高速）
  - **Codex 指摘 3 件を修正**（同種「複数制約次元の一部のみ check」構造 bug の網羅）:
    - **Critical**: post-shift で start_dt が opening close 超え → `is_place_open_at_dt` helper 追加 + `IneligiblePlaceForSlotError` raise
    - **Major**: `_find_eligible_alternate_for_slot` が transit 到達可能性を見ない → `prev_place_id` 引数で reachable_ids 必須フィルタ
    - **Major**: `_pick_departure_time` max() fallback が過去出発時刻を返す → 過去のみなら `NoFeasibleTransitError` raise、verify の candidates を 5 点 (`["09:00","12:00","15:00","18:00","21:00"]`) に拡張
  - **以前の改修**: `_find_alternate_place` の eligibility check 漏れも本セッション内で発見・修正済み（同一パターン）
  - 詳細 issue ログを `verify_hallucination_rate.py` に永続化（再現性ある bug 検知の土台）
  - **次セッション候補（Codex 残課題）**: (latent) 営業時間 parser の日跨ぎ対応 / (Minor) item_type vs category 整合性 validator
  - 設計書 + 全 run 詳細 (run 4〜27) + Codex review 全文 + 工夫まとめは @tasks/plans/2026-04-25-structured-plan-assembly.md
**Phase 1.4〜1.9 骨組み**: ✅ 完了（フロントの配線層、デザイナーへ引き渡し済み）

**Phase 2.5 Evidence 詳細モーダル**: ✅ **2026-04-26 完了（develop マージ済 commit 98e37fe + 872140d）**。EvidenceBadge を `onClick` 有無で span/button 切替、EvidenceModal で 5 フィールド（営業時間 / 評価 / 価格帯 / 出典 / 検証日時）+ Google Maps 公式 URL 形式の外部リンク（place_id があるとき）。`formatVerifiedAt` を JST 固定で追加、Phosphor X close ボタン、a11y (aria-labelledby / 新規タブ告知)、不在「— 不明」統一。Codex review 1+2 回目で Blocker 2 / Major 6 / Minor 1 を全反映。**web test 130/130 PASS / tsc clean / build PASS**。詳細は `tasks/plans/2026-04-26-evidence-detail-modal.md`

**Phase 2.2 予算配分の制約化**: 🟡 **2026-04-26 実装完了、commit 提案待ち**（`feat/budget-constraint` ブランチ、user 手動 push 待ち）。`_build_budget_context_md(budget_constraints)` を `apps/api/src/llm/prompt.py` に追加し、v2 prompt に「予算配分の絶対制約」Markdown を `mode_context_md` 直後に注入。カテゴリ別上限（宿泊/食事/観光/交通）を 3 桁区切りで明示、`BUDGET_TOLERANCE_RATIO` 連動で「+5% 許容」表記、LLM に slot 配分で守れと指示。v1 prompt は変更なし（後方互換）。Explore agent で現状調査 → plan 起案 → Codex review 1（Blocker 0 / Major 3 / Minor 3 / OK 5）反映 → TDD 実装 → Codex review 2（Blocker 0 / Major 0 / Minor 2）反映、の流れ。**API unit test 27/27 PASS（既存 16 + 新規 11）、prompt token +216（実測、警告閾値 12k 内）**。手動 verify（Run A 通常配分 + Run B 宿泊 80%）は MVP 提出優先で skip 可、smoke test 一括時に判断。設計詳細は `tasks/plans/2026-04-26-budget-constraint.md`

**🔴 セキュリティインシデント（2026-04-26）**: 🟡 user 対応中。docs に Google Maps ブラウザキーを文字列として埋め込んだ commit 215570e を public repo に push し、GitHub Secret Scanning が検出 + Google にアラート送信。**対処**: (a) user が Google Cloud Console で旧 key を rotate / 新 key 発行 / Vercel env 更新 / redeploy、(b) Claude が working tree の todo.md / lessons.md から key 文字列を redact 済（commit 提案待ち）。詳細は @tasks/lessons.md「docs / todo に API key 文字列を貼ったら Public repo の Secret Scanning が即検出」エントリ参照。再発防止ルールを `.claude/rules/external-api-rules.md` 昇格候補に

**Phase 1.10 Render 先行デプロイ**: 🟢 2026-04-25 完了。`https://routeful-api.onrender.com/healthz` が `{"service":"routeful-api","status":"ok"}` を返す状態。Singapore region / NRT edge 経由 / cold start ~0.4s / CORS ヘッダ動作確認済（`access-control-allow-origin: http://localhost:3000` が env から正しく echo back）。次は RLS 42501 解消 → Vercel deploy → CORS_ALLOWED_ORIGINS を Vercel URL に書き換え。

**Phase 1.10 本番 E2E 動作確認（2026-04-26）**: 🟡 **migration 05 適用で 409 解消、ただし Maps Directions API allowlist 漏れの新ブロッカー発覚**。経緯:
  - **Run 1（migration 05 未適用）**: Playwright で `/plan/new` auto モード submit → `POST /rest/v1/plans → 409 Conflict` で失敗、`PATCH ... {"status":"failed"}` で遷移失敗。FK 23503 仮説を本番実証
  - **Run 2（user が migration 05 を SQL Editor で適用後）**: 同条件で再 submit → `plans INSERT → 201` / `participants INSERT → 201` / `PATCH status='generating' → 204` まで通過、`/plan/<UUID>/generating` へ遷移成功。**migration 05 fix が本番で効くことを実証**
  - **Run 2 の後段で新ブロッカー**: ブラウザ Maps JS SDK の `DirectionsService.Route` が **全 call `MapsRequestError: DIRECTIONS_ROUTE: REQUEST_DENIED`** で失敗、`transit_matrix: []`（空配列）のまま `/api/plans/generate` に POST → サーバが 500 で `status='failed'` 転落。原因はブラウザキー（**※2026-04-26 に旧 key を rotate 済、commit 215570e 以前の git 履歴に文字列が残るため過去 key は無効化済**）の API restrictions に **Directions API** が入っていない（lessons.md「Google Cloud SDK 4 階層 checklist」3 階層目の **2 回目の見落とし**、Phase 1.10 で Places API (New) で同じパターンあり）
  - **次のアクション（user 作業）**: Google Cloud Console → Credentials → 該当ブラウザキー編集 →「キーの制限」「API の制限」に **Directions API を追加**（Maps JavaScript API / Places API (New) は維持）+ APIs & Services → Library で **Directions API が project で Enabled** か確認。反映後 Playwright で auto/anchor/theme 3 モードを再 verify
  - **Run 3（user 1 回目の Directions API 設定試行後）**: Playwright で同条件 submit、依然 `REQUEST_DENIED` 14 件 + `/api/plans/generate → 500`。ブラウザキー（rotate 前の旧 key、現在は無効）は変わっておらず、設定が(a) 反映待ち中 / (b) 「Restrict key」で別 API を追加 / (c) project Library で "Directions API"（legacy）が enable されていない / (d) 保存忘れ、のいずれかと推定。User に再確認依頼中。**ブラウザキーとサーバキーの API 分離知見**は @.claude/rules/external-api-rules.md「キー別 API 必要性早見表」節を参照（フロント DirectionsService が legacy "Directions API" を叩く事実、サーバ Places API (New)/Routes API/Geocoding API の必要度の差）
  - **Run 4（user 2 回目の Directions API 設定後、2026-04-26）**: **REQUEST_DENIED が 0 件に解消** (Maps SDK 動作 ✅)。`/api/evidence/places → 200` も維持。**ただし新たに 2 つの未解決問題が浮上**:
    - **問題 (i)**: `/api/plans/generate → 500`、エラー本文 `"failed to acquire plan lock"`。これは `apps/api/src/routes/plan_routes.py:110` の **`except Exception` 想定外例外パス**でしか出ない文字列で、`acquire_plan_generation_lock` RPC コール時に raise されている = **migration 04 (`20260424_04_plan_generation_rpcs.sql`、Phase 1.3d Branch B 実装) が本番 SQL Editor 未適用**の可能性大。冪等なので user に SQL Editor で再実行依頼必要
    - **問題 (ii)**: フロントが送る `transit_matrix: []` が **依然空配列**。Maps Direction API は反応するようになったが edge が 0 件。原因不明、要追加調査:
      - 仮説 (a): 箱根の places が 14km 以内 filter で全ペア弾かれ skip
      - 仮説 (b): `apps/web/src/lib/transit.ts` の deadline 10s に Maps SDK ロード時間が間に合わず global timeout
      - 仮説 (c): フロント logic bug（places 配列が空のまま渡してる、submit 時の race 等）
      - 問題 (i) 解消後に LLM 生成側で `transit_matrix=[]` を許容するか、validator で 422 reject になるかで切り分けやすくなる
  - **次のアクション（user 作業）**: `supabase/migrations/20260424_04_plan_generation_rpcs.sql` を Supabase SQL Editor で実行（冪等、既に適用済みでも害なし）。実行後に再度 auto モードで Playwright submit して、エラーが「failed to acquire plan lock」から別エラーに変わるか確認
  - **Run 5（migration 04 未適用のまま、Phase 2.2 + Vercel key 更新後）**: 依然 `failed to acquire plan lock` 500、ただし Vercel 新 key は反映済み（REQUEST_DENIED 0 件、`/api/evidence/places → 200`）。migration 04 適用が次の必須作業
  - **Run 6（user が migration 04 を SQL Editor で適用後）**: エラーが 500 → **409 `plan is already being generated`** に変化。**migration 04 RPC 動作確認**。ただし新たな**フロント設計バグ**が浮上: フロント `apps/web/src/app/plan/new/page.tsx` line 232 の `updatePlanStatus(planId, "generating")` が `/api/plans/generate` 呼び出しの **前**に走り、サーバ `acquire_plan_generation_lock` の compare-and-set (`status IN ('draft', 'failed')` のときのみ acquire) を破壊。Phase 1.3d Branch C と整合していなかった
  - **fix/plan-status-lock-mismatch ブランチで対応** (2026-04-26、`b97567b` で develop merge): フロントの `updatePlanStatus(generating)` 削除、サーバ acquire_lock が draft→generating 遷移する設計に統一。failed PATCH は維持。web test 130/130 PASS / tsc clean / build PASS
  - **Run 7（fix 全反映後、2026-04-26）**: **Vercel 新 key + migration 04 + フロント fix 全部効く**:
    - ✅ PATCH status='generating' が消えた
    - ✅ サーバ acquire_lock 成功 (draft→generating)
    - ✅ LLM 生成試行（Phase 2.2 prompt 含む）
    - ❌ **`/api/plans/generate → 422 "plan generation failed after retries"`** = LlmGenerationError、3 回 retry 後も validator reject
    - ❌ **transit_matrix=[] のまま**（Run 4 から続く謎）
  - **Run 7 で transit_matrix=[] の真因を突き止め**: `/api/evidence/places` を直接叩いて検証 → **places 10 件全部が箱根湯本駅周辺の飲食店ばかり**（HAKONE PICNIC / 箱根食堂 / 肉のKINOSUKE / 箱根BOOTEA / BOX BURGER / 森メシ / 日清亭 / Funny's 等）、互いの距離 0.01〜0.26 km（100m 以内）、観光地・宿泊・温泉施設 0 件。Maps Directions の TRANSIT が至近距離で `ZERO_RESULTS` を返す → transit_matrix=[] → LLM がプランを組めず 422
  - **次のアクション（Manato）**: `apps/api/src/evidence/places.py` の text search keyword 生成ロジックを確認し、`region: '箱根'` で **観光地 / 温泉宿 / 食事処の混合**になる候補生成に修正。Phase 2.3 楽天連携の builder.py 変更は places 検索を触っていないので無関係
  - **Run 8（ローカル、Phase 1.10 Evidence Pack 多様性 fix 後、2026-04-26）**: `feat/evidence-pack-diversity` で `_generate_keywords` 4 軸拡張 + `_classify_bucket` + bucket quota + 距離ガード + MIN_PLACES 補填を実装、ローカル `pnpm dev` で verify。**Phase 1.10 fix の効果は完璧に確認**:
    - places **12 件**（旧 10）、観光地 7（彫刻の森美術館 / 箱根神社 / 強羅公園 / 関所 / 園 / 飛竜の滝 / 玉簾の瀧）+ 飲食 5（喜之助 / 箱根食堂 / 森メシ / 銀の穂 / いろり茶屋）の多様な構成
    - 互いの距離 **0.64〜9.57 km**（旧 0.01〜0.26 km）、66 ペア全て 10km 以内 = フロント transit fetch の対象
    - **しかし新ブロッカー (Run 8 で発見)**: フロント `fetchTransitMatrix` の stats が `{attempted: 40, succeeded: 0, errors: 40, timedOut: 0, deadlineReached: false}` で、**Maps Directions の TRANSIT モードが 40 ペア全部 ZERO_RESULTS を返す**。これは Maps Directions の TRANSIT が「観光地間の公共交通機関経路」を返さない（観光地は徒歩 / 車アクセスが基本で、駅から駅の TRANSIT データセット圏外）という構造的問題で、Phase 1.10 多様性 fix とは別軸の課題
  - **次のアクション (`fix/transit-fallback-walking-driving` ブランチで対応予定)**: `apps/web/src/lib/transit.ts:333` の `travelMode: "TRANSIT"` 固定を **TRANSIT → WALKING → DRIVING のフォールバック** に変更。TRANSIT が ZERO_RESULTS でも WALKING / DRIVING でなんらかの経路を返す前提（同じ街中で徒歩 5km は十分歩ける、車なら確実）。実装 ~50 LOC + test ~30 LOC、Phase 1.10 fix と独立 commit
  - **並行発見**: `supabase/migrations/` に `20260425_05_*` ファイルが **2 つ** (`auth_user_sessions_mirror` / `index_optimization`) 存在する連番衝突。`all_migrations.sql` の sort 順が曖昧になるので、適用後に `index_optimization` を 06 にリネーム or 連番ルールの再整理を別タスク化推奨。詳細は @tasks/lessons.md 2026-04-26 エントリ + @.claude/rules/external-api-rules.md（2 回目から rule 昇格）参照

**Phase 1.10 Vercel 設定とビルド修正**: 🟡 2026-04-25 セッションで Vercel ビルド成功まで到達（`pnpm --filter web build` ローカル PASS / Web test 61/61 PASS）、本番 deploy は user push 後に確認。経緯:
  - Vercel UI Root Directory picker が monorepo 中間 `apps/` を表示しない罠 → Plan B（root deploy → Settings 修正 → Redeploy）で迂回
  - 設定: Root Directory `apps/web` / Install Command `pnpm install` / Production Branch `develop` を Settings の `Build and Deployment` / `Environments` 配下で個別設定（旧 UI と場所違い）
  - Production Branch 切替後の Redeploy は元 deploy の branch を継ぐので、新規 deploy トリガーには `develop` への empty commit push が必要だった
  - **build 失敗 1**: pnpm strict isolation × `@hookform/resolvers@5.2.2` の peer 宣言漏れで `Module not found: zod/v4/core` → `.npmrc` の `public-hoist-pattern[]=*zod*` で解消
  - **build 失敗 2**: `transit.test.ts` の ESLint `no-explicit-any` 4 件（mock 用の意図的 any）→ file-level `eslint-disable` 1 行で解消
  - 残: `develop` push → Vercel auto deploy → URL 確定 → Render の `CORS_ALLOWED_ORIGINS` 更新 → Google Maps browser key referrer に Vercel URL 追加 → 本番 E2E 確認

**Phase 1.10 デプロイ準備（コード側）**: ✅ 2026-04-25 セッションで完了（`feat/deploy-prep` ブランチ、API unit 283 件 PASS / Web 61 件 PASS / gunicorn smoke OK）。デプロイ前ブロッカーをまとめて解消:
  - **CORS 追加**: `flask-cors` 導入 + `apps/api/src/app.py` に `_resolve_cors_origins()` 実装。env `CORS_ALLOWED_ORIGINS`(CSV) 読み、未設定時 `http://localhost:3000` のみ。`Authorization` / `Content-Type` 許可、`GET/POST/OPTIONS` 許可。CORS テスト 6 件
  - **gunicorn 追加**: `requirements.txt` に追加、`--workers 1 --timeout 180` で起動 smoke OK
  - **render.yaml 新規作成**: Singapore region / healthCheckPath /healthz / 秘密値は `sync: false` で Dashboard 経由
  - **PROMPT_VERSION_DEFAULT を v2.0.0 に昇格**: Phase 1.3e 実証版（hallucination 0% / success 100%）を本番 default に。env 設定漏れでも v1（10〜67% hallucination）にフォールバックしない安全配線
  - **validator: item_type vs category 整合性チェック**（Codex Minor 残対応）: `IssueKind.ITEM_TYPE_CATEGORY_MISMATCH` 新設、`_MEAL_CATEGORIES`/`_LODGING_CATEGORIES` allowlist + Google Places `*_restaurant` 接尾辞許容。meal slot に観光地のみ・lodging slot にレストランのみ等の semantic mismatch を検出。テスト 10 件
  - **docs/setup-guide.md** を Render Blueprint 経由フローと CORS env で刷新
  - **デプロイ実施は user 作業**（Vercel/Render アカウント作成、env 入力、Settings UI で HTTP Timeout 180s）

**分業土台**: ✅ 2026-04-25 整備完了。3 メンバー並行着手可能な状態:
  - 型 3 点同期済み（`ShareResponse` / `SharedPlanResponse` 系、Phase 1.9 DB-4/5 の契約確定）
  - `supabase/migrations/` 00〜04 が冪等で配置済み（DB-1 は Manato 先行実施、DB 担当は今後の新規 ALTER のみ）
  - `.claude/settings.json` に `git add/commit/merge/push/rebase/reset` 系 deny、型 3 点同期対象ファイル編集時の PreToolUse 警告、セッション終了時の todo/lessons 反映 Stop hook を追加（Claude Code 横断で効く）
  - CLAUDE.md → tasks/todo.md → tasks/handoff-*.md の動線を明示、`docs/team-roles.md` / `handoff-frontend.md` も 2026-04-25 の状況で更新

**次にやるべきタスク:**

> ## 🟡 **2026-04-27 セッション末で実装完了 → user commit + push 待ち**: 422 真因全塞ぎ (`fix/plan-generation-blockers`)
>
> 本番 Run 10 で発見した 2 真因 + Codex review 1+2+3 で発覚した追加 Blocker 2 / Major 4 / Minor 2 を網羅的に修正:
>
> 1. **真因 A**: フロント `parseDirectionsResult` に `CANONICAL_DEPARTURE_TIMES` (`["00:00","06:00","09:00","12:00","15:00","18:00","21:00","23:59"]`) export const + observed merge → `candidate_departures` を 8〜9 件に
> 2. **真因 B**: バック `_build_retry_guidance_md` で過去 unknown place_id の禁止リスト注入 + regex 2 種で robust 抽出 + `previous_issues` 累積化 + dedup（UNKNOWN_PLACE_ID は place_id 単位、他は (kind, message)）+ recency 保証 (`pop + 再挿入`) + `MAX_RETAIN=10` cap
> 3. **早期 throw**: フロント `shouldEarlyThrowOnTransit(stats)` helper + 内側 catch で再 throw（握りつぶし排除）
> 4. **verify_hallucination_rate.py** を canonical 8 点に同期、双方向 drift 警告コメント
>
> **検証結果**:
> - フロント `transit.test.ts` 48/48 + 新設 `transit-guard.test.ts` 4/4 PASS
> - バック `test_llm_prompt.py` 35/35 + `test_llm_generator.py` 22/22 PASS（`_dedup_previous_issues` recency test 含む）
> - API 全体 394/394 PASS（既知 env 依存 2 件は本変更無関係）
> - Web 全体 151/151 + 6 件 pre-existing fail（modeSwitch / smoke、本変更無関係）
> - tsc clean / build PASS
> - Codex review 3 回完了（最終 Blocker 0）
>
> **ブランチ構成**: `fix/plan-generation-blockers` を 1 ブランチで全 fix。Codex 推奨で 2 commit に分割可能（Commit A: フロント canonical + early throw、Commit B: バック retry guidance + 累積化）。
>
> **次のアクション (user)**:
> 1. commit → develop merge → push
> 2. Vercel + Render auto deploy 完了待ち（~3 min）
> 3. **本番 Run 11**: もう一度 `/plan/new` から submit → **`/api/plans/generate` が 200 で返る + `/plan/[id]` のプラン閲覧画面まで遷移** を必須条件として確認
> 4. もし 422 のままなら Render Live tail で attempt 別 issue を確認 → ハッカソン提出までに必要な追加 fix を判断
>
> **詳細**: `tasks/plans/2026-04-27-plan-generation-blockers.md`（全 Codex review 反映済）+ lessons.md「2026-04-27: 全塞ぎモード — Codex 3 回 review で 422 真因 4 つ + 副次 Major 4 つを網羅的に修正」エントリ参照

> ## 🔴 **本番で 200 が出るまで継続調査 (Run 11 で判定)**: もし 422 が続くなら次の最優先タスク
>
> 本番 Run 10 (plan_id `9b209857-...`、04:54-04:55) で 422 を再現、Render Live tail から **4 attempts 全失敗の breakdown** を取得:
>
> - attempt 1 (gpt-4.1): `unknown_place_id` (day1_lunch)
> - attempt 2 (gpt-4.1): `unknown_transit_edge` — `candidate_departures=['13:54']` で required `start_hhmm='16:30'` カバーできず
> - attempt 3 (gpt-4.1): `unknown_place_id` (day1_dinner、attempt 1 と同じ ID)
> - attempt 4 (gpt-4.1-mini): place swap 成功したが `candidate_departures=['13:54']` で `'16:30'` カバーできず
>
> **問題 A (構造、最優先)**: `apps/web/src/lib/transit.ts:300-302` の `parseDirectionsResult` が `candidate_departures` を **常に 1 件しか返さない**。Phase 1.3e `verify_hallucination_rate.py` は 5 点 (`["09:00","12:00","15:00","18:00","21:00"]`) で test していたのに、本番フロント (Phase 1.3b) は submit 時刻 1 点だけ → assembler が「16:30 以降に出発」要件を満たせず reject。
>
> **問題 B (LLM ハルシネーション、次点)**: gpt-4.1 が `ChIJJS7EfYgChGWARNW9YGF4jb0I` を attempt 1 + 3 で繰り返し出力。Phase 1.3e で 0% 達成済みのはずが本番条件で再発。問題 A 解消後に再測。
>
> **次セッション最初のタスク**:
> 1. 問題 A の plan を `tasks/plans/2026-04-28-candidate-departures-multi.md` に書く
> 2. Codex review 1 → 反映
> 3. TDD で実装（branch `fix/candidate-departures-multi`）。設計案 2 つ:
>    - (1) フロントで 5 つの departure_time で並列 fetch（コール 5x、deadline 10s 危険）
>    - (2) 1 回 fetch 後にフロント側で fixed list `["09:00","12:00","15:00","18:00","21:00"]` を `candidate_departures` に加算（精度落ちるが assembler 互換、レイテンシ影響なし）→ **案 2 推奨**
> 4. Codex review 2 → 反映
> 5. ローカル + 本番 Run 11 で verify
> 6. 問題 A 解消後、問題 B が残るか測定
>
> **詳細**:
> - 設計の learning は `tasks/lessons.md` 「2026-04-27: 本番 Run 10 で 422 真因判明 — `candidate_departures` 1 件問題（Phase 1.3b ↔ 1.3e 不整合）+ `unknown_place_id` ハルシネーション再発」エントリ参照
> - 関連実装: `apps/web/src/lib/transit.ts:243-303` (`parseDirectionsResult`), `apps/api/src/llm/assembly.py` (assembler の transit edge selection logic), `apps/api/scripts/verify_hallucination_rate.py` (5 点 candidate を出している test fixture)

> ## ✅ **本セッション (2026-04-27) で完了**: Flask logging.basicConfig(INFO) (`chore/api-logging-config`) → develop merge + push 済
>
> 2026-04-27 セッション末のローカル `pnpm dev` verify で **transit_matrix が 40/40 で取れていても 422 が出ること** が判明。前セッション handoff の仮説「transit fallback fix で 422 も解消する」は **誤り**。
>
> **観測値（箱根 / 1 泊 2 日 / auto / 30,000円）**:
> - `[transit-debug] stats`: `{attempted: 40, succeeded: 40, errors: 0, timedOut: 0}` ← transit は完璧
> - `mode_counts`: `{walk: 20, car: 20}` / `duration: 5〜46 min, avg 18 min` ← 距離分岐も健全
> - `/api/plans/generate → 422 UNPROCESSABLE ENTITY` ← LLM validator が 3 回 retry 後 reject
>
> **次セッションでの調査タスク**（Manato）:
> 1. Flask の log（`pnpm dev` のターミナル出力）を確認して、validator がどの issue で reject しているか特定（`unknown_place_id` / `outside_opening_hours` / `budget_exceeded` / `unknown_transit_edge` etc）
> 2. 必要なら `apps/api/scripts/verify_hallucination_rate.py` をローカル env で動かして再現性ある rate 計測
> 3. Phase 1.3e の hallucination 0% / success 100% は `verify_hallucination_rate.py` で計測されたもの。本番でなぜ regression が出ているのか切り分け（candidate 数 / prompt token 数 / pack 構成 / opening_hours の周末扱い 等）
>
> 詳細は `tasks/lessons.md` 「2026-04-27: ローカル verify で『transit fallback fix は完璧、ただし 422 は別問題』と判明（仮説の修正）」エントリ参照。

> ## 🟡 **2026-04-27 セッションで実装完了 + ローカル verify 完了 → user commit + push 待ち**: Maps Directions travelMode 距離分岐フォールバック
>
> **ブランチ**: `fix/transit-fallback-walking-driving`（develop から派生、未 commit、commit 提案を user に提示済）
>
> **背景**: 2026-04-26 Run 8 で発見された「TRANSIT が観光地ペアで全 ZERO_RESULTS」を fix。`apps/web/src/lib/transit.ts` の `travelMode: "TRANSIT"` 固定を、ペア距離 ≤ 2km は `TRANSIT → WALKING → DRIVING`、> 2km は `TRANSIT → DRIVING → WALKING` の順で fallback chain 化した。
>
> **設計判断（Codex review 1 回目で軌道修正）**:
> - 単純な「TRANSIT → WALKING → DRIVING」順序固定は **遠距離 10km ペアで「徒歩 2 時間」が plan に組み込まれ assembler の opening_hours 違反量産で 422 再誘発リスク** → 距離分岐で 2 段目を切替
> - 閾値 `WALKING_DISTANCE_KM = 2` の根拠 = 徒歩 30 分相当（4 km/h × 0.5h、plan として自然）
> - per-mode timeout 2s 維持（`/3` 案を Codex OK 判定で却下、ZERO_RESULTS は ~100ms で返るので実時間 ~600ms/pair）
>
> **Codex review 2 回目で発覚した test 設計 bug 2 件も反映**:
> - 「WALKING / DRIVING で transitOptions 未付与」test が近距離ペアで書かれて DRIVING が呼ばれていなかった → 近距離 / 遠距離の 2 件に分割
> - WALKING_DISTANCE_KM の値そのものを固定する test なし（3 に変えても通る）→ 上側境界 (2.0015km) で DRIVING / WALKING 0 件 を assert
>
> **検証結果**: web test **147/147 PASS** (既存 130 + 新規 17) / tsc clean / build PASS / API regression 381/381 PASS / Codex review 2 回目 Blocker 0
>
> **ローカル verify 結果 (2026-04-27 セッション末)**: `pnpm dev` + Playwright で `/plan/new` 提出 → `[transit-debug] stats: {attempted: 40, succeeded: 40, errors: 0, timedOut: 0}` / `mode_counts: {walk: 20, car: 20}` / `duration: 5〜46 min, avg 18 min`。**Maps SDK は TRANSIT で全 ZERO_RESULTS（44 回）を返した後、fallback chain で WALKING/DRIVING で全成功**。距離分岐も綺麗に二分。本 fix の責務は完璧に達成
>
> **secret プリフライト**: 0 hit
>
> **commit 提案** (2 commit 構成、user 手動):
> 1. `docs(phase-1.10): Maps Directions travelMode フォールバック設計書` ← `tasks/plans/2026-04-27-transit-fallback.md`
> 2. `fix(phase-1.10): Maps Directions の travelMode を距離分岐フォールバックに` ← `apps/web/src/lib/transit.ts` + `apps/web/src/lib/transit.test.ts`
>
> **次のアクション (user)**:
> 1. 上記 commit 実施 → develop マージ → push
> 2. Vercel auto deploy 完了後、本番 **Run 9** で `/plan/new` から箱根 / wishes 短文 / tag 空 で submit、`/plan/[id]` まで到達するか確認。transit_matrix が ≥ 1 件取れていれば Phase 2.2 budget context の効果も観察可能になる
> 3. ローカル `pnpm dev` E2E は test mock 済みで論理は固まっているので skip 可（時間あれば実施）
>
> **詳細記録**:
> - 設計書 + Codex 2 回 review 反映: `tasks/plans/2026-04-27-transit-fallback.md`
> - 判断履歴 + 学び: `tasks/lessons.md` 「2026-04-27: Maps Directions の travelMode を距離分岐フォールバック chain 化で解消」
> - これで `.claude/rules/external-api-rules.md` 昇格候補（外部経路 SDK のフォールバック chain は単一モード固定せず下流影響まで含めて設計）が 2 回目記録、次セッション or commit 後にルール昇格を判断


- [x] **Manato**: Phase 1.3e すべて完遂（hallucination 0% / success 100%、run 27 ベースライン）
- [x] **Manato（2026-04-26 完了）**: Phase 2.5 Evidence 詳細モーダル（バッジクリック → modal、5 フィールド + Google Maps リンク、Codex 2 回 review 反映、test 130/130 PASS、develop マージ済）
- [x] **Manato（2026-04-26 完了 → user push 待ち）**: Phase 2.2 予算配分の制約化（prompt v2 に絶対制約 Markdown 注入、Codex 2 回 review 反映、API test 27/27 PASS）。`feat/budget-constraint` ブランチに 4 ファイル変更、commit 提案済
- [x] **Manato（2026-04-26 完了 → user push 済）**: API key 漏洩対応（旧 key rotate + working tree redact + .claude/rules/external-api-rules.md に「commit 提案前 secret プリフライト」を 1 回目で即昇格 + CLAUDE.md「Do NOT」と「ワークフロー」に明文化、commit 16bc5d0 で push 済）。**残: user が Vercel env を新 key に更新 + redeploy** で本番 Maps が動くようになる
- [ ] **Manato（真因判明、SQL 適用待ち）**: 「RLS 42501」は実は `plans.session_id` の **FK 違反 (23503)**。本番 E2E で `proxy-status: PostgREST; error=23503` を確認。anon サインインが `public.sessions` に mirror 行を作らないのが根本原因。**`supabase/migrations/20260425_05_auth_user_sessions_mirror.sql` を Supabase SQL Editor で実行**すれば解消（トリガ + backfill、冪等）。詳細は @tasks/lessons.md 「RLS 42501 の真因は FK 違反」エントリ参照
  - **2026-04-26 セッションで Playwright 再現済み**: auto モードで実フォーム送信 → `POST /rest/v1/plans → 409` を確定。SQL 未適用が原因と確定。SQL 適用後に Playwright で auto/anchor/theme 3 モードの動作確認を行う準備が整っている
- [ ] **Manato（連番衝突、別タスク）**: `supabase/migrations/` で `20260425_05_auth_user_sessions_mirror.sql` と `20260425_05_index_optimization.sql` が連番衝突。`all_migrations.sql` の sort 順が辞書順依存で曖昧になる。`index_optimization` を `06` 以降にリネーム or 連番ルール再整理（mirror が前提条件として先に来る方が適切なので mirror を 05 のまま維持、index は 06 に降格が筋）。**user の SQL 適用順序が決まる前に rename しない方が安全**（既に user が 05_index を実行済みの可能性あり、その場合は別の連番運用を再合意してから対応）
- [ ] **旧 (参考、SQL 適用後に閉じる)**: `test_routes_plans.py::test_integration_end_to_end_plan_generation` と `::test_integration_lock_conflict_returns_409` の RLS violation (42501) 解消。
  - 2026-04-25 セッションでコード側の調査は完了。`test_rls.py` のコメントに「実 DB の RLS 設定上は挙動が docs/data-model.md 通りになっていない」と既に明記済み = production drift 確定
  - migrations 側は `FOR ALL USING (session_id = auth.uid())` のみで `WITH CHECK` 暗黙、PostgreSQL default で USING と同じになるはず → production policy は何かしら drift している
  - 再開時の手順:
    1. Supabase SQL Editor で下記 2 クエリを実行して現状を確認:
       ```sql
       SELECT tablename, policyname, cmd, permissive, roles, qual, with_check
       FROM pg_policies
       WHERE tablename IN ('plans','participants','plan_items','sessions','evidence_pack_sessions')
       ORDER BY tablename, policyname;

       SELECT c.relname AS tablename, c.relrowsecurity AS rls_enabled, c.relforcerowsecurity AS rls_forced
       FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
       WHERE n.nspname = 'public'
         AND c.relname IN ('plans','participants','plan_items','sessions','evidence_pack_sessions');
       ```
    2. drift がある場合は `supabase/migrations/20260401_00_init.sql` を本番に再適用（冪等 DROP → CREATE で安全）
    3. `cd apps/api && .venv/bin/pytest -m integration tests/test_routes_plans.py -x -v` で 3/3 PASS 確認（Supabase anon sign-in は 30/hour rate limit、直前に他 integration を多く回した直後は 1 時間クールダウン）
    4. PASS したら todo.md と lessons.md（drift 原因と修正の記録）を更新
- [ ] **Manato**: Phase 1.10 デプロイ準備（Vercel + Render）。次セッション着手時の最初の一手は **CORS 追加 + gunicorn 追加 + render.yaml 作成** を `feat/deploy-prep` で実装。`apps/api/src/app.py` に CORS 設定なし / `requirements.txt` に gunicorn なしが本番ブロッカーとして 2026-04-25 セッションで判明。Vercel/Render アカウント作成と本番ドメイン方針の判断はユーザ側で必要（詳細は 1.10 節）
- [x] **Manato（Codex Minor、2026-04-25 完了）**: item_type vs category 整合性 validator を追加（`feat/deploy-prep` ブランチ）。`IssueKind.ITEM_TYPE_CATEGORY_MISMATCH` 新設、`_check_item_type_category_consistency` 実装、`_MEAL_CATEGORIES` / `_LODGING_CATEGORIES` allowlist + `*_restaurant` 接尾辞対応。テスト 10 件 PASS、unit 全 283 件 PASS
- [ ] **Manato（残課題、優先度低、Phase 2 scope）**: Codex (latent) 営業時間 parser 日跨ぎ対応（"22:00-02:00" のような夜またぎ）。MVP 箱根デモは日中観光のみで影響なし
- [x] **メンバー B**: DB-4/DB-5 共有 API 実装 + テスト完了（2026-04-26）。`share_routes.py` / `plan_cache.py` / `extensions.py` 実装済み、`tests/test_share_routes.py` 11 件 PASS。DB-7 楽天 API 実装済み（`lodging.py`）。DB-8 logging migration 作成済み（SQL Editor 適用が必要）。（@tasks/handoff-db.md）
- [ ] **メンバー C**: 1.4〜1.9 の見た目仕上げ（@tasks/handoff-frontend.md）

詳細は下の各セクション参照。

---

## Phase 0 / プロジェクト基盤

### 0.1 モノレポ初期化
- [x] `pnpm init` でルート package.json
- [x] Turborepo 導入（turbo.json、pnpm-workspace.yaml）
- [x] `apps/web` に Next.js 15 + TypeScript + Tailwind v4 を作成
- [x] `apps/api` に Flask (Python 3.12) プロジェクトを作成
- [x] `packages/shared-types` で TS 型を共有する仕組みを作る
- [x] `pnpm dev` で両方起動することを確認
- [x] 検証: 手動動作確認（必要に応じて Codex レビューを依頼）

### 0.2 Supabase 連携
- [x] Supabase プロジェクト作成、URL と anon key を取得（ユーザ手動）
- [x] `docs/data-model.md` の DDL を Supabase SQL Editor で実行（ユーザ手動、4テーブル作成確認済み）
- [x] フロント側に `@supabase/supabase-js` を導入（`apps/web/src/lib/supabase.ts`）
- [x] バック側に `supabase` (supabase-py) を導入（`apps/api/src/supabase_client.py`）
- [x] 匿名認証が動くことを確認（ライブで sign_in_anonymously → 691 chars の JWT 取得 → admin delete でクリーンアップ、全て OK）
- [x] 検証: `pytest apps/api/tests/test_supabase.py` パス（4件）

### 0.3 外部 API キー取得と疎通
- [x] Google Cloud Console で Places / Routes / Geocoding API を有効化
- [x] OpenAI API キー取得
- [x] Mapbox トークン取得（`.env` に `NEXT_PUBLIC_MAPBOX_TOKEN` セット済、Phase 1.8 で実戦確認）
- [x] 楽天トラベル App ID 取得（2026-04-27 完了）
- [x] バック側に疎通テスト実装（`apps/api/src/external/health.py` に Google Places / Routes / Geocoding / OpenAI の4チェック）
- [x] 検証: 全 API のヘルスチェックテストがパス（`pytest -m integration` で 4/4 PASS、5.66秒）

---

## Phase 1 / MVP （絶対完成させる）

### 1.1 データモデルと型の定義
- [x] テスト: vitest で `isValidBudgetBreakdown` / `isValidParticipantCount` / `getEvidenceBadgeInfo` を検証（`packages/shared-types/src/index.test.ts`、12件 PASS）
- [x] 実装: `packages/shared-types/src/index.ts` に enum / entity / API / UI ヘルパー型を定義（`Plan` / `PlanItem` / `Participant` / `Evidence` / `EvidenceBadgeInfo` 他）
- [x] 実装: Pydantic v2 のスキーマを `apps/api/src/schemas/__init__.py` に同期（手動ミラー、`_StrictBase` で未知フィールド拒否）
- [x] 検証: フロント型とバック型が同じ構造（`apps/api/tests/test_schema_parity.py` でフィールド名セットの一致をアサート、12モデル × 26フィールドで 2件 PASS）

### 1.2 Evidence Pack Builder（コア機能、サーバー側 places のみ）
- [x] テスト: Places API で「箱根湯本駅」を検索 → place_id と関連情報が返る
- [x] 実装: `apps/api/src/evidence/places.py` に検索関数
- [x] 実装: `apps/api/src/evidence/routes.py` に DRIVE モード経路関数（Phase 2 recalc 用、JP transit は Routes/Directions サーバー API 不可のため）
- [x] 実装: `apps/api/src/evidence/builder.py` で places-only の EvidencePack を構築
- [x] 実装: `apps/api/src/evidence/pack.py` に Pydantic モデル（`TransitEdge` は Field 制約強化済み、有向エッジ明文化）
- [x] 検証: 架空のスポット名を渡すと空リストが返る（例外にならない）
- [x] 検証: Places / Routes (DRIVE) の integration テスト PASS
- [ ] transit 取得は Phase 1.3 でフロントに移動（`apps/web/src/lib/transit.ts`）

### 1.3 LLM プラン生成 + フロント transit 取得（コア機能）

Phase 1.3 は大物なので 4 段に分割: 1.3a → 1.3b → 1.3c → 1.3d の順。

#### 1.3a: `/api/evidence/places` エンドポイント + キャッシュ ✅ 完了（develop: `0cab182`）
- [x] Supabase `evidence_pack_sessions` テーブル DDL（data-model.md 正典に追加、ユーザ適用済）
- [x] 認証ミドルウェア `apps/api/src/auth.py`（JWT 検証で `g.owner_session_id` セット）
- [x] キャッシュモジュール `apps/api/src/evidence/cache.py`（opportunistic cleanup + retry 2 回）
- [x] Flask blueprint `POST /api/evidence/places`（入力 validate → build_evidence_pack → store_pack → evidence_pack_id + places 最小サブセットを返却）
- [x] `EvidencePlacesResponse` を 3 点同期（docs / shared-types / Pydantic）
- [x] ライブ integration テスト（匿名サインイン → end-to-end 200 OK、Supabase ラウンドトリップ、cleanup 検証）

#### 1.3b: フロント Maps JS SDK DirectionsService ラッパー ✅ 完了（develop: `dd1b9b9`）
- [x] `@googlemaps/js-api-loader` v2 の `setOptions` + `importLibrary("routes")` で dynamic ロード
- [x] `apps/web/src/lib/transit.ts` — `fetchTransitMatrix(places, departureTime, options)` で `{edges, stats}` 返却
- [x] 有向エッジ（A→B と B→A を両方呼ぶ）、近接 10km フィルタ、各 place 被覆保証、並列 5、per-call 2s timeout、グローバル締切 10s（SDK ロード含む）
- [x] JST 固定 HH:mm フォーマット（`Intl.DateTimeFormat` で TZ 依存解消）
- [x] SSR ガード / API キー未設定エラー / Loader 失敗後の singleton クリアで再試行可能
- [x] `ClientTransitEdge` を 3 点同期（pack.TransitEdge と同一 Field 制約、同一性テスト付き）
- [x] Vitest 25 件 PASS（pure helpers + mocked SDK + parallelism / deadline / fail-soft / JST / 再試行）

#### 1.3c: サーバー側 Transit Validator + `/api/plans/generate` 骨組み ✅ 完了（develop へのマージ待ち）
- [x] `apps/api/src/evidence/validator.py` 新規: `validate_client_transit_matrix(edges, evidence_pack) -> list[TransitEdge]`
  - Pydantic 層で値域・文字長・HH:mm は既にガード済（`ClientTransitEdge`）
  - 追加: `from/to_place_id` が Evidence Pack.places に含まれるか
  - 追加: 自己ループ（from == to）を reject
  - 追加: 距離上限 `MAX_EDGE_DISTANCE_KM=15.0`（フロント 10km フィルタ + 浮動小数点誤差マージン）
  - 追加: `(from, to, mode)` 3-tuple 重複は「完全一致 drop / 矛盾 reject」で隠蔽防止
  - 追加: 件数上限 `min(HARD_CAP=200, N*(N-1))` を正規化後件数で判定
- [x] `apps/api/src/routes/plan_routes.py` 新規: `POST /api/plans/generate` 骨組み
  - 認証必須（`require_session`）
  - 入力 `PlanGenerationPayload = { evidence_pack_id: UUID, transit_matrix }` を Pydantic validate（`max_length=200` 静的 hard cap）
  - `load_pack(evidence_pack_id, owner_session_id)` で取り出し、None（期限切れ/未知/所有者不一致）は 404
  - Transit Validator で検証、失敗は 400。404 ログは owner を sha256 8 文字・pack_id prefix 8 文字のみ（PII 対策）
  - 検証済み transit_matrix を base_pack に merge（`model_copy(update=...)`、フロント改ざんデータは LLM に届かない）
  - 通常レスポンス: `{ plan_id: null }`。`?debug=1` の時のみ `{ plan_id: null, evidence_pack: merged }` 追加
  - `MAX_CONTENT_LENGTH=256KB` で巨大ペイロード DoS を一次防御
- [x] `PlanGenerationPayload` を 3 点同期（計画節から実型へ昇格、docs 先行 → shared-types → Pydantic → parity）
- [x] Unit テスト: validator 18 件 + `/api/plans/generate` 16 件（認証 / 入力 / UUID / hard cap / 期限 / 所有者 / DB 障害 500 / 検証失敗 / 成功パス / debug / 413）
- [x] Integration テスト: `/api/evidence/places` → `/api/plans/generate?debug=1` のラウンドトリップ（live Supabase、14km 以内ペア能動選定）
- [x] 検証: pnpm --filter api test 135 件 PASS（unit）、integration 1 件 PASS（箱根 live Places + Supabase）

#### 1.3d: LLM プロンプト / 生成 / ハルシネーション検出 ✅ 完了（develop: Branch 0/A/B/C/D 全マージ済み）

詳細計画は @tasks/plans/2026-04-24-llm-plan-generation.md（v3、Codex GO 済）。5 ブランチに分割して実装、各ブランチで Codex GO 取得。

**Branch 0** `feat/opening-hours-normalization` ✅
- [x] `OpeningHoursSlot` 追加、PlacePoint.opening_hours を構造化、日本語 weekdayDescriptions パーサ

**Branch A** `feat/llm-prompt-and-validator` ✅
- [x] `apps/api/src/llm/prompt.py` に system prompt（v1.0.0）と user prompt builder
- [x] `apps/api/src/llm/schema.py` LlmGeneratedPlan / LlmPlanItem / LlmTransitRef（OpenAI strict 対応）
- [x] `apps/api/src/llm/validator.py` で LLM 出力検証 13 項目（place_id / 時刻 / opening_hours / transit 整合 / 予算 / 時系列 / tz）

**Branch B** `feat/llm-generator-atomic` ✅
- [x] `apps/api/src/llm/generator.py` OpenAI Structured Output + retry×3 + gpt-4o-mini fallback、deadline 150s clamp
- [x] `supabase/migrations/20260424_04_plan_generation_rpcs.sql`: acquire_plan_generation_lock / mark_plan_failed / finalize_plan（compare-and-set + SELECT FOR UPDATE）
- [x] `apps/api/src/plans/storage.py` 3 RPC ラッパ（httpx 例外を RpcTransportError に wrap）

**Branch C** `feat/plans-generate-route` ✅
- [x] `/api/plans/generate` 最終配線: lock → LLM → finalize_plan RPC
- [x] debug mode `?debug=1` 廃止、最終応答を `{ plan_id: <UUID> }` に
- [x] 失敗分類: 422（ハルシネーション/refuse）/ 502（OpenAI transport）/ 504（deadline / finalize RPC transport）/ 500（bad_request / 想定外例外で stuck 防止の保険）
- [x] `_serialize_plan_item` が pack.places から place_name/lat/lng/address を埋める（1.7 MapView 対応）
- [x] `docs/setup-guide.md` 追記: pg_cron 有効化手順 / RPC 適用手順 / Render HTTP timeout 180s / PROMPT_VERSION

**Branch D** `feat/db-integrity-sweep` ✅
- [x] DB-2: RLS E2E integration テスト（`apps/api/tests/test_rls.py`、他セッション遮断 / service_role バイパス / evidence_pack_sessions 完全遮断）
- [x] DB-3: pg_cron クリーンアップ（`supabase/migrations/20260424_03_cleanup_cron.sql`、evidence_pack_sessions / stuck generating / abandoned draft+failed、succeeded は保全）

**検証**: `pytest -m "not integration"` 234 件 PASS。integration は rate limit リセット後に `pytest -m integration` で再確認推奨。

**実環境検証（2026-04-25 更新）**:
- [x] `pytest -m integration tests/test_rls.py`（8 件）: **2026-04-25 00:49 JST に全 8 件 PASS（10.5 秒）**。rate limit は 1 時間クールダウンで回復した
- [ ] `pytest -m integration tests/test_routes_plans.py`（3 件）: **1/3 PASS（`test_integration_invalid_transit_returns_400` のみ）**。残 2 件（`test_integration_end_to_end_plan_generation` / `test_integration_lock_conflict_returns_409`）は anon client から `plans` への INSERT 時に **RLS violation (code=42501, "new row violates row-level security policy for table plans")** で失敗。rate limit ではなく RLS policy 側の問題
  - **原因仮説**: 本番 Supabase の "Plans of own session" policy が `FOR ALL USING (session_id = auth.uid())` だが WITH CHECK が事実上効かず anon INSERT を deny している。または本番 policy が migrations ファイルと drift している可能性
  - **推奨対応（次セッション）**: (a) `supabase/migrations/20260401_00_init.sql` を本番に再適用して DROP POLICY IF EXISTS → CREATE POLICY で最新に揃える、(b) もしくは test 側を service_role 経由の INSERT に書き換える（フロント 1.5 の実挙動は anon INSERT なので (a) が本筋）、(c) Supabase SQL Editor で `SELECT * FROM pg_policies WHERE tablename='plans';` を実行して現在の policy を確認
  - **今回は「検証と記録のみ」指示のためコード修正なし**。次の Manato 作業で吸収
- [ ] `apps/api/scripts/verify_hallucination_rate.py --runs 10`: 2 run（OpenAI 合計 ~$4-6）いずれも hallucination 1/10 = **10%**。詳細 issue breakdown は @tasks/lessons.md 2026-04-25 エントリ。次イテレーション案 (a)〜(d) に従い prompt token / validator retry / fixture を見直す
  - **閉塞原因の仮説（lessons.md 参照）**: prompt 22k tokens、opening_hours retry の効きが弱い、transit_matrix 拡張による places 情報の埋没
  - **2026-04-25 着手済みの改善（Step 1-2、再検証未実施）**:
    - (Step 1) `verify_hallucination_rate.py::_build_transit_matrix` を「各 place から最近傍 5 edges、hard_cap=100」に変更。14km 全ペア 160 edges → 75 edges（-53%）で実運用密度（フロント SDK 実測 ~40 edges）に近づけた
    - (Step 2) `src/llm/prompt.py::_place_for_llm` から `lat` / `lng` / `relevance_tags` を除外（token 節約）。system prompt ルール 9（opening_hours 遵守）を「最頻出の違反」として強調
    - **効果（計測値）**: prompt token 22,385 → **11,645（-48%）**。evidence-pack.md 目安 10k 内は届かず、12k warning threshold は +350 で僅か超
    - unit テスト 60 件 (LLM 関連) PASS、regression なし
  - **Step 3 実施（2026-04-25 夜、`--runs 5`、OpenAI ~$1）**: 結果 **悪化**。success 0/5、hallucination 1/5 = **20%**。内訳: `unknown_transit_edge=7`（新規大量発生）/ `outside_opening_hours=5`（前回 12 から激減）/ `budget_exceeded=1` / `unknown_place_id=1`
    - opening_hours 違反は system prompt 強調で激減できたが、transit_matrix を 160→75 に攻めすぎて **LLM が pack にない edge を hallucinate する新しい失敗モード** が噴出
    - validator 的には「制約違反の押し出し」現象。片方を締めるともう片方が開く
  - **次イテレーション仮説（未実施、Manato 次セッション）**:
    - (a') transit_matrix を最近傍 5 → 8 に戻す（75 → ~120 edges、prompt ~13k tokens 想定）
    - (b') system prompt に「transit_matrix に該当 edge がなければ経路を使わず別 places を選び直す」と明示
    - (e') **LCaMO 論文（石原・中村 2026）思想の適用、本命候補**: LLM の役割を「pack 内 place_id の順列選定 + slot 指定」に限定し、`start_time` / `transit_ref` / `cost_jpy` はサーバ決定論で埋める設計改修。5 種の validator issue を構造的に 0 化できる想定。詳細と選択肢は @tasks/lessons.md「2026-04-25 深夜: LCaMO 論文からの構造的知見」エントリ参照
    - MVP 合格条件を「hallucination + unknown_transit_edge ≤ 10%」に下げる判断もあり（ハッカソン提出優先、Manato 次セッションで判断）
  - **進め方の選択肢（Manato 次セッションで判断）**:
    - (A) 設計 plan ファイル（`tasks/plans/2026-04-25-lcamo-inspired-plan-generation.md`）を先に書き、実装は次々セッション
    - (B) Phase 1.3e 新ブランチで骨組みだけ実装（schema + slot テンプレ + transit 自動挿入 stub）、動作確認は次
    - (C) ハッカソン提出優先で MVP 合格条件を緩和、LCaMO 応用は Phase 2 以降
  - **再現手順**: `cd apps/api && .venv/bin/python scripts/verify_hallucination_rate.py --runs 10`（env: OPENAI_API_KEY / GOOGLE_MAPS_API_KEY 必須）

### 1.4〜1.9: **フロント骨組み + デザイン引き渡し**（並列 3 トラック運用）

1.3c マージ後、Manato/Claude がフロントの「骨組み」を `feat/frontend-skeleton` で一括実装し、
その後デザイナー（メンバー C）に「見た目」をお任せする運用に切替。
詳細計画は @tasks/plans/2026-04-21-frontend-skeleton.md、
引き継ぎ資料は @tasks/handoff-frontend.md 参照。

#### 1.4〜1.9 骨組み（Claude/Manato 担当、6 ブランチに分割して実装） ✅ 完了

**Branch 0** `feat/plan-generation-plan-id` ✅ (develop: `807fca8`)
- [x] Task 0: `PlanGenerationPayload` に `plan_id` 追加 + `plans.status` カラム追加（3 点同期、DDL 追記）

**Branch 1** `feat/frontend-foundation` ✅ (develop: `369127b`)
- [x] Task 1: 依存パッケージ導入（shadcn/ui、React Query + Devtools、Zustand、react-hook-form、zod、Phosphor Icons、Mapbox、react-qr-code、Framer Motion）+ Providers 配線
- [x] Task 2: API クライアント (`lib/api.ts`) + `generationSessionStore` + zod スキーマ + モック fixtures（`queryFn` 分岐で `initialData` 不使用）
- [x] Task 3: 共通コンポーネント骨組み（EvidenceBadge / PlanTimeline / PlanItem / BudgetSummary / BudgetBreakdownSlider / ParticipantTabs / ParticipantForm）

**Branch 2** `feat/frontend-core-flow` ✅ (develop: `909bec6`)
- [x] Task 4: 1.4 ランディングページ骨組み（CTA + 3 軸カード）
- [x] Task 5: 1.5 希望入力画面骨組み（フォーム配線 + plan_id 発行 + plans INSERT + `/api/evidence/places` + Zustand stash + status 遷移）
- [x] Task 6: 1.6 プラン生成中画面骨組み（Zustand 取得 + transit 取得 + `/api/plans/generate` kick + 成功/失敗時 clearSession で重複 generate 防止）

**Branch 3** `feat/frontend-plan-view` ✅ (develop: `4f649aa`)
- [x] Task 7: 1.7 プラン閲覧画面骨組み（3 カラム: タイムライン / 予算 / マップ、`USE_MOCKS` 分岐は `lib/api.ts` 内）

**Branch 4** `feat/frontend-extra-pages` ✅ (develop: `d46fe2a`)
- [x] Task 8: 1.8 地図ビュー骨組み（Mapbox 初期化 + マーカー + 1.7 への差し込み）
- [x] Task 9: 1.9 プラン共有画面骨組み（QR + 共有 URL、API 未接続で 1.9 本実装待ち）

**Branch 5** `feat/frontend-handoff`
- [x] Task 10: ハンドオフ資料 + todo.md + architecture.md 最終化 + Codex レビュー Must-fix 反映（API URL 環境変数名を `NEXT_PUBLIC_API_BASE_URL` に統一、1.6 成功/失敗時の clearSession 追加、handoff 状態を完成ずみに更新、TabsTrigger ネスト button を外出し、getActiveSession で TTL 切れ時に autoclear、updatePlanStatus failed のログ明示化）
- [x] 検証: `pnpm --filter web test` 61 件 PASS、`pnpm --filter web exec tsc --noEmit` PASS

#### 1.4〜1.9 デザイン着地（メンバー C 担当、骨組みマージ後）
- [ ] 1.4 ランディングページの見た目仕上げ（ヒーロー / CTA / 3 軸カード、AI 感のない表現）
- [ ] 1.5 希望入力画面の見た目仕上げ（参加者タブ、予算スライダー、日本語 15 文字以上で崩れない）
- [ ] 1.6 プラン生成中画面のアニメーション実装（5 ステップのプログレス、Framer Motion）
- [ ] 1.7 プラン閲覧画面の見た目仕上げ（タイムラインを主役に、予算サマリ / マップは脇役）
- [ ] 1.8 地図ビューの見た目仕上げ（マーカークリック → PlanItem スクロール、ミニタイムラインストリップ）
- [ ] 1.9 プラン共有画面の見た目仕上げ（QR + 共有 URL、印刷可能なレイアウト）
- [ ] UI 耐久性チェック: 長文スポット名 / 0 件 / ローディング / エラー / 参加者数 2〜5 で全画面崩れないこと
- [ ] Design Tokens の最終調整（`globals.css` + `.claude/rules/frontend-design.md` 更新）

#### 1.9 共有 API 実装（メンバー B 担当、@tasks/handoff-db.md の DB-4/5/6）
- [x] 型 `ShareResponse` / `SharedPlanResponse` を docs / shared-types / Pydantic / parity に 3 点同期（2026-04-25 Manato、DB 担当の実装は contract 通りに通せば OK）
- [x] `POST /api/plans/:id/share`（share_token 生成、owner 検証、`plans.status='succeeded'` 限定）
- [x] `GET /api/plans/shared/:token`（Flask + service_role、RLS バイパス経路、handoff-db.md 参照）
- [x] 共有用 RLS ポリシー監査（handoff-db.md の DB-6 に要件整理）— 監査完了、追加ポリシー不要（Flask + service_role で十分）

### 1.x: **DB 整理タスク**

詳細は @tasks/handoff-db.md 参照。2026-04-25 時点で **Manato 担当分は完了**、**メンバー B 担当分が残り**。

#### Manato 担当（1.3d と合流して対応） ✅ 完了
- [x] DB-2: RLS の E2E テスト（`apps/api/tests/test_rls.py`、他セッションからのアクセス遮断検証。integration は rate limit 回復後に完走確認）
- [x] DB-3: 定期クリーンアップ（`supabase/migrations/20260424_03_cleanup_cron.sql`）: (a) `evidence_pack_sessions` の期限切れ、(b) `plans WHERE status='generating' AND updated_at < now() - INTERVAL '1 hour'`、(c) `plans WHERE status IN ('draft','failed') AND created_at < now() - INTERVAL '24 hours'`。`succeeded` は保全

#### メンバー B 担当（1.3d と完全独立、並行可）
- [x] DB-1: `supabase/migrations/` 冪等 5 連番ファイル配置（2026-04-25 Manato 先行実施）。DB 担当は今後の DDL 変更時に新規連番ファイルを追加する運用を維持
- [x] **DB インデックス最適化（2026-04-25 メンバー B 実施）**: `supabase/migrations/20260425_05_index_optimization.sql` を新規作成。cron クリーンアップクエリと DB-5 共有閲覧 API の ORDER BY を複合インデックスで高速化:
  - `idx_plans_status_updated_at(status, updated_at)` — stuck-plans cron の Seq Scan 排除
  - `idx_plans_status_created_at(status, created_at)` — abandoned-plans cron の Seq Scan 排除
  - `idx_participants_plan_order(plan_id, order_index)` — DB-5 の Sort ステップを Index Only Scan に昇格
  - **Supabase SQL Editor での適用が必要**（冪等設計、何度実行しても安全）
- [x] **DB 最適化 ⑫⑬（2026-04-25 メンバー B 実施）**:
  - **⑫ コネクションプール**: `apps/api/src/supabase_client.py` をシングルトン化。毎リクエスト `create_client()` → httpx.Client 都度生成だったのを、double-checked locking でプロセス内の接続を再利用する設計に変更。テスト用 `_reset_client()` も追加
  - **⑬ 非同期バッチ化**: `supabase/migrations/20260425_06_shared_plan_rpc.sql` を新規作成。`get_shared_plan(token)` RPC で plan + participants + plan_items を 1 本の SQL に集約し、DB-5 のラウンドトリップを 3 回 → 1 回に削減。`share_token IS NOT NULL` を SQL 内にハードコードして Flask 経由でのみアクセス可能な設計を維持
  - **Supabase SQL Editor で `20260425_06` → `20260425_07` の順で適用後、DB-5 の `share_routes.py` で `client.rpc("get_shared_plan", ...)` を使う**
- [x] **パフォーマンス最適化 Step 1+2（2026-04-20 メンバー B 実施）**（詳細は @tasks/plans/2026-04-25-performance-optimization.md）:
  - [x] インメモリ TTL キャッシュ（`apps/api/src/cache/plan_cache.py`、60s TTL、threading.Lock）
  - [x] Cache-Control ヘッダー（`get_shared_plan` に `public, max-age=60, stale-while-revalidate=300`）
  - [x] Flask-Limiter（`apps/api/src/extensions.py` + share_routes に `@limiter.limit("60 per minute")`）
  - [x] Flask-Compress（gzip、1KB以上に自動適用、`app.py` で Compress(app)）
  - [x] MapView dynamic import（ssr:false、~300KB バンドル削減、`plan/[id]/page.tsx`）
  - [x] React Query staleTime/gcTime/retry/placeholderData 設定（`providers.tsx`）
  - [x] SkeletonTimeline / SkeletonPlanItem コンポーネント（`ui/states/SkeletonPlanItem.tsx`）
  - [x] MapErrorBoundary クラスコンポーネント（`ui/MapErrorFallback.tsx`）
  - [x] gunicorn --keep-alive 5 --worker-connections 100（`render.yaml`）
  - [x] コネクションプールシングルトン（`supabase_client.py` double-checked locking）
  - [ ] Step 3（提出前余裕があれば）: Service Worker（オフライン対応）
- [x] DB-7: 楽天トラベル API App ID 取得 + 連携実装完了（2026-04-26）。`evidence/lodging.py` 新規作成、`builder.py` に組み込み済み。テスト 5 件 PASS。**2026-04-28: 新 API 移行対応** — (1) エンドポイントを `openapi.rakuten.co.jp/engine/...` に変更、(2) `RAKUTEN_ACCESS_KEY` 環境変数を追加（新 API で必須化）、(3) 検索方式を `keyword` → 緯度経度（`latitude`/`longitude`/`searchRadius=3`）に変更（新 API は keyword 単独不可）。`builder.py` で places の重心座標を算出して `_fetch_lodging_safe` に渡す設計。lodging テスト 5/5 PASS。**疎通テスト: 403 Invalid Access Key 発生中 → Access Key の値を Render 環境変数に正しく設定できているか確認が必要**
- [x] DB-8: Supabase Row-Level Logging（2026-04-26 完了）— `supabase/migrations/20260426_08_logging_setup.sql` を新規作成。pg_stat_statements 有効化 + `routeful_query_stats` / `routeful_slow_queries` ビュー + `reset_routeful_query_stats()` 関数。Supabase SQL Editor で適用後、ダッシュボードから観測可能
- [ ] 1.9 共有 API は上の「1.9 共有 API 実装」セクションで DB-4/5/6 として別管理

<details>
<summary>（旧）1.4 ランディングページ (01) — 骨組みタスクへ吸収済み</summary>

- [ ] テスト: ヒーロー、3軸カード、CTA が描画される
- [ ] 実装: `apps/web/src/app/page.tsx`
- [ ] UI 耐久性: 画面の主役が「旅を計画する」CTA になっている
- [ ] UI 耐久性: 長文テキスト（説明文 60文字以上）で崩れない
- [ ] 検証: 手動動作確認（必要に応じて Codex レビューを依頼）
</details>

<details>
<summary>（旧）1.5〜1.7 希望入力画面 / プラン生成中 / プラン閲覧 — 骨組みタスクへ吸収済み</summary>

### 1.5 希望入力画面 (04)
- [ ] テスト: 参加者を 2〜5 人で追加・削除できる
- [ ] テスト: 予算配分スライダーが常に合計 100% を保つ
- [ ] テスト: 全員分の入力が埋まるまで「プランを生成」ボタンが無効
- [ ] 実装: `apps/web/src/app/plan/new/page.tsx`
- [ ] 実装: Zustand で希望入力ステートを管理
- [ ] UI 耐久性: 参加者名が日本語 15文字以上でも崩れない
- [ ] UI 耐久性: タブの人数が 5 人になっても横スクロールなしで収まる

### 1.6 プラン生成中画面 (05)
- [ ] テスト: 5 ステップの状態変化がアニメーションする
- [ ] 実装: `apps/web/src/app/plan/[id]/generating/page.tsx`
- [ ] 実装: バックからの SSE（Server-Sent Events）で進行状況を受信
- [ ] 実装: エラー時の復帰導線（「もう一度試す」ボタン）
- [ ] UI 耐久性: 生成に 60 秒以上かかってもタイムアウトしない（バック側の許容時間を確認）

### 1.7 プラン閲覧画面 (06)
- [ ] テスト: タイムライン、予算サマリ、ミニマップの3カラムが描画
- [ ] テスト: 各 PlanItem に Evidence バッジが表示される
- [ ] テスト: 交通区間が電車便名・運賃・所要時間とともに表示
- [ ] 実装: `apps/web/src/app/plan/[id]/page.tsx`
- [ ] 実装: タブで「タイムライン / マップ / 予算」を切り替え
- [ ] UI 耐久性: 長文スポット名（30文字超）で崩れない
- [ ] UI 耐久性: PlanItem が0件（空状態）でも画面が成立
- [ ] UI 耐久性: ローディング状態・エラー状態を定義

### 1.8 地図ビュー (07)
- [ ] テスト: Mapbox 地図が描画、全スポットのマーカーが配置
- [ ] テスト: スポット間の経路ポリラインが描画
- [ ] 実装: `apps/web/src/components/MapView.tsx`
- [ ] 実装: マーカークリックで該当 PlanItem にスクロール
- [ ] 実装: 下部にミニタイムラインストリップ（横スクロール）
- [ ] UI 耐久性: スポット数 0 でも地図が成立
- [ ] UI 耐久性: Mapbox トークン未設定時に適切なエラーメッセージ

### 1.9 プラン共有 (08)
- [ ] テスト: 共有 URL でプランが読み取り専用表示される
- [ ] テスト: QR コードが生成される
- [ ] 実装: `apps/web/src/app/plan/[id]/share/page.tsx`
- [ ] 実装: `react-qr-code` で QR 表示
- [ ] 実装: PDF 生成はバック側で ReportLab or WeasyPrint
- [ ] 検証: URL 共有 → 別端末で閲覧可能

</details>

### 1.10 デプロイと初回公開

#### デプロイ前に必須のコード修正（`feat/deploy-prep` ブランチで実装、2026-04-25 完了）
- [x] **🔴 CORS 設定追加**: `flask-cors>=5.0,<7.0` を requirements 追加、`apps/api/src/app.py` に `_resolve_cors_origins()` + `CORS(app, ...)` を実装。env `CORS_ALLOWED_ORIGINS`（CSV）読み込み、未設定時は `http://localhost:3000` のみ許可。`Authorization` / `Content-Type` ヘッダ + `GET/POST/OPTIONS` メソッド許可。CORS unit テスト 6 件 PASS（`tests/test_cors.py`）
- [x] **🔴 `gunicorn>=22.0,<24.0` を requirements に追加**: ローカル smoke test で `gunicorn 'src.app:create_app()'` boot 成功 + `/healthz` 200 OK + ACAO ヘッダ付与確認済
- [x] **🟡 `render.yaml` 作成**: `singapore` region / `--workers 1 --timeout 180` / `healthCheckPath: /healthz` / env var 宣言（秘密値は `sync: false` で Dashboard 経由）
- [x] **🟡 `PROMPT_VERSION_DEFAULT = "v2.0.0"` に変更**: 本番デプロイ時に env 設定を忘れても Phase 1.3e で実証された LCaMO 構造化版（hallucination 0% / success 100%）が走るように。test_llm_prompt の default 期待値も v2 に更新、test_llm_generator は v1 schema mock のため `autouse fixture` で `PROMPT_VERSION=v1.0.0` を明示
- [x] **🟡 `docs/setup-guide.md` のデプロイ節を更新**: render.yaml Blueprint 経由のフロー、CORS_ALLOWED_ORIGINS の必須化、env 一覧の刷新
- [x] **検証**: API unit 273 件 PASS / Web 61 件 PASS / Web tsc PASS / gunicorn smoke OK / CORS ヘッダ実出力確認

#### デプロイ実施
- [ ] フロント: Vercel に `apps/web` をデプロイ（env 5 件: `NEXT_PUBLIC_API_BASE_URL` / `NEXT_PUBLIC_GOOGLE_MAPS_BROWSER_KEY` / `NEXT_PUBLIC_SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_ANON_KEY` / `NEXT_PUBLIC_MAPBOX_TOKEN`）
- [ ] バック: Render に `apps/api` をデプロイ（env 4 件必須: `GOOGLE_MAPS_API_KEY` / `OPENAI_API_KEY` / `NEXT_PUBLIC_SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY`、任意で `PROMPT_VERSION`）。HTTP Timeout 180s 必須
- [ ] Google Maps Console: ブラウザキーの HTTP referrer 制限に Vercel 本番ドメインを追加 / サーバキーの IP 制限に Render outbound IP を追加（Render の固定 IP は有料 plan 機能なので無料 plan は IP 制限スキップ可）
- [ ] Supabase: 匿名認証が production で有効か確認。RLS 42501 残課題（test_routes_plans 2 件）はデプロイ後の本番動作に直接影響しないが、anon plans INSERT が必要なので結局解決必要
- [ ] 本番環境の E2E テスト（1つのデモシナリオを最初から最後まで、希望入力 → 生成 → 閲覧 → 共有）
- [ ] パフォーマンス: プラン生成が 60 秒以内（Phase 1.3e で 4.4s/run 達成済、Render cold start を考慮しても余裕あり）
- [ ] 検証: 3人（チーム全員）で実機テスト

---

## Phase 2 / 差別化機能（ハッカソン向けに優先度高）

### 2.1 出発モード切替（お任せ / アンカー / テーマ）

**Backend 実装完了** (2026-04-25 セッション、`feat/mode-selector` ブランチ、commit 提案待ち):
- [x] 型 3 点同期（`AnchorModePayload` / `ThemeModePayload` / `ThemeKey`）。Plan.mode_payload は `dict[str, Any] | None` のままで後方互換、helper 型は form / API 入力時の validate に使用。設計詳細は `tasks/plans/2026-04-25-mode-selector.md`
- [x] `evidence/builder.py`: anchor mode で `fetch_place_details` 並列 fetch、pack 先頭注入、area filter skip（user 明示意思優先）、fail-soft
- [x] `evidence/builder.py`: theme mode で `_THEME_KEYWORDS` による検索 keyword bias（onsen/art/gourmet/nature/history/experience の 6 種、各 3 keyword）
- [x] `llm/prompt.py` v2: `mode_context_md` placeholder 追加、anchor 必須リスト + theme 日本語ラベル（テーマ衝突時は参加者希望優先の旨明記）
- [x] `llm/assembly.py`: `AnchorMissingError` + `_check_anchors_present`（assembly 完了後 post-check、self-healing で anchor swap された case も catch）
- [x] `llm/validator.py` + `generator.py`: `IssueKind.ANCHOR_MISSING` 新設、retry prompt に inject される
- [x] テスト: 全 299 件 PASS（既存 283 + 新規 16: schema_parity 2 / builder 5 / prompt 4 / assembly 5）

**Frontend 実装完了** (2026-04-25 セッション、`feat/mode-selector-ui` ブランチ、Codex レビュー 4 件すべて消化、commit 提案待ち):
- [x] zod schema を discriminatedUnion("start_mode") に refactor（auto/anchor/theme + ThemeKey 6 値）+ 各 mode の payload schema（test 11 件）
- [x] `apps/web/src/components/ThemePicker.tsx`: 6 theme chips、aria-pressed で active 表示、同 chip 再クリックで選択解除（test 4 件）
- [x] `apps/web/src/components/AnchorPicker.tsx`: place_id chips + 入力 + 追加 / 削除（最大 3 件、空白 / duplicate 拒否、3 件で input disabled）（test 7 件）
- [x] `apps/web/src/components/ModeSelector.tsx`: 3 モード radio（label 形式、active で primary border + ring、role="radiogroup" + aria-labelledby、Codex Minor 4）（test 3 件）
- [x] `/plan/new` page.tsx に組み込み: mode 切替時に mode_payload を対応形にリセット、theme 解除で auto に戻す safety、`clearErrors("mode_payload")` で旧 mode のエラー残留防止（Codex Minor 3）
- [x] **theme registry を `packages/shared-types/src/index.ts` に集約**（Codex Major 2）: `THEME_KEYS as const` + `THEME_LABELS_JP`、planForm.ts の z.enum / ThemePicker の options をこれから導出。backend の `apps/api/src/themes.py` と並行管理
- [x] **`/plan/new` の mode 切替統合テスト** `apps/web/src/app/plan/new/modeSwitch.test.tsx` 新規（Codex Major 1）: 5 件（初期 auto / anchor↔auto / theme↔anchor / theme 解除 safety / mode_payload リセット確認）
- [x] テスト: pnpm --filter web test 全 91 件 PASS（既存 61 + 新規 30）、pnpm --filter web build PASS、tsc clean
- [x] AnchorPicker は MVP として手動 place_id 貼付け方式。Maps JS Places Autocomplete UI 統合は polish 課題（ハッカソン提出後）

**Frontend polish 完了** (2026-04-25 〜 2026-04-26 セッション、`feat/anchor-autocomplete` ブランチ、commit 提案待ち):
- [x] AnchorPicker に Maps JS Places Autocomplete 統合。`apps/web/src/lib/places-autocomplete.ts` 新規（loader singleton + `_resetPlacesLoaderForTests`）
- [x] UX: 入力欄に「箱根神社」と打つ → Google ドロップダウン → クリックで chip に**日本語名**で追加。内部的に place_id を保持して form schema 互換維持
- [x] 設計: `value: string[]` props そのまま、内部 `useState<Map<string, string>>` で name lookup、closure 罠は ref pattern で回避
- [x] テスト: AnchorPicker test を Autocomplete mock で書き直し（10 件）、modeSwitch test も新 label に追従（test-id 経由で empty state 判定）
- [x] 検証: web test 全 95 件 PASS、build PASS、tsc clean、API 323 件も regression なし
- [x] 設計書 `tasks/plans/2026-04-25-anchor-autocomplete.md`、research subagent で Maps JS API 現状確認 (Autocomplete legacy で OK、PlaceAutocompleteElement は shadow DOM で blue hour テーマ整合性が悪い)
- [x] **2026-04-26: `PlaceAutocompleteElement` に migrate**（Places API (New) のみで動作、legacy enable 不要）。subagent 主導で実装、`apps/web/src/components/AnchorPicker.tsx` を web component (`<gmp-place-autocomplete>`) 経由に書き換え + Mock を `customElements.define` パターンで再構築。test 96 件 PASS / build / tsc 全クリア。詳細は @tasks/plans/2026-04-25-anchor-autocomplete.md「2026-04-25 補足」+ @tasks/lessons.md「Cloud project enable API と SDK class 一致確認」
- [x] **2026-04-26: ブラウザキーの API allowlist に「Places API (New)」追加**（Phase 1.10 で「Maps JavaScript API のみ」だったため `places.googleapis.com` 直接 fetch が 403）。詳細は lessons.md「Google Cloud SDK 利用は 4 階層を全部確認」
- [x] **ローカル smoke test 完走**（2026-04-26、`/plan/new` で 「箱根神社」入力 → ドロップダウン → chip に日本語名で追加、Phase 2.1 polish 完全動作確認）

**Frontend 残課題（次の polish フェーズ、優先度順）**:
- [ ] UI 耐久性: アンカー 3 つで崩れない、theme 6 個 chips が小画面で折り返し（実機確認、メンバー C のデザイン仕上げ範囲）
- [ ] 結合: ローカル `pnpm dev` または本番 URL で 3 モード触れて、各 mode で plan 生成が走ること（実 OpenAI コール、3 回 ~$1）
- [ ] (Codex 残 Minor) submit 時の `start_mode/mode_payload` 実引数を直接アサートする統合テスト（次セッション以降の堅牢化、必須ではない）

### 2.2 予算配分の制約化

**2026-04-26 実装完了** (`feat/budget-constraint` ブランチ、user 手動 push 待ち):
- [x] テスト: スライダーの配分が LLM プロンプトに数値制約として渡される（test_build_user_prompt_v2_includes_budget_context_md など 11 件）
- [x] テスト: 生成結果が配分内に収まっている（カテゴリごと合計検証）→ **既に Phase 1.3d で `_check_budget` 実装済**、Phase 2.2 では prompt 側で「絶対制約 + +5% 許容」明示
- [x] 実装: Evidence Pack の `budget_constraints` は既存（`breakdown_percent` + `breakdown_jpy`）、prompt 側で再利用
- [x] 実装: `_build_budget_context_md` で「宿泊は予算の 40%（¥12,000 以内）」形式の Markdown 生成、user_template.md に `{budget_context_md}` placeholder を `{mode_context_md}` 直後に追加
- [ ] 検証（任意、smoke test 一括時に判断）: 配分を極端に変える（宿泊 80% など）と出力が追従する。Run A 通常配分 + Run B 宿泊 80% 偏りの 2 run（~$0.15、5〜10 分）

設計詳細: `tasks/plans/2026-04-26-budget-constraint.md`（Codex review 1+2 回目で Blocker 0 / Major 3 / Minor 5 を全反映）

### 2.3 宿泊費 API 連携
- [x] テスト: 楽天トラベル API で「箱根」「2025-10-18〜20」の検索結果が返る（test_lodging.py 5件 PASS）
- [x] 実装: `apps/api/src/evidence/lodging.py`
- [x] 実装: 予算配分の宿泊枠に収まる宿を候補提示
- [ ] 実装: プラン内の宿泊 PlanItem に楽天トラベル URL を付与
- [ ] UI: 宿泊選択モーダル（3〜5件の候補）

### 2.4 手動編集 + 部分再提案
- [ ] テスト: PlanItem を削除すると後続の start_time が再計算される
- [ ] テスト: 「代替案」ボタンで1アイテムだけ差し替えられる（他は変わらない）
- [ ] 実装: `apps/api/src/llm/regenerate.py` で単一アイテム再生成 API
- [ ] 実装: `apps/web` でドラッグ&ドロップ並び替え（dnd-kit 等）
- [ ] 実装: 並び替え時に Routes API で再計算
- [ ] UI 耐久性: 再計算中のローディング表示

### 2.5 Evidence 詳細モーダル
- [ ] テスト: バッジクリックで根拠が展開される
- [ ] 実装: `apps/web/src/components/EvidenceModal.tsx`
- [ ] 表示内容: 実在確認日、営業時間、評価、出典、取得時刻

---

## Phase 3 / 余裕があれば

### 3.1 飲食費の精密化
- [ ] HotPepper Gourmet API 連携（個人開発OK）
- [ ] price_level だけでなく平均予算（朝/昼/夜別）を取得
- [ ] Evidence バッジを「~ 推定」から「✓ HotPepper」に格上げ

### 3.2 入場料の半自動取得
- [ ] Webスクレイピング（許可されたサイトのみ）で主要観光地の入場料をキャッシュ
- [ ] キャッシュ未ヒット時は LLM 推定のまま

### 3.3 当日の旅のしおりビュー
- [ ] モバイル最適化、オフライン対応（Service Worker）
- [ ] 次の予定までのカウントダウン表示

### 3.4 リモート同期（大規模拡張）
- [ ] Supabase Realtime の導入
- [ ] マルチカーソル表示
- [ ] 楽観的ロック

---

## 定常運用ルール（Phase を問わず）

- 各タスク完了時に `tasks/lessons.md` を確認。2回目の失敗は `.claude/rules/` に昇格
- Codex レビューはユーザ依頼時のみ実行（必須ではない）
- UI 実装タスクには必ず UI 耐久性チェック（長文/0件/エラー状態）を含める
- コミット前に `pnpm test` が全パス
