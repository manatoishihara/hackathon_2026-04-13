"""LLM 関連モジュール（Phase 1.3d）。

- schema: OpenAI Structured Output 用の Pydantic モデル（LlmGeneratedPlan / LlmPlanItem / LlmTransitRef）
- prompt: system / user prompt の builder、v2.0.0（LCaMO 構造化版、デフォルト）と
  v1.0.0 (legacy) のテキストを prompts/<version>/ に置く
- validator: LLM 出力のハルシネーション検出（13 項目、Phase 1.3d 計画書参照）
- generator: OpenAI SDK 呼び出しのリトライ + フォールバック（Branch B で追加）
"""
