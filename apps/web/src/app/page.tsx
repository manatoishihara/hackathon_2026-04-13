import { Calendar, MapTrifold } from "@phosphor-icons/react/dist/ssr";
import {
  FeatureSection,
  type Feature,
} from "@/components/landing/FeatureSection";
import { FloatingCTA } from "@/components/landing/FloatingCTA";
import { HeroSection } from "@/components/landing/HeroSection";

const features: Feature[] = [
  {
    number: "01",
    label: "EVIDENCE-BASED PLACES",
    title: "実在するスポット だけを提案する",
    description:
      "Google PlacesのAPIを使って実際にある店や観光地のみを提案します。",
    icon: <MapTrifold size={88} weight="duotone" />,
  },
  {
    number: "02",
    label: "TIME-AWARE PLAN",
    title: "時間的に成立する 旅程を組む",
    description: "Google MapsのAPIを使って移動時間を計算しています。",
    icon: <Calendar size={88} weight="duotone" />,
  },
];

/**
 * ランディング (01)。エクシブ公式サイト風の "縦スクロールでセクションが切り替わる" 構成。
 * - Hero: 中央配置で Routeful + キャッチ + scroll down
 * - Feature 01〜03: 特徴を 1 セクション 1 つで段階的開示
 * - FloatingCTA: 「旅を計画する」を画面右下に固定、スクロールしても位置不動
 *
 * 上部の "ROUTEFUL" は absolute 配置（fixed ではない）。スクロールすれば消える。
 * Home は RSC、アニメ部分のみ landing/* で client 分離。
 */
export default function Home() {
  return (
    <main className="relative bg-[color:var(--color-background)]">
      <header className="absolute left-0 right-0 top-0 z-40 mx-auto flex max-w-6xl items-baseline justify-between px-6 pt-8">
        <span className="font-heading text-base font-medium tracking-[0.28em] text-[color:var(--color-text-primary)]">
          ROUTEFUL
        </span>
        <span className="hidden text-xs italic text-[color:var(--color-text-secondary)] sm:inline">
          — for face-to-face planning
        </span>
      </header>

      <HeroSection />
      {features.map((feature) => (
        <FeatureSection key={feature.number} feature={feature} />
      ))}

      <FloatingCTA />
    </main>
  );
}
