"use client";

type Day = {
  /** "2026-06-01" */
  dateKey: string;
  /** 「6月1日(日)」表示用、上位で formatMonthDay を通して渡す */
  label: string;
};

type Props = {
  days: Day[];
  activeDateKey: string;
  onChange: (dateKey: string) => void;
};

/**
 * DAY 1 / DAY 2 / DAY 3 ... のタブ。HTML モック準拠。
 * active は Deep Navy 塗り、inactive は白背景 + 薄い境界線。
 */
export function DayTabs({ days, activeDateKey, onChange }: Props) {
  if (days.length === 0) return null;
  if (days.length === 1) {
    // 1 日プランならタブ不要、ただしラベルは出す（情報密度のため）
    const day = days[0];
    return (
      <div className="rounded-md border border-[color:var(--color-border)] bg-[color:var(--color-surface)] px-4 py-3">
        <p className="text-[10px] font-medium tracking-[0.18em] text-[color:var(--color-text-secondary)]">
          DAY 1
        </p>
        <p className="font-heading text-base text-[color:var(--color-text-primary)]">
          {day.label}
        </p>
      </div>
    );
  }

  return (
    <div
      className="grid gap-1.5"
      style={{ gridTemplateColumns: `repeat(${days.length}, minmax(0, 1fr))` }}
      role="tablist"
      aria-label="日程タブ"
    >
      {days.map((day, i) => {
        const active = day.dateKey === activeDateKey;
        return (
          <button
            key={day.dateKey}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(day.dateKey)}
            className={`flex flex-col items-start gap-1 rounded-md px-3 py-2.5 text-left transition-colors ${
              active
                ? "bg-[color:var(--color-primary)] text-[color:var(--color-background)]"
                : "border border-[color:var(--color-border)] bg-[color:var(--color-surface)] text-[color:var(--color-text-primary)] hover:border-[color:var(--color-primary)]/40"
            }`}
          >
            <span
              className={`text-[10px] font-medium tracking-[0.18em] ${
                active
                  ? "text-[color:var(--color-background)]/65"
                  : "text-[color:var(--color-text-secondary)]"
              }`}
            >
              DAY {i + 1}
            </span>
            <span className="font-heading text-sm">{day.label}</span>
          </button>
        );
      })}
    </div>
  );
}
