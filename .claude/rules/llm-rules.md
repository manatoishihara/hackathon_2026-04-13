---
paths:
  - "apps/api/src/llm/**/*.py"
  - "apps/api/src/services/plan_generator.py"
  - "apps/api/src/services/evidence_builder.py"
---

# LLM Rules

本プロジェクトにおける最重要ルール。**LLM に勝手に推論させたら負け**。
Evidence Pack が全て。詳細仕様は `@docs/evidence-pack.md` を参照。

## 鉄則

1. **Evidence Pack なしに LLM を呼ぶな**。prompt に必ず構造化データを含める
2. **架空の場所・架空の時刻を出力させるな**。LLM の出力は Evidence Pack 内の `place_id` のみ参照可
3. **LLM 出力は必ず JSON Schema で検証**せよ。自由テキストで返させない
4. **検証失敗時は最大 2 回リトライ**。3 回目は諦めてエラーを返す

## プロンプト構成

```python
SYSTEM_PROMPT = """
あなたは旅行プランナーです。以下の制約の下でプランを JSON で出力してください。

## 絶対ルール
- evidence_pack.places に含まれる place_id のみ使用せよ
- 時刻は ISO 8601 形式、start_time < end_time を守れ
- 予算配分（budget_breakdown）を守れ
- 架空の場所・情報を生成するな

## 出力スキーマ
<JSON Schema を埋め込む>
"""

USER_PROMPT_TEMPLATE = """
## 旅行の基本情報
{basic_info}

## 参加者の希望
{participants_wishes}

## 利用可能なスポット（Evidence Pack）
{evidence_pack_json}

## 予算配分制約
{budget_breakdown}
"""
```

## 出力検証（ハルシネーション検出）

```python
def validate_plan_output(plan: GeneratedPlan, evidence: EvidencePack) -> None:
    valid_place_ids = {p.place_id for p in evidence.places}
    for item in plan.items:
        if item.location.place_id not in valid_place_ids:
            raise HallucinationError(
                f"LLM referenced unknown place_id: {item.location.place_id}"
            )
        # 時刻の妥当性
        if item.start_time >= item.end_time:
            raise InvalidTimeRangeError(item.id)
        # 営業時間内か
        if not is_within_opening_hours(item, evidence):
            raise OutsideOpeningHoursError(item.id)
```

## モデル選定

- **デフォルト**: `gpt-4o`（精度重視）
- **フォールバック**: `gpt-4o-mini`（gpt-4o が 3 回失敗した場合のみ）
- **Structured Output 機能を使え**。`response_format={"type": "json_schema", ...}` でスキーマを強制

## プロンプトのバージョニング

- `apps/api/src/llm/prompts/` に yaml または txt ファイルで配置
- 各プロンプトに semantic version を付ける（v1.0.0、v1.1.0...）
- A/B テスト時は env var でバージョン切替可能に

## コスト管理

- プロンプトトークン数を `tiktoken` でカウント、12,000 トークン超えたら警告ログ
- 1 プラン生成あたりの想定コスト: gpt-4o で $0.10-0.30
- Evidence Pack の内容は必要最小限に絞る（全スポットの全フィールドを送らない）

## テスト

- **ゴールデンケース**: 代表的な入力 5 パターンを fixture で保持、生成結果の構造検証を毎回走らせる
- **ハルシネーション検出テスト**: 架空の地名で呼び出し、検証機能が正しく reject すること
- **リトライテスト**: 最初のレスポンスが不正な場合にリトライが動くこと

## Do NOT

- LLM に「Google で検索してください」とか指示するな（ツール使用は別設計）
- LLM に時刻を計算させるな（Routes API の値を使え）
- LLM に金額を計算させるな（構造化データの値を使え）
- LLM の出力を Markdown として表示するな（JSON → コンポーネント描画）
