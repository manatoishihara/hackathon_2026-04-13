"use client";

import { AirplaneInFlight } from "@phosphor-icons/react/dist/ssr";
import { motion } from "framer-motion";

type Variant = "flying" | "landed" | "error";

type Props = {
  variant?: Variant;
  /** 0〜1 の進捗。飛行機の水平位置に反映される。 */
  progress?: number;
};

/**
 * 1.6 プラン生成中の中央演出。
 * 1.5 で滑走路を走った飛行機が、ここで空を飛び、1.7 で目的地に着く一連のストーリー。
 * 飛行機は progress に応じて左→右に進む。上下揺れと雲の流れで「飛んでいる感」を出す。
 */
export function FlyingPlane({ variant = "flying", progress = 0 }: Props) {
  const isFlying = variant === "flying";
  const isLanded = variant === "landed";
  const isError = variant === "error";

  const clamped = Math.max(0, Math.min(1, progress));
  const x = isError
    ? "10%"
    : isLanded
      ? "calc(100% - 64px)"
      : `${5 + clamped * (95 - 5 - 8)}%`; // 5%〜82% の間を移動

  return (
    <div className="relative h-36 w-full overflow-hidden" aria-hidden>
      {/* 軌跡の薄い破線 */}
      <span
        className="absolute inset-x-2 top-1/2 h-px -translate-y-1/2 opacity-50"
        style={{
          background:
            "repeating-linear-gradient(90deg, var(--color-accent) 0 12px, transparent 12px 24px)",
        }}
      />

      {/* 奥の雲（薄め、ゆっくり） */}
      <motion.span
        className="absolute left-0 top-6 h-2.5 w-2/5 rounded-full bg-[color:var(--color-text-tertiary)] opacity-15"
        animate={isFlying ? { x: ["-60%", "180%"] } : { x: "0%" }}
        transition={{ duration: 22, repeat: isFlying ? Infinity : 0, ease: "linear" }}
      />
      {/* 手前の雲（濃いめ、速め） */}
      <motion.span
        className="absolute right-0 bottom-7 h-2 w-1/3 rounded-full bg-[color:var(--color-text-tertiary)] opacity-25"
        animate={isFlying ? { x: ["120%", "-180%"] } : { x: "0%" }}
        transition={{ duration: 14, repeat: isFlying ? Infinity : 0, ease: "linear" }}
      />

      {/* 飛行機: x は progress に追従、y は上下揺れ */}
      <motion.div
        animate={{
          x,
          y: isError
            ? [0, -2, 0, 2, 0]
            : isLanded
              ? 0
              : [0, -5, 0, 4, 0],
          rotate: isError ? [-2, 2, -2] : 0,
        }}
        transition={{
          x: { duration: 1.6, ease: [0.25, 0.46, 0.45, 0.94] },
          y: {
            duration: isError ? 0.7 : isLanded ? 0.6 : 4,
            repeat: isLanded ? 0 : Infinity,
            ease: "easeInOut",
          },
          rotate: {
            duration: isError ? 0.7 : 0.6,
            repeat: isError ? Infinity : 0,
            ease: "easeInOut",
          },
        }}
        className={`absolute top-1/2 -translate-y-1/2 ${
          isError
            ? "text-[color:var(--color-danger)]"
            : "text-[color:var(--color-primary)]"
        }`}
      >
        <AirplaneInFlight size={56} weight="duotone" />
      </motion.div>
    </div>
  );
}
