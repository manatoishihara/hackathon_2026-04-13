"""Evidence Pack Builder。

docs/evidence-pack.md の「Pack 構築フロー」を実装する。Phase 1.2 の範囲:

- Places API で候補スポットを検索（並列）
- 予算・時間の制約を展開
- transit_matrix は **空で返す**（フロントが Maps JS SDK DirectionsService で
  埋める設計、Phase 1.3）

transit を server で取らない理由: Google Directions / Routes API は日本国内の
公共交通情報を返さないため（`tasks/lessons.md` の記録を参照）。

relevance_tags のスコアリングと candidate_departures の複数化は Phase 1.3。
"""
