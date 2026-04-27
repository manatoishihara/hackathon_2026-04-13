"use client";

import { useState } from "react";
import { CalendarBlank } from "@phosphor-icons/react/dist/ssr";
import { Popover as PopoverPrimitive } from "@base-ui/react/popover";
import { Calendar } from "@/components/ui/calendar";
import { cn } from "@/lib/utils";

type IsoDate = string;

interface DateRangePickerProps {
  startDate: IsoDate;
  endDate: IsoDate;
  onStartChange: (date: IsoDate) => void;
  onEndChange: (date: IsoDate) => void;
  error?: string;
}

function parseIso(iso: IsoDate): Date | undefined {
  if (!iso) return undefined;
  const d = new Date(`${iso}T00:00:00`);
  return isNaN(d.getTime()) ? undefined : d;
}

function toIso(date: Date): IsoDate {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

const WEEKDAY_LABELS = ["日", "月", "火", "水", "木", "金", "土"];

function formatDisplay(iso: IsoDate): string {
  const d = parseIso(iso);
  if (!d) return "";
  const weekday = WEEKDAY_LABELS[d.getDay()];
  return `${d.getFullYear()}/${String(d.getMonth() + 1).padStart(2, "0")}/${String(d.getDate()).padStart(2, "0")} (${weekday})`;
}

interface CalendarPopoverProps {
  label: string;
  placeholder: string;
  value: IsoDate;
  onSelect: (date: Date) => void;
  disabledBefore?: Date;
}

function CalendarPopover({
  label,
  placeholder,
  value,
  onSelect,
  disabledBefore,
}: CalendarPopoverProps) {
  const [open, setOpen] = useState(false);

  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const disableFrom = disabledBefore ?? today;

  const parsed = parseIso(value);
  const display = formatDisplay(value);

  return (
    <PopoverPrimitive.Root open={open} onOpenChange={setOpen}>
      <div className="flex flex-col gap-1.5">
        <span className="text-xs font-medium text-[color:var(--color-text-secondary)]">
          {label}
        </span>
        <PopoverPrimitive.Trigger
          className={cn(
            "inline-flex h-10 w-full items-center gap-2 rounded-md border bg-[color:var(--color-surface)] px-3 text-sm transition-colors text-left",
            "focus-visible:outline-2 focus-visible:outline-[color:var(--color-primary)]",
            "border-[color:var(--color-border)] hover:border-[color:var(--color-primary)]/60",
            "aria-expanded:border-[color:var(--color-primary)] aria-expanded:ring-2 aria-expanded:ring-[color:var(--color-primary)]/20",
            value
              ? "text-[color:var(--color-text-primary)]"
              : "text-[color:var(--color-text-tertiary)]",
          )}
        >
          <CalendarBlank
            size={16}
            weight="regular"
            className="shrink-0 text-[color:var(--color-text-tertiary)]"
          />
          <span>{display || placeholder}</span>
        </PopoverPrimitive.Trigger>
      </div>

      <PopoverPrimitive.Portal>
        <PopoverPrimitive.Positioner sideOffset={6} align="start">
          <PopoverPrimitive.Popup className="z-50 rounded-lg border border-[color:var(--color-border)] bg-[color:var(--color-surface)] shadow-[0_8px_32px_rgba(4,44,83,0.14)] outline-none">
            <Calendar
              mode="single"
              selected={parsed}
              onSelect={(date) => {
                if (!date) return;
                onSelect(date);
                setOpen(false);
              }}
              disabled={{ before: disableFrom }}
              defaultMonth={parsed ?? disableFrom}
              weekStartsOn={0}
              formatters={{
                formatWeekdayName: (d) => WEEKDAY_LABELS[d.getDay()],
                formatCaption: (d) =>
                  `${d.getFullYear()}年 ${d.getMonth() + 1}月`,
              }}
            />
          </PopoverPrimitive.Popup>
        </PopoverPrimitive.Positioner>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  );
}

export function DateRangePicker({
  startDate,
  endDate,
  onStartChange,
  onEndChange,
  error,
}: DateRangePickerProps) {
  const [endOpen, setEndOpen] = useState(false);
  const startParsed = parseIso(startDate);

  const today = new Date();
  today.setHours(0, 0, 0, 0);

  const handleStartSelect = (date: Date) => {
    onStartChange(toIso(date));
    const endParsed = parseIso(endDate);
    if (endParsed && endParsed < date) {
      onEndChange("");
    }
    // 開始日を選んだら終了日ポップオーバーを自動で開く
    setTimeout(() => setEndOpen(true), 120);
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-2 gap-3">
        <CalendarPopover
          label="開始日"
          placeholder="出発日を選択"
          value={startDate}
          onSelect={handleStartSelect}
          disabledBefore={today}
        />

        {/* 終了日は external open state で自動オープンも制御 */}
        <EndCalendarPopover
          label="終了日"
          placeholder="帰宅日を選択"
          value={endDate}
          onSelect={(date) => onEndChange(toIso(date))}
          disabledBefore={startParsed ?? today}
          open={endOpen}
          onOpenChange={setEndOpen}
        />
      </div>

      {error ? (
        <p className="flex items-start gap-2 border-l-2 border-[color:var(--color-accent)] pl-2 text-xs leading-relaxed text-[color:var(--color-text-primary)]">
          {error}
        </p>
      ) : null}
    </div>
  );
}

function EndCalendarPopover({
  label,
  placeholder,
  value,
  onSelect,
  disabledBefore,
  open,
  onOpenChange,
}: CalendarPopoverProps & {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const disableFrom = disabledBefore ?? today;

  const parsed = parseIso(value);
  const display = formatDisplay(value);

  return (
    <PopoverPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <div className="flex flex-col gap-1.5">
        <span className="text-xs font-medium text-[color:var(--color-text-secondary)]">
          {label}
        </span>
        <PopoverPrimitive.Trigger
          className={cn(
            "inline-flex h-10 w-full items-center gap-2 rounded-md border bg-[color:var(--color-surface)] px-3 text-sm transition-colors text-left",
            "focus-visible:outline-2 focus-visible:outline-[color:var(--color-primary)]",
            "border-[color:var(--color-border)] hover:border-[color:var(--color-primary)]/60",
            "aria-expanded:border-[color:var(--color-primary)] aria-expanded:ring-2 aria-expanded:ring-[color:var(--color-primary)]/20",
            value
              ? "text-[color:var(--color-text-primary)]"
              : "text-[color:var(--color-text-tertiary)]",
          )}
        >
          <CalendarBlank
            size={16}
            weight="regular"
            className="shrink-0 text-[color:var(--color-text-tertiary)]"
          />
          <span>{display || placeholder}</span>
        </PopoverPrimitive.Trigger>
      </div>

      <PopoverPrimitive.Portal>
        <PopoverPrimitive.Positioner sideOffset={6} align="start">
          <PopoverPrimitive.Popup className="z-50 rounded-lg border border-[color:var(--color-border)] bg-[color:var(--color-surface)] shadow-[0_8px_32px_rgba(4,44,83,0.14)] outline-none">
            <Calendar
              mode="single"
              selected={parsed}
              onSelect={(date) => {
                if (!date) return;
                onSelect(date);
                onOpenChange(false);
              }}
              disabled={{ before: disableFrom }}
              defaultMonth={parsed ?? disableFrom}
              weekStartsOn={0}
              formatters={{
                formatWeekdayName: (d) => WEEKDAY_LABELS[d.getDay()],
                formatCaption: (d) =>
                  `${d.getFullYear()}年 ${d.getMonth() + 1}月`,
              }}
            />
          </PopoverPrimitive.Popup>
        </PopoverPrimitive.Positioner>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  );
}
