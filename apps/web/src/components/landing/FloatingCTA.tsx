import Link from "next/link";
import { ArrowRight } from "@phosphor-icons/react/dist/ssr";

/**
 * 旅を計画する CTA。スクロール位置にかかわらず常に同じ位置に固定表示される。
 * 対面で囲んで使うため、画面下部・指で届きやすい右側に配置。
 */
export function FloatingCTA() {
  return (
    <Link
      href="/plan/new"
      className="fixed bottom-6 right-6 z-50 inline-flex items-center gap-2 rounded-full bg-[color:var(--color-primary)] px-6 py-3.5 text-base font-medium text-[color:var(--color-background)] shadow-[0_10px_28px_rgba(4,44,83,0.22)] transition hover:opacity-90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--color-primary)] sm:bottom-8 sm:right-8"
    >
      旅を計画する
      <ArrowRight size={18} weight="bold" />
    </Link>
  );
}
