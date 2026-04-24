import { CircleNotch } from "@phosphor-icons/react/dist/ssr";

type Props = { message?: string };

/**
 * 共通ローディング表示。`useQuery` の `isPending` で出す。
 * デザイナーはここの className を触って見た目を調整してよい。
 */
export function LoadingState({ message = "読み込み中..." }: Props) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-10 text-[color:var(--color-text-secondary)]">
      <CircleNotch size={28} weight="bold" className="animate-spin" />
      <p className="text-sm">{message}</p>
    </div>
  );
}
