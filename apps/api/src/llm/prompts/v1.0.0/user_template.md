# 旅行の基本情報
{query_context_json}

# 利用可能なスポット（Evidence Pack）
{evidence_pack_places_json}

# 経路情報（スポット間の移動、有向エッジ）
{transit_matrix_json}

# 予算制約（カテゴリ別上限、1 人あたり円）
{budget_constraints_json}

# 時間制約（期間、チェックイン/アウト）
{temporal_constraints_json}

# 前回の生成で失敗した検証項目（あれば修正せよ。空配列なら初回試行）
{previous_issues_json}

上記情報のみを使ってプランを JSON で生成せよ。
