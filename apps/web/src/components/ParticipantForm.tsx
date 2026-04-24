"use client";

import { X } from "@phosphor-icons/react/dist/ssr";
import type { ParticipantFormInput } from "@/lib/schemas/planForm";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

type Props = {
  value: ParticipantFormInput;
  onChange: (next: ParticipantFormInput) => void;
  onAddTag: (tag: string) => void;
  onRemoveTag: (tag: string) => void;
};

/**
 * 単一参加者の入力フォーム。display_name / wishes_text / tags を扱う。
 * アバターの色指定は将来追加（今は受け取った値を表示するのみ）。
 */
export function ParticipantForm({ value, onChange, onAddTag, onRemoveTag }: Props) {
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-2">
        <Label htmlFor={`name-${value.order_index}`}>名前</Label>
        <Input
          id={`name-${value.order_index}`}
          value={value.display_name}
          onChange={(e) => onChange({ ...value, display_name: e.target.value })}
          maxLength={30}
          placeholder="さとし"
        />
      </div>
      <div className="flex flex-col gap-2">
        <Label htmlFor={`wishes-${value.order_index}`}>この旅で叶えたいこと</Label>
        <textarea
          id={`wishes-${value.order_index}`}
          className="min-h-[80px] resize-y rounded-md border border-[color:var(--color-border)] bg-[color:var(--color-surface)] px-3 py-2 text-sm"
          value={value.wishes_text}
          onChange={(e) => onChange({ ...value, wishes_text: e.target.value })}
          maxLength={500}
          placeholder="温泉でゆっくりしたい、美味しいご飯を食べたい"
        />
      </div>
      <div className="flex flex-col gap-2">
        <Label>タグ（雰囲気）</Label>
        <div className="flex flex-wrap items-center gap-2">
          {value.tags.map((tag) => (
            <span
              key={tag}
              className="inline-flex items-center gap-1 rounded-full bg-[color:var(--color-primary)]/10 px-2 py-1 text-xs text-[color:var(--color-primary)]"
            >
              {tag}
              <button
                type="button"
                onClick={() => onRemoveTag(tag)}
                className="rounded-full hover:bg-[color:var(--color-primary)]/20"
                aria-label={`${tag} を削除`}
              >
                <X size={12} weight="bold" />
              </button>
            </span>
          ))}
          <TagInput onAdd={onAddTag} />
        </div>
      </div>
    </div>
  );
}

function TagInput({ onAdd }: { onAdd: (tag: string) => void }) {
  return (
    <input
      type="text"
      placeholder="+ タグ追加（Enter 確定）"
      className="min-w-[160px] rounded-full bg-transparent px-2 py-1 text-xs text-[color:var(--color-text-secondary)] outline-none placeholder:text-[color:var(--color-text-tertiary)]"
      onKeyDown={(e) => {
        if (e.key !== "Enter") return;
        e.preventDefault();
        const v = e.currentTarget.value.trim();
        if (v.length === 0) return;
        onAdd(v);
        e.currentTarget.value = "";
      }}
    />
  );
}
