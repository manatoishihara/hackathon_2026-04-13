"use client";

import type { TransportMode } from "shared-types";

const TRANSPORT_OPTIONS: ReadonlyArray<{
  key: TransportMode;
  title: string;
  description: string;
}> = [
  {
    key: "all_modes",
    title: "車も使う",
    description: "電車・徒歩・車など、距離に応じて最適な手段を組み合わせます。",
  },
  {
    key: "public_transit_only",
    title: "公共交通機関のみ",
    description: "全員が車を運転しない場合。電車・バス・徒歩のみで行ける場所を選びます。",
  },
];

type Props = {
  value: TransportMode;
  onChange: (next: TransportMode) => void;
  /** SR 用の group label を外部の見出し（h2 等）と関連付ける場合に渡す。 */
  ariaLabelledBy?: string;
};

/**
 * Phase 2 polish (2026-04-27) 移動手段指定。2 モードの radio 群。
 * ModeSelector のスタイルを踏襲し、出発モード radio の直後に置く想定。
 */
export function TransportModeSelector({ value, onChange, ariaLabelledBy }: Props) {
  return (
    <div
      role="radiogroup"
      aria-labelledby={ariaLabelledBy}
      className="flex flex-col gap-2 sm:flex-row sm:flex-wrap"
    >
      {TRANSPORT_OPTIONS.map(({ key, title, description }) => {
        const active = value === key;
        const id = `transport-${key}`;
        return (
          <label
            key={key}
            htmlFor={id}
            className={`flex flex-1 cursor-pointer flex-col gap-1 rounded-lg border p-4 text-left transition-colors ${
              active
                ? "border-[color:var(--color-primary)] bg-[color:var(--color-primary)]/8 ring-1 ring-[color:var(--color-primary)]"
                : "border-[color:var(--color-border)] bg-[color:var(--color-surface)] hover:border-[color:var(--color-primary)]/40"
            }`}
          >
            <input
              id={id}
              type="radio"
              name="transport_mode"
              value={key}
              checked={active}
              onChange={() => onChange(key)}
              className="sr-only"
            />
            <span className="text-sm font-semibold text-[color:var(--color-text-primary)]">
              {title}
            </span>
            <span className="text-xs leading-relaxed text-[color:var(--color-text-secondary)]">
              {description}
            </span>
          </label>
        );
      })}
    </div>
  );
}
