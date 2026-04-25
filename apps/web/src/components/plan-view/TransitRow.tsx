import type { PlanItem, TransitToNext } from "shared-types";

import { formatDurationMin } from "@/lib/format";

type Props =
  | { kind: "item"; item: PlanItem & { item_type: "transit" } }
  | { kind: "next"; transit: TransitToNext };

/**
 * 移動の区切り表現。HTML モック準拠の縦線 + italic 明朝。
 * 2 系統:
 * - kind=item: PlanItem 本体が item_type=transit の場合
 * - kind=next: 前のアイテムの transit_to_next（連続移動の補足）
 */
export function TransitRow(props: Props) {
  if (props.kind === "item") {
    const dur =
      (new Date(props.item.end_time).getTime() -
        new Date(props.item.start_time).getTime()) /
      60_000;
    const summary = props.item.transit_to_next?.route ?? props.item.title;
    const fare = props.item.transit_to_next?.fare_jpy;
    return (
      <Row
        text={`${summary} · ${formatDurationMin(Math.max(1, Math.round(dur)))}${fare != null ? ` · ¥${fare.toLocaleString("ja-JP")}` : ""}`}
      />
    );
  }
  const t = props.transit;
  const text = `${t.route} · ${formatDurationMin(t.duration_min)}${t.fare_jpy != null ? ` · ¥${t.fare_jpy.toLocaleString("ja-JP")}` : ""}`;
  return <Row text={text} />;
}

function Row({ text }: { text: string }) {
  return (
    <div className="flex items-center gap-3 pl-6">
      <span
        aria-hidden
        className="inline-block h-4 w-px bg-[color:var(--color-text-tertiary)]/40"
      />
      <span className="font-heading text-[11px] italic text-[color:var(--color-text-secondary)]">
        {text}
      </span>
    </div>
  );
}
