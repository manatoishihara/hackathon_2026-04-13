"use client";

import { AirplaneTakeoff } from "@phosphor-icons/react/dist/ssr";
import { motion } from "framer-motion";

type Props = {
  /** 0〜1 の入力完了率 */
  progress: number;
  /** 提出中なら離陸モーション（y 上昇 + フェード） */
  isSubmitting?: boolean;
};

const easing = [0.25, 0.46, 0.45, 0.94] as const;

/**
 * 1.5 希望入力画面のヘッダーで使う「飛行機 × 滑走路」進捗インジケータ。
 * フォームの埋まり率に応じて飛行機が左→右に進み、submit 時に離陸する。
 */
export function StepProgressRunway({ progress, isSubmitting = false }: Props) {
  const clamped = Math.max(0, Math.min(1, progress));
  const x = isSubmitting ? "calc(100% - 28px)" : `${clamped * (100 - 7)}%`;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-baseline justify-between">
        <span className="text-[10px] font-medium tracking-[0.28em] text-[color:var(--color-text-primary)]">
          STEP 1 · INPUT
        </span>
        <span className="text-[10px] font-medium tracking-[0.28em] text-[color:var(--color-text-tertiary)]">
          STEP 2 · GENERATE →
        </span>
      </div>
      <div className="relative h-10 w-full">
        <span
          aria-hidden
          className="absolute inset-x-0 top-1/2 h-px -translate-y-1/2 bg-[color:var(--color-border)]"
        />
        <span
          aria-hidden
          className="absolute inset-x-3 top-1/2 h-px -translate-y-1/2 opacity-60"
          style={{
            background:
              "repeating-linear-gradient(90deg, var(--color-accent) 0 14px, transparent 14px 28px)",
          }}
        />
        <motion.span
          aria-hidden
          animate={{
            x,
            y: isSubmitting ? -18 : 0,
            opacity: isSubmitting ? 0.35 : 1,
          }}
          transition={{
            x: { duration: 0.7, ease: easing },
            y: { duration: 0.6, ease: easing },
            opacity: { duration: 0.6, ease: easing },
          }}
          className="absolute top-1/2 -translate-y-1/2 text-[color:var(--color-primary)]"
        >
          <AirplaneTakeoff size={28} weight="duotone" />
        </motion.span>
      </div>
    </div>
  );
}
