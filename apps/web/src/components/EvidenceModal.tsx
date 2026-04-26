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
import { formatVerifiedAt, UNKNOWN_VALUE_LABEL } from "@/lib/format";

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

  const rating = formatRating(evidence.rating);
  const priceLevel = formatPriceLevel(evidence.price_level);
  const sources = formatSources(evidence.sources);
  const verifiedAt = formatVerifiedAt(evidence.verified_at);
  // codex review 2 回目 Minor: 空文字 / 空白のみも「不在」扱い
  const openingHours = evidence.opening_hours?.trim()
    ? evidence.opening_hours
    : UNKNOWN_VALUE_LABEL;

  const mapsUrl = buildGoogleMapsUrl({
    placeId: item.location.place_id,
    placeName: item.location.place_name,
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

function formatRating(rating: number | undefined): { text: string; dim: boolean } {
  if (typeof rating !== "number" || Number.isNaN(rating)) {
    return { text: UNKNOWN_VALUE_LABEL, dim: true };
  }
  return { text: `★ ${rating.toFixed(1)} / 5.0`, dim: false };
}

function formatPriceLevel(level: number | undefined): { text: string; dim: boolean } {
  if (typeof level !== "number" || level < 1 || level > 4) {
    return { text: UNKNOWN_VALUE_LABEL, dim: true };
  }
  return { text: "¥".repeat(level), dim: false };
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
