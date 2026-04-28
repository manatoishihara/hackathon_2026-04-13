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

const SUGGESTED_TAGS = [
  "温泉",
  "和食",
  "洋食",
  "観光",
  "自然",
  "街歩き",
  "写真映え",
  "ゆったり派",
  "アクティブ派",
  "歴史",
  "グルメ",
  "夜景",
];

/**
 * 単一参加者の入力フォーム。display_name / wishes_text / tags を扱う。
 * タグはサジェスト（よく使う 12 個）から選ぶ + カスタム入力（Enter 確定）。
 */
export function ParticipantForm({ value, onChange, onAddTag, onRemoveTag }: Props) {
  return (
    <div className="flex flex-col gap-5">
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
          className="min-h-[96px] resize-y rounded-md border border-[color:var(--color-border)] bg-[color:var(--color-surface)] px-3 py-2 text-sm leading-relaxed text-[color:var(--color-text-primary)] placeholder:text-[color:var(--color-text-tertiary)] outline-none transition-[color,box-shadow,border-color] focus-visible:border-[color:var(--color-primary)] focus-visible:ring-3 focus-visible:ring-[color:var(--color-primary)]/30"
          value={value.wishes_text}
          onChange={(e) => onChange({ ...value, wishes_text: e.target.value })}
          maxLength={500}
          placeholder="温泉でゆっくりしたい、美味しいご飯を食べたい、駅ビルでお土産も見たい"
        />
      </div>
      <div className="flex flex-col gap-3">
        <Label>タグ（雰囲気）</Label>

        {value.tags.length > 0 ? (
          <div className="flex flex-wrap items-center gap-2">
            {value.tags.map((tag) => (
              <span
                key={tag}
                className="inline-flex items-center gap-1 rounded-full bg-[color:var(--color-primary)]/10 px-3 py-1 text-xs font-medium text-[color:var(--color-primary)]"
              >
                {tag}
                <button
                  type="button"
                  onClick={() => onRemoveTag(tag)}
                  className="rounded-full transition-colors hover:bg-[color:var(--color-primary)]/20"
                  aria-label={`${tag} を削除`}
                >
                  <X size={12} weight="bold" />
                </button>
              </span>
            ))}
          </div>
        ) : null}

        <div className="flex flex-col gap-2">
          <span className="text-[10px] font-medium tracking-[0.18em] text-[color:var(--color-text-tertiary)]">
            SUGGESTED
          </span>
          <div className="flex flex-wrap gap-1.5">
            {SUGGESTED_TAGS.filter((t) => !value.tags.includes(t)).map((tag) => (
              <button
                type="button"
                key={tag}
                onClick={() => onAddTag(tag)}
                className="rounded-full border border-[color:var(--color-border)] bg-[color:var(--color-surface)] px-3 py-1 text-xs text-[color:var(--color-text-secondary)] transition-colors hover:border-[color:var(--color-primary)] hover:bg-[color:var(--color-primary)]/5 hover:text-[color:var(--color-primary)]"
              >
                + {tag}
              </button>
            ))}
          </div>
        </div>

        <TagInput onAdd={onAddTag} existing={value.tags} />
      </div>
    </div>
  );
}

function TagInput({
  onAdd,
  existing,
}: {
  onAdd: (tag: string) => void;
  existing: string[];
}) {
  return (
    <input
      type="text"
      placeholder="その他のタグを入力して Enter"
      className="w-full rounded-md border border-[color:var(--color-border)] bg-[color:var(--color-surface)] px-3 py-2 text-sm text-[color:var(--color-text-primary)] placeholder:text-[color:var(--color-text-tertiary)] outline-none transition-[color,box-shadow,border-color] focus-visible:border-[color:var(--color-primary)] focus-visible:ring-3 focus-visible:ring-[color:var(--color-primary)]/30"
      onKeyDown={(e) => {
        if (e.key !== "Enter") return;
        e.preventDefault();
        const v = e.currentTarget.value.trim();
        if (v.length === 0) return;
        if (existing.includes(v)) {
          e.currentTarget.value = "";
          return;
        }
        onAdd(v);
        e.currentTarget.value = "";
      }}
    />
  );
}
