# 旅行の基本情報
{query_context_json}

# 利用可能なスポット（Evidence Pack）
# 各 place は id / name / category / opening_hours（曜日別）/ price_level / rating を持つ。
# opening_hours が空配列、または opening_hours_unknown_days に該当曜日が含まれる場合は
# 営業時間検証はスキップされる（サーバ側で吸収）。
{evidence_pack_places_json}

# Slot カタログ（サーバが固定、ここから選ぶ）
# slot_id / start_hhmm / end_hhmm / item_type。各 slot は 1 日の特定時間帯に固定。
{slot_catalog_json}

# 経路情報（transit_matrix、有向エッジ）
# 連続 slot の place が transit_matrix で到達可能なペアになるよう選ぶこと。
{transit_matrix_json}

# 予算目安（カテゴリ上限は次の絶対制約節を参照）
{budget_constraints_json}

# 出発モード補足
{mode_context_md}

{budget_context_md}

# 前回の生成で失敗した検証項目（あれば修正せよ。空配列なら初回試行）
{previous_issues_json}

{retry_guidance_md}

上記情報のみを使って slot 割当 JSON を生成せよ。
