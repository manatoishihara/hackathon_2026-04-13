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
