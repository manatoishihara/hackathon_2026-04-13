"use client";

import { Slider } from "@/components/ui/slider";
import type { BudgetBreakdown } from "shared-types";

type Props = {
  value: BudgetBreakdown;
  onChange: (next: BudgetBreakdown) => void;
};

type CategoryKey = keyof BudgetBreakdown;

const CATEGORY_LABEL: Record<CategoryKey, string> = {
  lodging: "宿泊",
  meal: "食事",
  activity: "観光",
  transit: "交通",
};

const ORDER: CategoryKey[] = ["lodging", "meal", "activity", "transit"];

/**
 * 合計 100% を保つ 4 連予算スライダー。
 * 1 つを動かすと、他カテゴリが比例配分で調整される（rebalance）。
 * blue hour トーン: 合計バーは Deep Navy、% は font-mono、ズレたら Coral 警告。
 */
export function BudgetBreakdownSlider({ value, onChange }: Props) {
  const handleChange = (changed: CategoryKey, nextValue: number) => {
    const clamped = Math.max(0, Math.min(100, Math.round(nextValue)));
    onChange(rebalance(value, changed, clamped));
  };

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-5">
        {ORDER.map((cat) => (
          <div key={cat} className="flex flex-col gap-2">
            <div className="flex items-baseline justify-between text-sm">
              <span className="font-medium text-[color:var(--color-text-primary)]">
                {CATEGORY_LABEL[cat]}
              </span>
              <span className="font-mono tabular-nums text-[color:var(--color-primary)]">
                <span className="text-lg">{value[cat]}</span>
                <span className="ml-0.5 text-xs text-[color:var(--color-text-secondary)]">
                  %
                </span>
              </span>
            </div>
            <Slider
              value={[value[cat]]}
              min={0}
              max={100}
              step={1}
              onValueChange={(v) => {
                const next = Array.isArray(v) ? (v[0] ?? 0) : v;
                handleChange(cat, next);
              }}
            />
          </div>
        ))}
      </div>
    </div>
  );
}

/**
 * 1 つの値が変わった時、他 3 項目を比例配分して合計 100% を保つ。
 * テストしやすいように export する（既存テストとの互換性を維持）。
 */
export function rebalance(
  current: BudgetBreakdown,
  changed: CategoryKey,
  newValue: number,
): BudgetBreakdown {
  const clampedValue = Math.max(0, Math.min(100, Math.round(newValue)));
  const others = ORDER.filter((k) => k !== changed);
  const remaining = 100 - clampedValue;
  const otherTotal = others.reduce((sum, k) => sum + current[k], 0);

  const next = { ...current, [changed]: clampedValue };

  if (otherTotal === 0) {
    const share = Math.floor(remaining / others.length);
    const extra = remaining - share * others.length;
    others.forEach((k, i) => {
      next[k] = share + (i < extra ? 1 : 0);
    });
    return next;
  }

  let assigned = 0;
  const shares: number[] = [];
  for (const k of others) {
    const raw = (current[k] / otherTotal) * remaining;
    const rounded = Math.round(raw);
    shares.push(rounded);
    assigned += rounded;
  }
  const diff = remaining - assigned;
  if (diff !== 0 && shares.length > 0) {
    shares[0] += diff;
  }
  others.forEach((k, i) => {
    next[k] = Math.max(0, Math.min(100, shares[i]));
  });
  return next;
}
