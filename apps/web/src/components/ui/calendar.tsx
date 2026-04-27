"use client";

import { DayPicker } from "react-day-picker";
import { CaretLeft, CaretRight } from "@phosphor-icons/react/dist/ssr";
import { cn } from "@/lib/utils";

export type CalendarProps = React.ComponentProps<typeof DayPicker>;

export function Calendar({ className, classNames, showOutsideDays = true, ...props }: CalendarProps) {
  return (
    <DayPicker
      showOutsideDays={showOutsideDays}
      className={cn("p-3", className)}
      classNames={{
        months: "flex flex-col sm:flex-row gap-4",
        month: "flex flex-col gap-4",
        month_caption: "flex justify-center pt-1 relative items-center",
        caption_label: "text-sm font-medium text-[color:var(--color-text-primary)]",
        nav: "flex items-center gap-1",
        button_previous: cn(
          "absolute left-1 inline-flex h-7 w-7 items-center justify-center rounded-md border border-[color:var(--color-border)] bg-[color:var(--color-surface)] text-[color:var(--color-text-secondary)] hover:bg-[color:var(--color-background)] hover:text-[color:var(--color-primary)] transition-colors disabled:pointer-events-none disabled:opacity-40",
        ),
        button_next: cn(
          "absolute right-1 inline-flex h-7 w-7 items-center justify-center rounded-md border border-[color:var(--color-border)] bg-[color:var(--color-surface)] text-[color:var(--color-text-secondary)] hover:bg-[color:var(--color-background)] hover:text-[color:var(--color-primary)] transition-colors disabled:pointer-events-none disabled:opacity-40",
        ),
        month_grid: "w-full border-collapse",
        weekdays: "flex",
        weekday: "text-[color:var(--color-text-tertiary)] rounded-md w-8 font-normal text-[0.8rem] text-center",
        week: "flex w-full mt-2",
        day: "relative p-0 text-center text-sm",
        day_button: cn(
          "inline-flex h-8 w-8 items-center justify-center rounded-md text-[color:var(--color-text-primary)] text-sm hover:bg-[color:var(--color-background)] hover:text-[color:var(--color-primary)] transition-colors focus-visible:outline-2 focus-visible:outline-[color:var(--color-primary)] disabled:pointer-events-none disabled:opacity-40",
        ),
        selected: "[&>button]:bg-[color:var(--color-primary)] [&>button]:text-[color:var(--color-background)] [&>button]:hover:bg-[color:var(--color-primary)] [&>button]:hover:text-[color:var(--color-background)]",
        today: "[&>button]:border [&>button]:border-[color:var(--color-accent)] [&>button]:text-[color:var(--color-accent)]",
        outside: "[&>button]:text-[color:var(--color-text-tertiary)] [&>button]:opacity-50",
        disabled: "[&>button]:text-[color:var(--color-text-tertiary)] [&>button]:opacity-40",
        range_start: "[&>button]:rounded-r-none",
        range_end: "[&>button]:rounded-l-none",
        range_middle: "bg-[color:var(--color-background)] [&>button]:rounded-none",
        hidden: "invisible",
        ...classNames,
      }}
      components={{
        Chevron: ({ orientation }) =>
          orientation === "left" ? (
            <CaretLeft size={14} weight="bold" />
          ) : (
            <CaretRight size={14} weight="bold" />
          ),
      }}
      {...props}
    />
  );
}
