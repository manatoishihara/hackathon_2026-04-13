"use client";

import { useState } from "react";
import { X } from "@phosphor-icons/react/dist/ssr";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const MAX_ANCHORS = 3;

type Props = {
  /** 現在選択中の place_id 配列（最大 3 件） */
  value: string[];
  /** 選択変更コールバック */
  onChange: (next: string[]) => void;
};

/**
 * Phase 2.1 出発モード切替「アンカー」UI（MVP）。
 *
 * 必ず含めたい場所の Google Places place_id を 1〜3 件指定。LLM プロンプトで
 * 「これらを必ず slot に割当てよ」と明示され、assembler が post-check で検証する。
 *
 * 現状は手動 place_id 貼付け方式。Maps JS Places Autocomplete UI 統合は polish 課題
 * （hackathon 提出後の次イテレーション）。デモ時は事前に取得した place_id を貼る運用。
 */
export function AnchorPicker({ value, onChange }: Props) {
  const [draft, setDraft] = useState("");
  const isFull = value.length >= MAX_ANCHORS;

  const handleAdd = () => {
    const trimmed = draft.trim();
    if (!trimmed) return;
    if (value.includes(trimmed)) return; // duplicate
    if (isFull) return;
    onChange([...value, trimmed]);
    setDraft("");
  };

  const handleRemove = (placeId: string) => {
    onChange(value.filter((id) => id !== placeId));
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap gap-2">
        {value.map((placeId) => (
          <span
            key={placeId}
            className="inline-flex items-center gap-1.5 rounded-full border border-[color:var(--color-primary)] bg-[color:var(--color-primary)]/8 px-3 py-1 text-xs font-medium text-[color:var(--color-primary)]"
          >
            <span className="font-mono">{placeId}</span>
            <button
              type="button"
              aria-label={`${placeId} を削除`}
              onClick={() => handleRemove(placeId)}
              className="-mr-1 rounded-full p-0.5 hover:bg-[color:var(--color-primary)]/15"
            >
              <X size={12} weight="bold" />
            </button>
          </span>
        ))}
        {value.length === 0 ? (
          <p className="text-xs text-[color:var(--color-text-tertiary)]">
            必ず行きたい場所の Google Place ID を 1〜3 件登録してください
          </p>
        ) : null}
      </div>

      <div className="flex items-end gap-2">
        <div className="flex flex-1 flex-col gap-1">
          <Label htmlFor="anchor_place_id">place_id</Label>
          <Input
            id="anchor_place_id"
            placeholder="例: ChIJN1t_tDeuEmsRUsoyG83frY4"
            value={draft}
            disabled={isFull}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                handleAdd();
              }
            }}
          />
        </div>
        <button
          type="button"
          onClick={handleAdd}
          disabled={isFull}
          className="rounded-full border border-[color:var(--color-primary)] bg-[color:var(--color-surface)] px-5 py-2 text-sm font-medium text-[color:var(--color-primary)] transition hover:bg-[color:var(--color-primary)] hover:text-[color:var(--color-background)] disabled:cursor-not-allowed disabled:opacity-40"
        >
          追加
        </button>
      </div>

      <p className="text-xs text-[color:var(--color-text-tertiary)]">
        最大 3 件。Google Maps の URL から place_id を取得できます。
        {isFull ? "（上限到達）" : null}
      </p>
    </div>
  );
}
