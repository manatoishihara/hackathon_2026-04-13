import type { FetchTransitStats } from "@/lib/transit";

/**
 * 1.6 生成中画面のガード判定。
 *
 * フロント transit が「絶対数または比率で coverage 不足」のとき
 * `/api/plans/generate` を呼ばず早期エラー化する。
 *
 * 背景:
 * - Phase 1.10 後段 Run 8: TRANSIT が ZERO_RESULTS でも続行 → サーバー 422 に流れる穴
 * - Phase 2 polish v3 Run 13c: transit_matrix が疎 (succeeded < 10 or coverage < 30%)
 *   でも続行 → assembler の `_find_alternate_place` が候補枯渇で `unknown_transit_edge` 連発
 *   ＝ Codex review 3 Major: deadline 依存判定では「deadline 未到達 × 低 coverage」を取り逃す
 *
 * 設計 (v3 Codex review 5 Major 反映):
 * - `placeCount <= 1`: transit_matrix=[] のまま続行（places 1 件以下は経路不要）
 * - `attempted === 0 && placeCount > 1`: 距離フィルタで pair 全落ち → 即 throw
 *   (旧設計は `attempted === 0` 無条件許容で「places 多数 + 距離分散で pair 0 件」を素通りさせていた)
 * - `succeeded === 0` (全滅): 即 throw
 * - `succeeded < MIN_SUCCEEDED_FOR_GENERATE` (絶対下限): throw
 *   理由: assembler が 4 日 18 slot に対し 各 slot 間 1 edge + alternate 候補数本で
 *         最低 10-15 edge 必要、succeeded < 10 では確実に枯渇する
 * - `succeeded / attempted < MIN_COVERAGE_RATIO` (比率下限): throw
 *   理由: ratio 単独では「attempted=5, succeeded=2 (40%)」のような少数バッチ通過リスク、
 *         absolute floor と併用して「attempted=10, succeeded=2 (20%)」も catch
 *
 * deadline 依存判定 (`stats.deadlineReached`) は撤廃。deadline 前に低 coverage で
 * 確定したケースを取り逃さないため、常時チェック方式にする (Codex review 3 Major)。
 */
const MIN_SUCCEEDED_FOR_GENERATE = 10;
const MIN_COVERAGE_RATIO = 0.3;

export function shouldEarlyThrowOnTransit(
  stats: FetchTransitStats,
  placeCount: number,
): boolean {
  // places 1 件以下は transit 不要、空のまま続行（既存挙動）
  if (placeCount <= 1) return false;
  // places 複数あるのに attempted=0 = 距離フィルタで pair 全落ち（places 散らばりすぎ）
  // 空 transit_matrix で /api/plans/generate に流すと A6 系で 422 連発するため early throw
  if (stats.attempted === 0) return true;
  if (stats.succeeded === 0) return true;
  if (stats.succeeded < MIN_SUCCEEDED_FOR_GENERATE) return true;
  if (stats.succeeded / stats.attempted < MIN_COVERAGE_RATIO) return true;
  return false;
}
