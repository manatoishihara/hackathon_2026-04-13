# 次セッション再開プロンプト（2026-04-26 終了時点 → 次セッション）

このファイルの中身をそのまま新しい会話の冒頭に貼り付けて使ってください。

---

## 再開プロンプト本文（コピペ用）

```
Routeful プロジェクト（hackathon 2026-04-13）の作業継続。前セッション（2026-04-26）から
最優先 blocker を引き継ぐ。

## 🔴 最優先タスク: プラン生成が動かない（demo の core が壊れている）

本番 / ローカル両方で `/plan/new` から submit するとプラン生成中画面で 422 エラー
「plan generation failed after retries」になり、プラン閲覧画面に到達しない。これは
hackathon 提出のブロッカー。

### 真因（前セッションで切り分け済）

`apps/web/src/lib/transit.ts:333` の `service.route({travelMode: "TRANSIT"})` 固定が
原因。Maps Directions の TRANSIT モードは「駅・停留所間の公共交通機関」を返す SDK で、
観光地（彫刻の森美術館 / 箱根神社 / 強羅公園 等）のような徒歩アクセス前提の地点間では
**40 ペア全部 ZERO_RESULTS** を返し、結果として transit_matrix=[] のままサーバへ POST
され、LLM が plan を組めず validator 3 回 retry 後 422 になる。

ローカル Run 8 verify 結果（2026-04-26）:
- places 12 件（観光地 7 + 飲食 5、距離 0.64〜9.57 km）→ Phase 1.10 多様性 fix は完璧
- fetchTransitMatrix stats: `{attempted: 40, succeeded: 0, errors: 40, deadlineReached: false}`
- console error は `/api/plans/generate → 422` のみ、Maps SDK 自体は動作

詳細は @tasks/todo.md の Phase 1.10 本番 E2E 動作確認 Run 1〜8 節 +
@tasks/lessons.md の「Maps Directions TRANSIT モードは観光地間で ZERO_RESULTS を返す」
エントリ。

### 次セッションのタスク（branch: `fix/transit-fallback-walking-driving`）

`apps/web/src/lib/transit.ts:333` の travelMode 固定を **TRANSIT → WALKING → DRIVING の
フォールバック chain** に変更:

1. `callDirectionsWithTimeout` を「mode を引数に取る」設計に変更
2. `fetchTransitMatrix` の per-pair 処理で「TRANSIT 試行 → 失敗なら WALKING → 失敗なら
   DRIVING」を順次実行
3. 各 mode で per-call 2s timeout 維持、全体 deadline 10s 維持（mode あたり 2s × 3 = 6s
   までは収まる、ペア並列で実時間は短縮）
4. `mapVehicleToMode` を拡張: WALKING → mode='walk'、DRIVING → mode='car'
5. `parseDirectionsResult` は既に `step.travel_mode` で判別済なので最小修正
6. test 追加（`apps/web/src/lib/transit.test.ts`）:
   - TRANSIT で ZERO_RESULTS なら WALKING を試す
   - WALKING も ZERO_RESULTS なら DRIVING を試す
   - すべて失敗なら kind: error、edges に追加されない
   - per-call timeout は mode あたり 2s

規模: 実装 ~50 LOC、test ~30 LOC、1〜2 時間。

### 進め方（前セッションと同じパターンで）

1. 設計 plan を `tasks/plans/2026-04-26-transit-fallback.md` に書く
2. Codex review 1 回目
3. 反映
4. TDD で実装（branch `fix/transit-fallback-walking-driving`）
5. Codex review 2 回目
6. 反映
7. ローカル `pnpm dev` で verify（前セッションで使った debug log の手法、generating
   page で `console.log("[transit-debug]", result.stats)` を一時的に仕込んで stats を見る）
8. secret プリフライト + commit 提案 → user push
9. 本番 deploy → Run 9 で本番 E2E 確認

### 制約 / 守ってほしいこと

- CLAUDE.md / .claude/rules/ を必ず読んでから着手
- develop に直接コミットしない、必ず `fix/transit-fallback-walking-driving` ブランチ
- git commit / push は user が手動でやる、Claude は提案だけ
- commit 提案前に必ず secret プリフライト（CLAUDE.md ルール）
- subagent は適材適所で活用 OK（Explore で transit.ts 周辺の現状調査、codex で plan / 実装 review）

### 副次的な未解決タスク（hackathon 提出に致命的ではない）

- `tasks/lessons.md` で 1 回目記録した教訓のうち、`.claude/rules/` 昇格候補が複数あり:
  - 「外部経路 SDK は単一モード固定にせずフォールバック設計」(今回 1 回目、修正で実証)
  - 「migration 適用漏れ checklist」
  - 「LLM prompt 拡張は helper pattern + 挿入順 test」
- Phase 1.7 / 1.8 / 1.9 の見た目仕上げ（メンバー C スコープ）
- Phase 2.4 手動編集 + 部分再提案（時間あれば）

### 関連参照

- @CLAUDE.md
- @tasks/todo.md（Phase 1.10 本番 E2E Run 1〜8、最優先タスク節）
- @tasks/lessons.md（直近の Maps TRANSIT 限界 / 本番 E2E 7 連続 Run / Evidence Pack 多様性 等）
- @tasks/plans/2026-04-26-evidence-pack-diversity.md（前セッションの Phase 1.10 fix 設計）
- @apps/web/src/lib/transit.ts（line 333 の travelMode 固定が修正対象）
- @apps/web/src/lib/transit.test.ts（既存 25 件 test）
- @apps/web/src/app/plan/[id]/generating/page.tsx（fetchTransitMatrix 呼び出し元）

まずは todo.md の最優先タスク節を読んで現状把握 → plan 起案 → 推奨で進めて。
```

