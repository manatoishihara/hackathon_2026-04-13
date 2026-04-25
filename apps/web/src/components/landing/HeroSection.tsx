"use client";

import { CaretDown } from "@phosphor-icons/react/dist/ssr";
import { motion } from "framer-motion";

const easing = [0.25, 0.46, 0.45, 0.94] as const;

export function HeroSection() {
  return (
    <section className="relative flex h-screen flex-col items-center justify-center px-6 text-center">
      <motion.p
        initial={{ opacity: 0, y: -8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.7, delay: 0.1, ease: easing }}
        className="mb-10 text-xs font-medium tracking-[0.28em] text-[color:var(--color-text-secondary)]"
      >
        A JOURNAL FOR THE JOURNEY
      </motion.p>

      <motion.h1
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.95, delay: 0.25, ease: easing }}
        className="font-heading text-7xl font-medium leading-none tracking-[0.02em] text-[color:var(--color-text-primary)] sm:text-8xl lg:text-[140px]"
      >
        Routeful
      </motion.h1>

      <motion.p
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.9, delay: 0.55, ease: easing }}
        className="mt-12 max-w-md text-base leading-[1.95] text-[color:var(--color-text-primary)]"
      >
        みんなで 1 画面を囲んで、
        <span className="relative mx-1 inline-block">
          <span className="relative z-10">その場で合意する</span>
          <span
            aria-hidden
            className="absolute inset-x-0 bottom-0.5 z-0 h-2 bg-[color:var(--color-accent)] opacity-40"
          />
        </span>
        旅行計画。
      </motion.p>

      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 1.2, delay: 1.2 }}
        className="absolute bottom-12 flex flex-col items-center gap-3 text-[color:var(--color-text-secondary)]"
      >
        <span className="text-[10px] font-medium tracking-[0.28em]">SCROLL</span>
        <motion.span
          aria-hidden
          animate={{ y: [0, 6, 0] }}
          transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
          className="inline-flex"
        >
          <CaretDown size={18} weight="bold" />
        </motion.span>
      </motion.div>
    </section>
  );
}
