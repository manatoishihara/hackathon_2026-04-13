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
 * 1.5 の希望入力画面で使う。参加者数制約は UI 側でハードガード（MIN/MAX）。
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
      <div className="flex flex-wrap items-center gap-2">
        <TabsList className="flex-wrap">
          {participants.map((p, i) => (
            <TabsTrigger key={p.order_index} value={String(i)} className="gap-1">
              <span
                className="h-2 w-2 rounded-full"
                style={{ backgroundColor: p.avatar_color }}
                aria-hidden="true"
              />
              {p.display_name || `参加者 ${i + 1}`}
            </TabsTrigger>
          ))}
        </TabsList>
        {/* 削除ボタンは TabsTrigger の外に出す（button のネストはアクセシビリティ違反）。
           選択中の参加者だけ削除ボタンを出し、最低人数 (MIN_PARTICIPANTS) に達していれば隠す。 */}
        {canRemove ? (
          <button
            type="button"
            onClick={() => onRemoveParticipant(activeIndex)}
            className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-[color:var(--color-text-secondary)] hover:bg-[color:var(--color-danger)]/10 hover:text-[color:var(--color-danger)]"
            aria-label={`${participants[activeIndex]?.display_name || `参加者 ${activeIndex + 1}`} を削除`}
          >
            <X size={12} weight="bold" />
            この参加者を削除
          </button>
        ) : null}
        {canAdd ? (
          <button
            type="button"
            onClick={onAddParticipant}
            className="inline-flex items-center gap-1 rounded-md border border-dashed border-[color:var(--color-border)] px-2 py-1 text-xs text-[color:var(--color-text-secondary)] hover:bg-[color:var(--color-surface)]"
          >
            <Plus size={12} weight="bold" />
            参加者を追加
          </button>
        ) : null}
      </div>
      {participants.map((p, i) => (
        <TabsContent key={p.order_index} value={String(i)} className="pt-4">
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