---

## 補足（このファイル自体は次セッションの context に入らないので参考）

### 前セッション (2026-04-26) で完了したもの

| 項目 | 状態 | branch / commit |
|---|---|---|
| Phase 2.5 Evidence 詳細モーダル | ✅ develop merge 済 | 98e37fe + 872140d |
| API key 漏洩対応 + secret preflight rule 昇格 | ✅ develop merge 済 | 16bc5d0 |
| Phase 2.2 予算配分 (prompt v2 絶対制約 Markdown) | ✅ develop merge 済 | 2c000e2 + aa007b9 |
| Phase 1.10 plan_status 設計バグ fix | ✅ develop merge 済 | b97567b + bd835f2 |
| Phase 1.10 Evidence Pack 多様性 fix | ✅ develop merge 済（ユーザがマージ） | feat/evidence-pack-diversity |

### 前セッションで判明した問題（解決順）

| Run | 状況 | 解消 |
|---|---|---|
| 1 | FK 23503 (auth.users → public.sessions mirror なし) | migration 05 適用 |
| 2-3 | Maps Directions REQUEST_DENIED (key allowlist 漏れ) | Vercel key 再設定 |
| 4-5 | 同 + `failed to acquire plan lock` | migration 04 適用 |
| 6 | `plan is already being generated`（フロント PATCH 先打ち） | フロント fix |
| 7 | places 10 件全部湯本駅前飲食店 100m 圏 → TRANSIT ZERO_RESULTS | Phase 1.10 多様性 fix |
| 8 (ローカル) | places 12 件多様化 OK、しかし TRANSIT が観光地ペアで全 ZERO_RESULTS | **次セッションで TRANSIT fallback** |

### 次セッション開始時の git 状態（想定）

- branch: develop（直前に user が `fix/transit-fallback-walking-driving` を切る）
- working tree: clean（前セッション最後で全 commit + push 済）
- background process: なし（dev server は前セッション末で kill 済）

### 環境変数（再開時に確認すべき）

- `apps/api/.env`: `GOOGLE_MAPS_API_KEY` / `OPENAI_API_KEY` / `NEXT_PUBLIC_SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY`
- `apps/web/.env.local`: `NEXT_PUBLIC_GOOGLE_MAPS_BROWSER_KEY` / `NEXT_PUBLIC_API_BASE_URL=http://localhost:5000` / `NEXT_PUBLIC_SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_ANON_KEY` / `NEXT_PUBLIC_MAPBOX_TOKEN`
- ブラウザキー (`NEXT_PUBLIC_GOOGLE_MAPS_BROWSER_KEY`) の Cloud Console allowlist:
  - Maps JavaScript API ✅
  - Places API (New) ✅
  - Directions API ✅（前セッションで user が追加済、TRANSIT / WALKING / DRIVING 全て同じ Directions API allowlist で動く）
- HTTP referrer: `https://hackathon-2026-04-13.vercel.app/*` + `http://localhost:3000/*`

### 次セッションで「やらない」こと（hackathon 提出優先で）

- Phase 2.3 楽天宿泊 API の本格運用（既に builder.py に組み込み済、demo で動けば良い）
- Phase 2.4 手動編集（規模大、提出後）
- Phase 1.7/1.8/1.9 デザイン仕上げ（メンバー C スコープ、Claude が触らない）
- Codex 残課題の (latent) 営業時間 parser 日跨ぎ対応（MVP 箱根 demo は日中観光のみ）
