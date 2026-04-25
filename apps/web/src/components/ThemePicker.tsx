"use client";

import { THEME_KEYS, THEME_LABELS_JP } from "shared-types";

import type { ThemeKey } from "@/lib/schemas/planForm";

// shared-types の単一情報源から導出（Codex Major 2 対応）。
// theme 追加 / 改名は shared-types/src/index.ts のみ編集すれば全箇所に反映される。
export const THEME_OPTIONS: ReadonlyArray<{ key: ThemeKey; label: string }> =
  THEME_KEYS.map((key) => ({ key, label: THEME_LABELS_JP[key] }));

type Props = {
  /** 現在選択中の theme key（未選択時は null） */
  value: ThemeKey | null;
  /** 選択変更コールバック。同じ chip 再クリックで null（選択解除） */
  onChange: (next: ThemeKey | null) => void;
};

/**
 * Phase 2.1 出発モード切替「テーマ」UI。
 * 6 種から 1 つを単一選択（toggle で解除可）。LLM プロンプトに theme key が
 * mode_payload.theme として渡され、pack の検索 keyword も bias される。
 */
export function ThemePicker({ value, onChange }: Props) {
  return (
    <div className="flex flex-wrap gap-2">
      {THEME_OPTIONS.map(({ key, label }) => {
        const active = value === key;
        return (
          <button
            type="button"
            key={key}
            aria-pressed={active}
            onClick={() => onChange(active ? null : key)}
            className={`rounded-full border px-4 py-1.5 text-sm font-medium transition-colors ${
              active
                ? "border-[color:var(--color-primary)] bg-[color:var(--color-primary)] text-[color:var(--color-background)]"
                : "border-[color:var(--color-border)] bg-[color:var(--color-surface)] text-[color:var(--color-text-secondary)] hover:border-[color:var(--color-primary)] hover:text-[color:var(--color-primary)]"
            }`}
          >
            {label}
          </button>
        );
      })}
    </div>
  );
}
