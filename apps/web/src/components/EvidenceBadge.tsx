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

type Props = {
  confidence: CostConfidence;
  sources: readonly string[];
};

/**
 * Evidence バッジ。PlanItem のコスト信頼度を色 + アイコン + ラベルで表現する。
 * ロジック（信頼度判定）は shared-types の `getEvidenceBadgeInfo`、
 * ここは見た目だけ。デザイナーはアイコンサイズ・形状・アニメを触ってよい。
 */
export function EvidenceBadge({ confidence, sources }: Props) {
  const info = getEvidenceBadgeInfo(confidence, sources);
  const Icon = resolveIcon(info);
  return (
    <span
      data-variant={info.variant}
      style={{ color: `var(${info.colorToken})` }}
      className="inline-flex items-center gap-1 rounded-full border border-current/20 bg-current/5 px-2 py-0.5 text-xs font-medium"
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
