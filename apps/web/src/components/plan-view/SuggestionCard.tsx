/**
 * 「SUGGESTION」カード。HTML モック準拠の Coral 背景。
 * Phase 2 で LLM 連携の本実装に置き換える予定。今は固定文言の placeholder。
 */
export function SuggestionCard() {
  return (
    <aside className="flex flex-col gap-2 rounded-md bg-[color:var(--color-accent)] p-4 text-[color:#4A1B0C]">
      <p className="text-[10px] font-medium tracking-[0.18em] opacity-70">
        SUGGESTION
      </p>
      <p className="font-heading text-sm font-medium leading-snug">
        この日にもう一カ所 加えるなら
      </p>
      <p className="text-xs leading-relaxed opacity-90">
        近くの寄り道スポットを LLM が提案します（Phase 2）。タップで採用、却下で次の候補に。
      </p>
      <span className="mt-1 inline-block w-fit border-b border-[#4A1B0C]/60 pb-0.5 text-[11px] font-medium opacity-70">
        Phase 2 で実装予定
      </span>
    </aside>
  );
}
