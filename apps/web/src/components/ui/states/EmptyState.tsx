import type { ReactNode } from "react";

type Props = {
  icon?: ReactNode;
  title: string;
  description?: string;
  action?: ReactNode;
};

/**
 * 共通 Empty State。0 件のリスト / 未選択状態で使う。
 * frontend-design.md の「0 件 Empty State で画面が成立する」ルールを守るための基盤。
 */
export function EmptyState({ icon, title, description, action }: Props) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-[color:var(--color-border)] bg-[color:var(--color-surface)]/50 px-6 py-10 text-center">
      {icon ? <div className="text-[color:var(--color-text-tertiary)]">{icon}</div> : null}
      <div className="max-w-md space-y-1">
        <p className="font-medium text-[color:var(--color-text-primary)]">{title}</p>
        {description ? (
          <p className="text-sm text-[color:var(--color-text-secondary)]">{description}</p>
        ) : null}
      </div>
      {action}
    </div>
  );
}
