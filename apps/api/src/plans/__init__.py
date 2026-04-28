"""plans ドメインモジュール（Phase 1.3d）。

- storage: Supabase RPC の薄いラッパ（acquire_plan_generation_lock / finalize_plan / mark_plan_failed）

実テーブル操作は RPC に閉じ込めて、Flask 側は状態遷移の race を気にせず呼び出せる設計。
詳細は `supabase/migrations/20260424_04_plan_generation_rpcs.sql` と
`tasks/plans/2026-04-24-llm-plan-generation.md` の「競合安全性」節を参照。
"""
