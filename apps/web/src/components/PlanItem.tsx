import {
  Bed,
  Bus,
  ForkKnife,
  MapPin,
  Train,
} from "@phosphor-icons/react/dist/ssr";
import type { PlanItem as PlanItemType, ItemType, TransitMode } from "shared-types";

import { EvidenceBadge } from "./EvidenceBadge";
import { formatHHmmJst, formatJpy, formatDurationMin } from "@/lib/format";

type Props = {
  item: PlanItemType;
};

/**
 * プランの 1 アイテム（activity / meal / transit / lodging）。
 * デザイナーは className / 余白 / Motion を触ってよい。Props と `formatXxx` は固定。
 */
export function PlanItem({ item }: Props) {
  const Icon = resolveIcon(item.item_type, item.transit_to_next?.mode ?? null);
  const durationMin = Math.max(
    1,
    Math.round(
      (new Date(item.end_time).getTime() - new Date(item.start_time).getTime()) / 60_000,
    ),
  );
  return (
    <article className="flex gap-4 rounded-lg border border-[color:var(--color-border)] bg-[color:var(--color-surface)] p-4">
      <div className="shrink-0 text-[color:var(--color-text-tertiary)]">
        <Icon size={24} weight="duotone" />
      </div>
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <div className="flex items-baseline gap-2 text-xs text-[color:var(--color-text-secondary)]">
          <span className="font-mono tabular-nums">
            {formatHHmmJst(item.start_time)} – {formatHHmmJst(item.end_time)}
          </span>
          <span>· {formatDurationMin(durationMin)}</span>
        </div>
        <h3 className="break-words font-medium text-[color:var(--color-text-primary)]">
          {item.title}
        </h3>
        {item.description ? (
          <p className="text-sm text-[color:var(--color-text-secondary)]">
            {item.description}
          </p>
        ) : null}
        <div className="mt-1 flex flex-wrap items-center gap-2">
          {item.cost_jpy !== null ? (
            <span className="text-sm font-medium text-[color:var(--color-text-primary)]">
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

function resolveIcon(type: ItemType, transitMode: TransitMode | null) {
  if (type === "transit") {
    if (transitMode === "bus") return Bus;
    return Train;
  }
  if (type === "meal") return ForkKnife;
  if (type === "lodging") return Bed;
  return MapPin;
}
