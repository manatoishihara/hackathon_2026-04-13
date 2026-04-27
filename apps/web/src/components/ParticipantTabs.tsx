"use client";

import { Plus, X } from "@phosphor-icons/react/dist/ssr";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ParticipantForm } from "./ParticipantForm";
import type { ParticipantFormInput } from "@/lib/schemas/planForm";

const MIN_PARTICIPANTS = 2;
const MAX_PARTICIPANTS = 5;

type Props = {
  participants: ParticipantFormInput[];
  activeIndex: number;
  onActiveChange: (index: number) => void;
  onParticipantChange: (index: number, next: ParticipantFormInput) => void;
  onAddParticipant: () => void;
  onRemoveParticipant: (index: number) => void;
  onAddTag: (index: number, tag: string) => void;
  onRemoveTag: (index: number, tag: string) => void;
};

/**
 * 参加者 2〜5 人をタブで管理。追加/削除/切替を行う。
 * blue hour トーン: タブは下線のみで active 表現、ナンバリング (01, 02...) を添える。
 */
export function ParticipantTabs({
  participants,
  activeIndex,
  onActiveChange,
  onParticipantChange,
  onAddParticipant,
  onRemoveParticipant,
  onAddTag,
  onRemoveTag,
}: Props) {
  const canRemove = participants.length > MIN_PARTICIPANTS;
  const canAdd = participants.length < MAX_PARTICIPANTS;

  return (
    <Tabs
      value={String(activeIndex)}
      onValueChange={(v) => onActiveChange(Number(v))}
      className="w-full"
    >
      <div className="flex flex-wrap items-end justify-between gap-y-1 border-b border-[color:var(--color-border)] sm:gap-y-2">
        <TabsList className="flex-wrap !h-auto !gap-0 !rounded-none !bg-transparent !p-0">
          {participants.map((p, i) => (
            <TabsTrigger
              key={p.order_index}
              value={String(i)}
              className="group relative !rounded-none !bg-transparent px-2 py-2 text-xs font-medium text-[color:var(--color-text-secondary)] transition-colors data-[state=active]:!bg-transparent data-[state=active]:!shadow-none data-[state=active]:text-[color:var(--color-text-primary)] sm:px-3 sm:py-2.5 sm:text-sm"
            >
              <span className="flex items-center gap-1.5 sm:gap-2">
                <span
                  aria-hidden
                  className="font-mono text-[9px] tabular-nums text-[color:var(--color-text-tertiary)] group-data-[state=active]:text-[color:var(--color-accent)] sm:text-[10px]"
                >
                  {String(i + 1).padStart(2, "0")}
                </span>
                <span
                  aria-hidden
                  className="h-1.5 w-1.5 rounded-full sm:h-2 sm:w-2"
                  style={{ backgroundColor: p.avatar_color }}
                />
                <span className="max-w-[8ch] truncate sm:max-w-[12ch]">
                  {p.display_name || `参加者 ${i + 1}`}
                </span>
              </span>
              <span
                aria-hidden
                className="absolute inset-x-0 -bottom-px h-[2px] bg-[color:var(--color-primary)] opacity-0 transition-opacity group-data-[state=active]:opacity-100"
              />
            </TabsTrigger>
          ))}
        </TabsList>
        <div className="flex items-center gap-1.5 pb-1 sm:gap-2 sm:pb-1.5">
          {canRemove ? (
            <button
              type="button"
              onClick={() => onRemoveParticipant(activeIndex)}
              className="inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-[11px] text-[color:var(--color-text-secondary)] transition-colors hover:bg-[color:var(--color-danger)]/10 hover:text-[color:var(--color-danger)] sm:px-2 sm:text-xs"
              aria-label={`${participants[activeIndex]?.display_name || `参加者 ${activeIndex + 1}`} を削除`}
            >
              <X size={12} weight="bold" />
              削除
            </button>
          ) : null}
          {canAdd ? (
            <button
              type="button"
              onClick={onAddParticipant}
              className="inline-flex items-center gap-1 rounded-md border border-dashed border-[color:var(--color-border)] px-1.5 py-1 text-[11px] font-medium text-[color:var(--color-text-secondary)] transition-colors hover:border-[color:var(--color-primary)] hover:text-[color:var(--color-primary)] sm:px-2.5 sm:text-xs"
            >
              <Plus size={12} weight="bold" />
              参加者を追加
            </button>
          ) : null}
        </div>
      </div>
      {participants.map((p, i) => (
        <TabsContent key={p.order_index} value={String(i)} className="pt-6">
          <ParticipantForm
            value={p}
            onChange={(next) => onParticipantChange(i, next)}
            onAddTag={(tag) => onAddTag(i, tag)}
            onRemoveTag={(tag) => onRemoveTag(i, tag)}
          />
        </TabsContent>
      ))}
    </Tabs>
  );
}
