/**
 * 数値・日時フォーマッタ。
 * すべて JST / ja-JP 固定。AI 感を消すため必ず `Intl.NumberFormat` / `Intl.DateTimeFormat`
 * を通す（`.claude/rules/frontend-design.md` の「数字は必ず Intl.NumberFormat」ルール準拠）。
 */

const JPY_FORMATTER = new Intl.NumberFormat("ja-JP", {
  style: "currency",
  currency: "JPY",
  maximumFractionDigits: 0,
});

/** `48200` → `¥48,200` */
export function formatJpy(value: number): string {
  return JPY_FORMATTER.format(value);
}

const NUMBER_FORMATTER = new Intl.NumberFormat("ja-JP");

/** `48200` → `48,200` */
export function formatNumber(value: number): string {
  return NUMBER_FORMATTER.format(value);
}

const MONTH_DAY_FORMATTER = new Intl.DateTimeFormat("ja-JP", {
  month: "long",
  day: "numeric",
  weekday: "short",
  timeZone: "Asia/Tokyo",
});

/** ISO → `6月1日(日)` */
export function formatMonthDay(iso: string): string {
  return MONTH_DAY_FORMATTER.format(new Date(iso));
}

const HHMM_FORMATTER = new Intl.DateTimeFormat("ja-JP", {
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
  timeZone: "Asia/Tokyo",
});

/** ISO → `09:00`（JST 固定） */
export function formatHHmmJst(iso: string): string {
  return HHMM_FORMATTER.format(new Date(iso));
}

const DATE_RANGE_MONTH_DAY = new Intl.DateTimeFormat("ja-JP", {
  month: "numeric",
  day: "numeric",
  timeZone: "Asia/Tokyo",
});

/** `2026-06-01` + `2026-06-02` → `6/1 - 6/2` */
export function formatDateRange(startIso: string, endIso: string): string {
  const start = DATE_RANGE_MONTH_DAY.format(new Date(startIso));
  const end = DATE_RANGE_MONTH_DAY.format(new Date(endIso));
  return `${start} – ${end}`;
}

/** `90` → `1時間30分`、`45` → `45分` */
export function formatDurationMin(minutes: number): string {
  if (minutes < 60) return `${minutes}分`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (m === 0) return `${h}時間`;
  return `${h}時間${m}分`;
}
