"use client";

import { DayPicker } from "react-day-picker";
import { ArrowLeft, ArrowRight } from "@phosphor-icons/react/dist/ssr";
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
        // grid 3列: [prev 36px] [label auto] [next 36px]
        month_caption: "grid grid-cols-[36px_1fr_36px] items-center py-2 px-1",
        caption_label: "col-start-2 text-center text-sm font-semibold tracking-wide text-[color:var(--color-text-primary)]",
        // nav は box を作らず子要素を親 grid に参加させる
        nav: "contents",
        button_previous:
          "col-start-1 group inline-flex h-8 w-8 items-center justify-center rounded-full text-[color:var(--color-text-tertiary)] transition-all hover:bg-[color:var(--color-primary)] hover:text-[color:var(--color-background)] hover:shadow-sm active:scale-90 disabled:pointer-events-none disabled:opacity-30",
        button_next:
          "col-start-3 group inline-flex h-8 w-8 items-center justify-center rounded-full text-[color:var(--color-text-tertiary)] transition-all hover:bg-[color:var(--color-primary)] hover:text-[color:var(--color-background)] hover:shadow-sm active:scale-90 disabled:pointer-events-none disabled:opacity-30",
        month_grid: "w-full border-collapse",
        weekdays: "flex",
        weekday:
          "text-[color:var(--color-text-tertiary)] rounded-md w-8 font-normal text-[0.8rem] text-center",
        week: "flex w-full mt-2",
        day: "relative p-0 text-center text-sm",
        day_button: cn(
          "inline-flex h-8 w-8 items-center justify-center rounded-md text-[color:var(--color-text-primary)] text-sm hover:bg-[color:var(--color-background)] hover:text-[color:var(--color-primary)] transition-colors focus-visible:outline-2 focus-visible:outline-[color:var(--color-primary)] disabled:pointer-events-none disabled:opacity-40",
        ),
        selected:
          "[&>button]:bg-[color:var(--color-primary)] [&>button]:text-[color:var(--color-background)] [&>button]:hover:bg-[color:var(--color-primary)] [&>button]:hover:text-[color:var(--color-background)]",
        today:
          "[&>button]:border [&>button]:border-[color:var(--color-accent)] [&>button]:font-semibold",
        outside:
          "[&>button]:text-[color:var(--color-text-tertiary)] [&>button]:opacity-40",
        disabled: "[&>button]:opacity-30 [&>button]:pointer-events-none",
        range_start: "[&>button]:rounded-r-none",
        range_end: "[&>button]:rounded-l-none",
        range_middle:
          "bg-[color:var(--color-background)] [&>button]:rounded-none",
        hidden: "invisible",
        ...classNames,
      }}
      components={{
        Chevron: ({ orientation }) =>
          orientation === "left" ? (
            <ArrowLeft size={15} weight="regular" />
          ) : (
            <ArrowRight size={15} weight="regular" />
          ),
      }}
      {...props}
    />
  );
}
