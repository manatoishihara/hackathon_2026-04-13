"use client";

import { useId } from "react";
import { ArrowSquareOut, X } from "@phosphor-icons/react/dist/ssr";
import type { PlanItem } from "shared-types";

import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { formatJpy, formatVerifiedAt, UNKNOWN_VALUE_LABEL } from "@/lib/format";

type Props = {
  item: PlanItem;
  open: boolean;
  onOpenChange: (open: boolean) => void;
};

/**
 * Evidence 詳細モーダル。Phase 2.5 の demo 訴求コンポーネント。
 * - 5 フィールド（営業時間 / 評価 / 価格帯 / 出典 / 検証日時）を行レイアウトで表示
 * - place_id がある場合に Google Maps への外部リンクを footer に
 * - 不在フィールドは「— 不明」（grayed）で統一
 */
export function EvidenceModal({ item, open, onOpenChange }: Props) {
  const titleId = useId();
  const evidence = item.evidence;

  // Task B2 (2026-04-28): lodging item は 24h 営業前提なので、opening_hours 不在
  // でも「— 不明」ではなく「終日 (チェックイン 15:00 / チェックアウト 10:00)」と
  // 自然に表記する。評価も lodging 不在時は「評価情報なし (レビュー数不足)」と原因明示。
  const isLodging = item.item_type === "lodging";
  const rating = formatRating(evidence.rating, isLodging);
  // Phase 3 polish 案 D 第 4 段 (2026-04-28): price_level が無くても cost_jpy が
  // estimated として埋まっていれば「¥X,XXX (推定)」で表示する。価格帯=不明のまま
  // plan には cost が出てる乖離を解消する。
  const priceLevel = formatPriceLevel(
    evidence.price_range_jpy,
    evidence.price_level,
    item.cost_jpy ?? null,
    item.cost_confidence,
  );
  const sources = formatSources(evidence.sources);
  const verifiedAt = formatVerifiedAt(evidence.verified_at);
  // codex review 2 回目 Minor: 空文字 / 空白のみも「不在」扱い
  const openingHours = evidence.opening_hours?.trim()
    ? evidence.opening_hours
    : isLodging
      ? "終日 (チェックイン 15:00 / チェックアウト 10:00)"
      : UNKNOWN_VALUE_LABEL;

  // transit item や location 不在の item で `item.location` が undefined になる
  // ケース（Phase 2.5 design でも null セーフガード漏れ）。Optional chaining で
  // render error を避けつつ、buildGoogleMapsUrl 側で fallbackTitle 経由にフォールバック。
  const mapsUrl = buildGoogleMapsUrl({
    placeId: item.location?.place_id ?? null,
    placeName: item.location?.place_name ?? null,
    fallbackTitle: item.title,
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        showCloseButton={false}
        aria-labelledby={titleId}
        className="max-w-md"
      >
        <DialogTitle id={titleId} className="pr-8">
          {item.title} の根拠
        </DialogTitle>

        <DialogClose
          render={
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="閉じる"
              className="absolute top-2 right-2"
            />
          }
        >
          <X size={16} weight="bold" />
        </DialogClose>

        <dl className="grid grid-cols-[88px_1fr] gap-y-2 text-sm">
          <Row label="営業時間" value={openingHours} dim={openingHours === UNKNOWN_VALUE_LABEL} />
          <Row label="評価" value={rating.text} dim={rating.dim} />
          <Row label="価格帯" value={priceLevel.text} dim={priceLevel.dim} />
          <Row label="出典" value={sources.text} dim={sources.dim} />
          <Row label="検証日時" value={verifiedAt} dim={verifiedAt === UNKNOWN_VALUE_LABEL} />
        </dl>

        {evidence.external_url ? (
          <div className="mt-2 flex justify-end">
            <a
              href={evidence.external_url}
              target="_blank"
              rel="noopener noreferrer"
              aria-label="楽天トラベルで詳細を開く（新しいタブ）"
              className="inline-flex items-center gap-1.5 rounded-md border border-[color:var(--color-accent)] bg-[color:var(--color-accent)] px-3 py-1.5 text-xs font-medium text-[color:var(--color-surface)] transition-opacity hover:opacity-90"
            >
              <ArrowSquareOut size={14} weight="bold" />
              楽天トラベルで見る
            </a>
          </div>
        ) : null}

        {mapsUrl ? (
          <div className="mt-2 flex justify-end">
            <a
              href={mapsUrl}
              target="_blank"
              rel="noopener noreferrer"
              aria-label="Google Mapsで開く（新しいタブ）"
              className="inline-flex items-center gap-1.5 rounded-md border border-[color:var(--color-primary)] bg-[color:var(--color-surface)] px-3 py-1.5 text-xs font-medium text-[color:var(--color-primary)] transition-colors hover:bg-[color:var(--color-primary)] hover:text-[color:var(--color-surface)]"
            >
              <ArrowSquareOut size={14} weight="bold" />
              Google Maps で開く
            </a>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

function Row({
  label,
  value,
  dim,
}: {
  label: string;
  value: string;
  dim: boolean;
}) {
  return (
    <div className="contents">
      <dt className="text-[12px] font-medium text-[color:var(--color-text-secondary)]">
        {label}
      </dt>
      <dd
        className={`font-heading text-[13px] ${
          dim
            ? "text-[color:var(--color-text-tertiary)]"
            : "text-[color:var(--color-text-primary)]"
        }`}
      >
        {value}
      </dd>
    </div>
  );
}

function formatRating(
  rating: number | undefined,
  isLodging: boolean,
): { text: string; dim: boolean } {
  if (typeof rating !== "number" || Number.isNaN(rating)) {
    // Task B2 (2026-04-28): lodging は楽天トラベルの hotelRatingInfo.reviewAverage が
    // レビュー数不足で None になることがあるので、原因明示の文言にする。
    return {
      text: isLodging ? "評価情報なし (レビュー数不足)" : UNKNOWN_VALUE_LABEL,
      dim: true,
    };
  }
  return { text: `★ ${rating.toFixed(1)} / 5.0`, dim: false };
}

function formatPriceLevel(
  priceRange: { start: number; end: number } | undefined,
  level: number | undefined,
  costJpy: number | null,
  costConfidence: "verified" | "estimated" | "unknown",
): { text: string; dim: boolean } {
  // Phase 3 polish 第 9 段 Modal 配線 fix (2026-04-28): Google Places (New) の
  // priceRange が取れていれば「¥1,500〜¥3,000」と実数値レンジで表示する (最優先)。
  // ¥¥¥ 記号より具体的、cost_jpy より範囲表示で user に有益。
  if (
    priceRange &&
    typeof priceRange.start === "number" &&
    typeof priceRange.end === "number" &&
    priceRange.start >= 0 &&
    priceRange.end >= priceRange.start
  ) {
    if (priceRange.start === priceRange.end) {
      return { text: formatJpy(priceRange.start), dim: false };
    }
    return {
      text: `${formatJpy(priceRange.start)}〜${formatJpy(priceRange.end)}`,
      dim: false,
    };
  }
  // Phase 3 polish 第 9 段 Modal 配線 hotfix2 (2026-04-28、楽天宿 ¥ 表示問題対応):
  // cost_confidence="verified" な cost_jpy は外部 API (楽天等) の実取得値で、
  // price_level の ¥¥¥ 記号 (推定 4 段階) より具体的・確定情報。priceRange の次に
  // 優先する。例: 楽天 lodging で price_jpy=12,000 が verified なら「￥12,000」表示
  // (price_level=2 の ¥¥ 記号より有益)。
  if (
    typeof costJpy === "number" &&
    costJpy > 0 &&
    costConfidence === "verified"
  ) {
    return { text: formatJpy(costJpy), dim: false };
  }
  // priceRange / verified cost_jpy が無い時の fallback: Google Places の
  // price_level (1〜4) → ¥¥¥¥ 記号
  if (typeof level === "number" && level >= 1 && level <= 4) {
    return { text: "¥".repeat(level), dim: false };
  }
  // Phase 3 polish 案 D 第 4 段 (2026-04-28): price_level 無しでも、内部で
  // estimated 値が cost_jpy に埋まっていれば「¥X,XXX (推定)」で表示する。
  // 「価格帯=不明」と「plan には推定値が出てる」の乖離を解消する狙い。
  if (
    typeof costJpy === "number" &&
    costJpy > 0 &&
    costConfidence === "estimated"
  ) {
    return { text: `${formatJpy(costJpy)} (推定)`, dim: false };
  }
  return { text: UNKNOWN_VALUE_LABEL, dim: true };
}

function formatSources(sources: readonly string[] | undefined): {
  text: string;
  dim: boolean;
} {
  if (!sources || sources.length === 0) {
    return { text: UNKNOWN_VALUE_LABEL, dim: true };
  }
  return { text: sources.join(" / "), dim: false };
}

function buildGoogleMapsUrl({
  placeId,
  placeName,
  fallbackTitle,
}: {
  placeId: string | null;
  placeName: string | null;
  fallbackTitle: string;
}): string | null {
  if (!placeId) return null;
  // codex review 2 回目 Minor: place_name が空文字 / 空白のみだと query が空になるので、title fallback
  const query = placeName?.trim() ? placeName : fallbackTitle;
  const params = new URLSearchParams({
    api: "1",
    query,
    query_place_id: placeId,
  });
  return `https://www.google.com/maps/search/?${params.toString()}`;
}
