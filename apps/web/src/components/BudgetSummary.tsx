import type { Plan, PlanItem } from "shared-types";

import { formatJpy } from "@/lib/format";
import { Progress } from "@/components/ui/progress";

type Props = {
  plan: Plan;
  items: PlanItem[];
};

type CategoryKey = "lodging" | "meal" | "activity" | "transit";

const CATEGORY_LABEL: Record<CategoryKey, string> = {
  lodging: "宿泊",
  meal: "食事",
  activity: "観光",
  transit: "交通",
};

/**
 * 予算カテゴリ別の消化状況を表示。
 * `plan.budget_breakdown`（%）+ `plan.budget_per_person_jpy` で各カテゴリの上限を算出し、
 * `items` の `cost_jpy` 合計を重ねる。脇役コンポーネントなので控えめに。
 */
export function BudgetSummary({ plan, items }: Props) {
  const totalPerPerson = plan.budget_per_person_jpy;
  const categories: CategoryKey[] = ["lodging", "meal", "activity", "transit"];

  const spentByCategory = computeSpentByCategory(items);

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-[color:var(--color-border)] bg-[color:var(--color-surface)] p-3 sm:gap-4 sm:p-4">
      <div className="flex items-baseline justify-between">
        <h3 className="text-xs font-semibold text-[color:var(--color-text-secondary)] sm:text-sm">
          予算（1 人あたり）
        </h3>
        <p className="font-mono text-base font-semibold tabular-nums text-[color:var(--color-text-primary)] sm:text-lg">
          {formatJpy(totalPerPerson)}
        </p>
      </div>
      <div className="flex flex-col gap-2.5 sm:gap-3">
        {categories.map((cat) => {
          const allocatedPct = plan.budget_breakdown[cat];
          const allocatedJpy = Math.round((totalPerPerson * allocatedPct) / 100);
          const spentJpy = spentByCategory[cat];
          const pctUsed = allocatedJpy === 0 ? 0 : Math.min(100, Math.round((spentJpy / allocatedJpy) * 100));
          return (
            <div key={cat} className="flex flex-col gap-1">
              <div className="flex items-baseline justify-between text-xs sm:text-sm">
                <span className="text-[color:var(--color-text-primary)]">
                  {CATEGORY_LABEL[cat]}
                  <span className="ml-1.5 text-[11px] text-[color:var(--color-text-tertiary)] sm:ml-2 sm:text-xs">
                    {allocatedPct}%
                  </span>
                </span>
                <span className="font-mono text-[11px] tabular-nums text-[color:var(--color-text-secondary)] sm:text-xs">
                  {formatJpy(spentJpy)} / {formatJpy(allocatedJpy)}
                </span>
              </div>
              <Progress value={pctUsed} />
            </div>
          );
        })}
      </div>
    </div>
  );
}

/**
 * PlanItem[] を category ごとに合計する。`transit_to_next` 運賃も transit に加算。
 */
export function computeSpentByCategory(items: PlanItem[]): Record<CategoryKey, number> {
  const total: Record<CategoryKey, number> = {
    lodging: 0,
    meal: 0,
    activity: 0,
    transit: 0,
  };
  for (const item of items) {
    const category = mapItemTypeToCategory(item.item_type);
    if (category && item.cost_jpy != null) {
      total[category] += item.cost_jpy;
    }
    if (item.transit_to_next?.fare_jpy != null) {
      total.transit += item.transit_to_next.fare_jpy;
    }
  }
  return total;
}

function mapItemTypeToCategory(itemType: PlanItem["item_type"]): CategoryKey | null {
  switch (itemType) {
    case "lodging":
      return "lodging";
    case "meal":
      return "meal";
    case "activity":
      return "activity";
    case "transit":
      return "transit";
    default:
      return null;
  }
}
