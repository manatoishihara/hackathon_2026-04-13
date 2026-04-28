import {
  CheckCircle,
  WarningCircle,
  Question,
} from "@phosphor-icons/react/dist/ssr";
import {
  getEvidenceBadgeInfo,
  type CostConfidence,
  type EvidenceBadgeInfo,
} from "shared-types";

type BaseProps = {
  confidence: CostConfidence;
  sources: readonly string[];
};

/**
 * `onClick` を渡すと `<button>`、渡さなければ `<span>`。
 * `onClick` を渡す側は `ariaLabelTitle` も必ず渡す（複数バッジ並列時の文脈不足を防ぐ）。
 * codex review 2 回目で discriminated union 化、fallback ラベルを廃止。
 */
type Props =
  | (BaseProps & {
      onClick: () => void;
      /** PlanItem.title 等。aria-label に「<title> の根拠の詳細を見る」として埋まる */
      ariaLabelTitle: string;
    })
  | (BaseProps & {
      onClick?: undefined;
      ariaLabelTitle?: undefined;
    });

/**
 * Evidence バッジ。PlanItem のコスト信頼度を色 + アイコン + ラベルで表現する。
 * `onClick` を渡すと button にレンダされ、クリックで詳細モーダルを開く想定。
 */
export function EvidenceBadge({ confidence, sources, onClick, ariaLabelTitle }: Props) {
  const info = getEvidenceBadgeInfo(confidence, sources);
  const Icon = resolveIcon(info);
  const className =
    "inline-flex items-center gap-1 rounded-full border border-current/20 bg-current/5 px-2 py-0.5 text-xs font-medium";

  if (onClick) {
    // discriminated union により onClick が truthy なら ariaLabelTitle は必須 string
    const label = `${ariaLabelTitle} の根拠の詳細を見る`;
    return (
      <button
        type="button"
        onClick={onClick}
        data-variant={info.variant}
        aria-label={label}
        style={{ color: `var(${info.colorToken})` }}
        className={`${className} cursor-pointer transition-shadow hover:ring-1 hover:ring-current/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-current/40`}
      >
        <Icon size={12} weight="fill" />
        {info.label}
      </button>
    );
  }

  return (
    <span
      data-variant={info.variant}
      style={{ color: `var(${info.colorToken})` }}
      className={className}
    >
      <Icon size={12} weight="fill" />
      {info.label}
    </span>
  );
}

function resolveIcon(info: EvidenceBadgeInfo) {
  switch (info.variant) {
    case "verified":
      return CheckCircle;
    case "estimated":
      return WarningCircle;
    case "unknown":
    default:
      return Question;
  }
}
