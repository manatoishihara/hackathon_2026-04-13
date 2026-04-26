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

/**
 * Evidence の `verified_at` を表示用に整形。
 * locale 依存を避けるため `formatToParts` で部品取得 → `YYYY-MM-DD HH:mm`（JST 固定）に組み立てる。
 * 値が無い・無効な場合は `"— 不明"`（不在 fallback）。
 */
const VERIFIED_AT_FORMATTER = new Intl.DateTimeFormat("en-CA", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
  timeZone: "Asia/Tokyo",
});

export const UNKNOWN_VALUE_LABEL = "— 不明";

export function formatVerifiedAt(iso?: string | null): string {
  if (!iso) return UNKNOWN_VALUE_LABEL;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return UNKNOWN_VALUE_LABEL;
  const parts = VERIFIED_AT_FORMATTER.formatToParts(date);
  const map: Record<string, string> = {};
  for (const part of parts) {
    if (part.type !== "literal") map[part.type] = part.value;
  }
  // hour: "2-digit" + hour12: false を渡すと "24" を返す環境があるので 00 に正規化
  if (map.hour === "24") map.hour = "00";
  return `${map.year}-${map.month}-${map.day} ${map.hour}:${map.minute}`;
}
