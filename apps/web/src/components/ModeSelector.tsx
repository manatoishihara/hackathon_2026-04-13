"use client";

import type { StartMode } from "shared-types";

const MODE_OPTIONS: ReadonlyArray<{
  key: StartMode;
  title: string;
  description: string;
}> = [
  {
    key: "auto",
    title: "お任せ",
    description: "AI が参加者の希望から全体を組み立てます。",
  },
  {
    key: "anchor",
    title: "こだわり",
    description: "必ず行きたい場所を 1〜3 件決めて、その周りを組み立てます。",
  },
];

type Props = {
  value: StartMode;
  onChange: (next: StartMode) => void;
  /** SR 用の group label を外部の見出し（h2 等）と関連付ける場合に渡す（Codex Minor 4） */
  ariaLabelledBy?: string;
};

/**
 * Phase 2.1 出発モード切替。2 モード（auto / anchor）の radio 群。
 * 選択された mode に応じて、page 側で AnchorPicker を条件レンダリング
 * する想定（本コンポーネントは mode 選択そのものだけを担当）。
 *
 * a11y: role="radiogroup" でグループ意味付けを SR に伝える（Codex Minor 4 対応）。
 */
export function ModeSelector({ value, onChange, ariaLabelledBy }: Props) {
  return (
    <div
      role="radiogroup"
      aria-labelledby={ariaLabelledBy}
      className="flex flex-col gap-2 sm:flex-row sm:flex-wrap"
    >
      {MODE_OPTIONS.map(({ key, title, description }) => {
        const active = value === key;
        const id = `mode-${key}`;
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
              name="start_mode"
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
