import type { FetchTransitStats } from "@/lib/transit";

/**
 * 1.6 生成中画面のガード判定。
 *
 * フロント transit が「試行はしたが全 pair 失敗」(`attempted > 0 && succeeded === 0`)
 * の場合は `/api/plans/generate` を呼ばず早期エラー化する。
 *
 * 背景: Phase 1.10 後段 Run 8 で TRANSIT が ZERO_RESULTS を返しても続行 → サーバー 422 に
 * 流れる穴があった。空 transit_matrix を渡しても LLM がプランを組めず無駄な
 * OpenAI コール + ユーザを待たせる。早期 throw でエラー画面に直行し、
 * 「もう一度入力からやり直す」導線へ流す。
 *
 * `attempted === 0` (places 1 件以下で transit 不要) は許容して transit_matrix=[] のまま続行。
 */
export function shouldEarlyThrowOnTransit(stats: FetchTransitStats): boolean {
  return stats.attempted > 0 && stats.succeeded === 0;
}
