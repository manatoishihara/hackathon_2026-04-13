"use client";

import { motion } from "framer-motion";
import type { ReactNode } from "react";

export type Feature = {
  number: string; // "01"
  label: string; // "EVIDENCE-BASED PLACES"
  title: string;
  description: string;
  icon: ReactNode;
};

const easing = [0.25, 0.46, 0.45, 0.94] as const;

export function FeatureSection({ feature }: { feature: Feature }) {
  return (
    <section className="relative flex min-h-screen items-center px-4 py-16 sm:px-6 sm:py-24">
      <div className="mx-auto grid w-full max-w-6xl grid-cols-12 items-center gap-8 lg:gap-16">
        <motion.div
          initial={{ opacity: 0, y: 28 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true, margin: "-15%" }}
          transition={{ duration: 0.75, ease: easing }}
          className="col-span-12 lg:col-span-6"
        >
          <p className="mb-6 flex items-center gap-3 text-xs font-medium tracking-[0.24em] text-[color:var(--color-text-secondary)]">
            <span className="font-mono text-sm text-[color:var(--color-accent)]">
              {feature.number}
            </span>
            <span
              aria-hidden
              className="inline-block h-px w-12 bg-[color:var(--color-accent)]"
            />
            {feature.label}
          </p>
          <h2 className="font-heading text-2xl leading-[1.45] text-[color:var(--color-text-primary)] sm:text-4xl lg:text-5xl">
            {feature.title}
          </h2>
          <p className="mt-6 max-w-md text-sm leading-[1.95] text-[color:var(--color-text-primary)] opacity-85 sm:mt-8 sm:text-base">
            {feature.description}
          </p>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, scale: 0.94 }}
          whileInView={{ opacity: 1, scale: 1 }}
          viewport={{ once: true, margin: "-15%" }}
          transition={{ duration: 0.95, delay: 0.15, ease: easing }}
          className="col-span-12 flex items-center justify-center lg:col-span-6"
        >
          <div className="relative flex aspect-square w-full max-w-md items-center justify-center overflow-hidden rounded-lg border border-[color:var(--color-border)] bg-[color:var(--color-surface)]">
            <span
              aria-hidden
              className="absolute left-0 top-0 h-1 w-16 bg-[color:var(--color-accent)]"
            />
            <div className="text-[color:var(--color-primary)]">{feature.icon}</div>
          </div>
        </motion.div>
      </div>
    </section>
  );
}
