import { Bed, ForkKnife, MapPin } from "@phosphor-icons/react/dist/ssr";
import type { PlanItem as PlanItemType, ItemType } from "shared-types";

import { EvidenceBadge } from "./EvidenceBadge";
import { formatDurationMin, formatHHmmJst, formatJpy } from "@/lib/format";

type Props = {
  item: PlanItemType;
};

/**
 * プランの 1 アイテム（activity / meal / lodging）。HTML モック準拠で:
 * - 左: 時刻（明朝）+ 滞在時間（小さく）
 * - 中: カテゴリ別 thumb（54x54 の塗り + 装飾）
 * - 右: タイトル + 説明 + Evidence + コスト
 * - hover で translateX 軽め + 背景色変化
 */
export function PlanItem({ item }: Props) {
  const durationMin = Math.max(
    1,
    Math.round(
      (new Date(item.end_time).getTime() -
        new Date(item.start_time).getTime()) /
        60_000,
    ),
  );

  return (
    <article
      data-plan-item-id={item.id}
      className="group flex items-start gap-3 rounded-md bg-[color:var(--color-surface)] p-3 transition-[transform,background-color] duration-300 hover:translate-x-1 hover:bg-[#FAF5EA]"
    >
      <div className="flex w-12 shrink-0 flex-col">
        <span className="font-heading text-[15px] font-medium tabular-nums text-[color:var(--color-text-primary)]">
          {formatHHmmJst(item.start_time)}
        </span>
        <span className="text-[11px] text-[color:var(--color-text-secondary)]">
          {formatDurationMin(durationMin)}
        </span>
      </div>
      <ItemThumb type={item.item_type} />
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <h3 className="break-words text-[13px] font-medium leading-snug text-[color:var(--color-text-primary)]">
          {item.title}
        </h3>
        {item.description ? (
          <p className="text-[12px] leading-[1.55] text-[color:var(--color-text-secondary)]">
            {item.description}
          </p>
        ) : null}
        <div className="mt-1 flex flex-wrap items-center gap-2">
          {item.cost_jpy !== null ? (
            <span className="font-mono text-[12px] tabular-nums text-[color:var(--color-text-primary)]">
              {formatJpy(item.cost_jpy)}
            </span>
          ) : null}
          <EvidenceBadge
            confidence={item.cost_confidence}
            sources={item.evidence.sources}
          />
        </div>
      </div>
    </article>
  );
}

const THUMB_THEMES: Record<
  ItemType,
  { bg: string; accent: string; icon: typeof MapPin }
> = {
  activity: { bg: "#8FA3C0", accent: "#6C7F9A", icon: MapPin },
  meal: { bg: "#C4A988", accent: "#8A7356", icon: ForkKnife },
  lodging: { bg: "#7A8B5C", accent: "#5A6A44", icon: Bed },
  transit: { bg: "#A0B2B8", accent: "#7A8E94", icon: MapPin },
};

/** カテゴリ別の塗りプレースホルダ。HTML モック準拠（54x54、下部に accent 帯）。 */
function ItemThumb({ type }: { type: ItemType }) {
  const theme = THUMB_THEMES[type];
  const Icon = theme.icon;
  return (
    <div
      aria-hidden
      className="relative h-[54px] w-[54px] shrink-0 overflow-hidden rounded-sm"
      style={{ backgroundColor: theme.bg }}
    >
      <span
        className="absolute inset-x-0 bottom-0 h-[22px]"
        style={{ backgroundColor: theme.accent }}
      />
      <Icon
        size={18}
        weight="duotone"
        className="absolute right-1 top-1 text-[color:var(--color-surface)] opacity-85"
      />
    </div>
  );
}
