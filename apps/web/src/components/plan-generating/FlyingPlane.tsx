"use client";

import { useEffect, useRef, useState } from "react";
import { AirplaneInFlight } from "@phosphor-icons/react/dist/ssr";
import { motion } from "framer-motion";

type Variant = "flying" | "landed" | "error";

type Props = {
  variant?: Variant;
  /** 0〜1 の進捗。飛行機の水平位置に反映される。 */
  progress?: number;
  /** インタラクティブモード（タップ / Space で浮上、重力で落下）。
   *  variant が "flying" のときだけ有効。 */
  interactive?: boolean;
};

/**
 * 1.6 プラン生成中の中央演出。
 * 1.5 で滑走路を走った飛行機が、ここで空を飛び、1.7 で目的地に着くストーリー。
 *
 * variant=flying かつ interactive のとき、ユーザがタップ / Space で
 * 飛行機を浮上させられる「軽量ミニゲーム」モードになる。衝突判定や
 * スコアはなく、雲を縫って遊ぶだけの「触れる演出」。
 */
export function FlyingPlane({
  variant = "flying",
  progress = 0,
  interactive = false,
}: Props) {
  if (interactive && variant === "flying") {
    return <InteractivePlane progress={progress} />;
  }
  return <AutoPlane variant={variant} progress={progress} />;
}

/* ───────────── 自動演出（既存） ───────────── */

function AutoPlane({
  variant,
  progress,
}: {
  variant: Variant;
  progress: number;
}) {
  const isFlying = variant === "flying";
  const isLanded = variant === "landed";
  const isError = variant === "error";

  const clamped = Math.max(0, Math.min(1, progress));
  const x = isError
    ? "10%"
    : isLanded
      ? "calc(100% - 64px)"
      : `${5 + clamped * (95 - 5 - 8)}%`;

  return (
    <div className="relative h-36 w-full overflow-hidden" aria-hidden>
      <span
        className="absolute inset-x-2 top-1/2 h-px -translate-y-1/2 opacity-50"
        style={{
          background:
            "repeating-linear-gradient(90deg, var(--color-accent) 0 12px, transparent 12px 24px)",
        }}
      />
      <motion.span
        className="absolute left-0 top-6 h-2.5 w-2/5 rounded-full bg-[color:var(--color-text-tertiary)] opacity-15"
        animate={isFlying ? { x: ["-60%", "180%"] } : { x: "0%" }}
        transition={{ duration: 22, repeat: isFlying ? Infinity : 0, ease: "linear" }}
      />
      <motion.span
        className="absolute right-0 bottom-7 h-2 w-1/3 rounded-full bg-[color:var(--color-text-tertiary)] opacity-25"
        animate={isFlying ? { x: ["120%", "-180%"] } : { x: "0%" }}
        transition={{ duration: 14, repeat: isFlying ? Infinity : 0, ease: "linear" }}
      />
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

/* ───────────── インタラクティブ（軽量ミニゲーム） ───────────── */

const GRAVITY = 0.4; // px/frame²
const LIFT_VELOCITY = -6; // 浮上時の瞬時 velocity
const MAX_Y_OFFSET = 50; // 中央 y からの上下クランプ (px)

function InteractivePlane({ progress }: { progress: number }) {
  const [yPx, setYPx] = useState(0);
  const velocityRef = useRef(0);

  // 物理シミュレーション（requestAnimationFrame）
  useEffect(() => {
    let rafId = 0;
    const tick = () => {
      velocityRef.current += GRAVITY;
      setYPx((y) => {
        let next = y + velocityRef.current;
        if (next > MAX_Y_OFFSET) {
          next = MAX_Y_OFFSET;
          velocityRef.current = 0;
        } else if (next < -MAX_Y_OFFSET) {
          next = -MAX_Y_OFFSET;
          velocityRef.current = 0;
        }
        return next;
      });
      rafId = requestAnimationFrame(tick);
    };
    rafId = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafId);
  }, []);

  const lift = () => {
    velocityRef.current = LIFT_VELOCITY;
  };

  // Space / ArrowUp で浮上
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.code === "Space" || e.code === "ArrowUp") {
        e.preventDefault();
        lift();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const clamped = Math.max(0, Math.min(1, progress));
  const xPct = 5 + clamped * (95 - 5 - 8); // 5%〜82%
  const tiltDeg = Math.max(
    -25,
    Math.min(25, velocityRef.current * 4),
  );

  return (
    <div
      className="relative h-36 w-full cursor-pointer touch-none select-none overflow-hidden rounded-md"
      onPointerDown={(e) => {
        e.preventDefault();
        lift();
      }}
      role="button"
      aria-label="飛行機を浮上させる（タップ または Space キー）"
      tabIndex={0}
    >
      {/* 軌跡破線 */}
      <span
        aria-hidden
        className="absolute inset-x-2 top-1/2 h-px -translate-y-1/2 opacity-50"
        style={{
          background:
            "repeating-linear-gradient(90deg, var(--color-accent) 0 12px, transparent 12px 24px)",
        }}
      />

      {/* 雲 (Framer Motion で軽量に) */}
      <motion.span
        aria-hidden
        className="absolute left-0 top-6 h-2.5 w-2/5 rounded-full bg-[color:var(--color-text-tertiary)] opacity-15"
        animate={{ x: ["-60%", "180%"] }}
        transition={{ duration: 22, repeat: Infinity, ease: "linear" }}
      />
      <motion.span
        aria-hidden
        className="absolute right-0 bottom-7 h-2 w-1/3 rounded-full bg-[color:var(--color-text-tertiary)] opacity-25"
        animate={{ x: ["120%", "-180%"] }}
        transition={{ duration: 14, repeat: Infinity, ease: "linear" }}
      />

      {/* 飛行機: x は progress、y はインタラクティブ state、rotate は velocity */}
      <span
        aria-hidden
        className="absolute text-[color:var(--color-primary)]"
        style={{
          left: `${xPct}%`,
          top: `calc(50% + ${yPx}px)`,
          transform: `translate(-50%, -50%) rotate(${tiltDeg}deg)`,
          transition: "left 0.6s cubic-bezier(0.25,0.46,0.45,0.94)",
          willChange: "transform, top",
        }}
      >
        <AirplaneInFlight size={56} weight="duotone" />
      </span>
    </div>
  );
}
