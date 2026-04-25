/**
 * プランアイテムのスケルトンローディング。
 * 弱 WiFi でデータ待ちの間もレイアウトを維持し体感速度を改善する。
 * デザイナーは className を調整してよい。
 */
export function SkeletonPlanItem() {
  return (
    <div className="flex gap-3 py-4 animate-pulse">
      <div className="w-10 h-10 rounded-full bg-[color:var(--color-border)] shrink-0" />
      <div className="flex-1 space-y-2 py-1">
        <div className="h-3 bg-[color:var(--color-border)] rounded w-3/4" />
        <div className="h-3 bg-[color:var(--color-border)] rounded w-1/2 opacity-60" />
        <div className="h-3 bg-[color:var(--color-border)] rounded w-2/3 opacity-40" />
      </div>
    </div>
  );
}

export function SkeletonTimeline() {
  return (
    <div className="space-y-1 px-1">
      {Array.from({ length: 5 }, (_, i) => (
        <SkeletonPlanItem key={i} />
      ))}
    </div>
  );
}
