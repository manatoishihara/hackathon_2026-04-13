"use client";

import { useState } from "react";
import { Bed, ForkKnife, MapPin } from "@phosphor-icons/react/dist/ssr";
import type { PlanItem as PlanItemType, ItemType } from "shared-types";

import { EvidenceBadge } from "./EvidenceBadge";
import { EvidenceModal } from "./EvidenceModal";
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
  const [evidenceOpen, setEvidenceOpen] = useState(false);
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
      className="group flex items-start gap-2 rounded-md bg-[color:var(--color-surface)] p-2 transition-[transform,background-color] duration-300 hover:translate-x-1 hover:bg-[#FAF5EA] sm:gap-3 sm:p-3"
    >
      <div className="flex w-10 shrink-0 flex-col sm:w-12">
        <span className="font-heading text-[13px] font-medium tabular-nums text-[color:var(--color-text-primary)] sm:text-[15px]">
          {formatHHmmJst(item.start_time)}
        </span>
        <span className="text-[10px] text-[color:var(--color-text-secondary)] sm:text-[11px]">
          {formatDurationMin(durationMin)}
        </span>
      </div>
      <ItemThumb type={item.item_type} />
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <h3 className="break-words text-[12px] font-medium leading-snug text-[color:var(--color-text-primary)] sm:text-[13px]">
          {item.title}
        </h3>
        {item.description ? (
          <p className="text-[11px] leading-[1.55] text-[color:var(--color-text-secondary)] sm:text-[12px]">
            {item.description}
          </p>
        ) : null}
        <div className="mt-1 flex flex-wrap items-center gap-2">
          {item.cost_jpy !== null ? (
            <span className="font-mono text-[11px] tabular-nums text-[color:var(--color-text-primary)] sm:text-[12px]">
              {formatJpy(item.cost_jpy)}
            </span>
          ) : null}
          <EvidenceBadge
            confidence={item.cost_confidence}
            sources={item.evidence.sources}
            ariaLabelTitle={item.title}
            onClick={() => setEvidenceOpen(true)}
          />
        </div>
      </div>
      <EvidenceModal
        item={item}
        open={evidenceOpen}
        onOpenChange={setEvidenceOpen}
      />
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
      className="relative h-10 w-10 shrink-0 overflow-hidden rounded-sm sm:h-[54px] sm:w-[54px]"
      style={{ backgroundColor: theme.bg }}
    >
      <span
        className="absolute inset-x-0 bottom-0 h-3 sm:h-[22px]"
        style={{ backgroundColor: theme.accent }}
      />
      <Icon
        size={14}
        weight="duotone"
        className="absolute right-1 top-1 text-[color:var(--color-surface)] opacity-85 sm:hidden"
      />
      <Icon
        size={18}
        weight="duotone"
        className="absolute right-1 top-1 hidden text-[color:var(--color-surface)] opacity-85 sm:block"
      />
    </div>
  );
}
