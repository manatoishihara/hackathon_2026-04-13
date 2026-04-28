"use client";

import {
  BedIcon as Bed,
  ForkKnifeIcon as ForkKnife,
  MapPinIcon as MapPin,
} from "@phosphor-icons/react/dist/ssr";
import type { ItemType, PlanItem } from "shared-types";

import { formatHHmmJst } from "@/lib/format";

type Props = {
  items: PlanItem[];
};

type StripVisual = {
  Icon: typeof MapPin;
  bg: string;
  ariaLabel: string;
};

// MapView.tsx の MARKER_VISUALS と同配色（種別の認知を画面間で統一）。
const STRIP_VISUALS: Record<ItemType, StripVisual> = {
  activity: { Icon: MapPin, bg: "#8FA3C0", ariaLabel: "観光" },
  meal: { Icon: ForkKnife, bg: "#C4A988", ariaLabel: "食事" },
  lodging: { Icon: Bed, bg: "#7A8B5C", ariaLabel: "宿泊" },
  transit: { Icon: MapPin, bg: "#A0B2B8", ariaLabel: "移動" },
};

/**
 * 地図カード下部に貼る、その日の予定を時刻順に並べた横長ストリップ。
 *
 * 役割:
 * - 地図のマーカーだけだと「何時頃か」「いま何件目か」が読み取れない
 * - 大きな PlanTimeline を縦スクロールしなくても、地図カード周辺で時刻軸の
 *   早見ができる → 対面で「次どこ？」「ここ」が即答できる
 *
 * 仕様:
 * - items を `order_index` 順（既に PlanTimeline と同じソート前提）で左→右に並べ、
 *   横スクロール（`overflow-x-auto` + `min-w-max`）
 * - 各 chip は時刻 (HH:mm) + 種別アイコン + スポット名を表示
 * - クリックで `data-plan-item-id` を頼りに PlanItem 行へ scrollIntoView
 *   （Stage 3 のマーカークリックと同じ動線）
 * - 番号バッジは地図側マーカー（位置情報のみで連番）と整合しないため出さない
 */
export function MapMiniStrip({ items }: Props) {
  if (items.length === 0) return null;

  return (
    <div
      data-testid="map-mini-strip"
      className="overflow-x-auto rounded-md border border-[color:var(--color-border)] bg-[color:var(--color-surface)] px-2 py-2"
    >
      <ol className="flex min-w-max items-stretch gap-1.5">
        {items.map((item) => {
          const visual = STRIP_VISUALS[item.item_type];
          const Icon = visual.Icon;
          const placeName = item.location?.place_name ?? item.title;
          return (
            <li key={item.id}>
              <button
                type="button"
                className="flex flex-col items-start gap-0.5 rounded-sm px-2 py-1 text-left transition-colors hover:bg-[color:var(--color-background)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--color-primary)]"
                onClick={() => {
                  const target = document.querySelector(
                    `[data-plan-item-id="${item.id}"]`,
                  );
                  target?.scrollIntoView({
                    behavior: "smooth",
                    block: "center",
                  });
                }}
                aria-label={`${visual.ariaLabel}: ${placeName} へ移動`}
              >
                <span className="flex items-center gap-1.5">
                  <span
                    className="flex h-4 w-4 items-center justify-center rounded-full"
                    style={{ backgroundColor: visual.bg }}
                    aria-hidden="true"
                  >
                    <Icon size={10} weight="fill" className="text-white" />
                  </span>
                  <span className="font-mono text-[11px] tabular-nums text-[color:var(--color-text-primary)]">
                    {formatHHmmJst(item.start_time)}
                  </span>
                </span>
                <span className="block max-w-[8rem] truncate text-[11px] text-[color:var(--color-text-secondary)]">
                  {placeName}
                </span>
              </button>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
