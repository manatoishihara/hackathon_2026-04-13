import { WarningCircle } from "@phosphor-icons/react/dist/ssr";

type Props = {
  title?: string;
  message: string;
  action?: { label: string; onClick: () => void };
};

/**
 * 共通エラー表示。API 失敗・データ取得失敗時に使う。
 * action を渡せば「もう一度試す」等のボタンを出す。
 */
export function ErrorState({ title = "エラーが発生しました", message, action }: Props) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-10 text-center">
      <WarningCircle size={32} weight="duotone" className="text-[color:var(--color-danger)]" />
      <div className="max-w-md space-y-1">
        <p className="font-medium text-[color:var(--color-text-primary)]">{title}</p>
        <p className="text-sm text-[color:var(--color-text-secondary)]">{message}</p>
      </div>
      {action ? (
        <button
          type="button"
          onClick={action.onClick}
          className="rounded-md border border-[color:var(--color-border)] bg-[color:var(--color-surface)] px-4 py-2 text-sm font-medium hover:opacity-80"
        >
          {action.label}
        </button>
      ) : null}
    </div>
  );
}
