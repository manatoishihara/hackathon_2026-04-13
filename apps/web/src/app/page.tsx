import { Clock, MapTrifold, UsersThree } from "@phosphor-icons/react/dist/ssr";
import {
  FeatureSection,
  type Feature,
} from "@/components/landing/FeatureSection";
import { FloatingCTA } from "@/components/landing/FloatingCTA";
import { HeroSection } from "@/components/landing/HeroSection";

const features: Feature[] = [
  {
    number: "01",
    label: "PLANNING TOGETHER",
    title: "全員の希望を、1 つのプランに編む",
    description:
      "2〜5 人ぶんの希望を一度に入力でき、AI が全員の希望文を読み合わせて、誰か一人に偏らない配分を目指します。",
    icon: <UsersThree size={88} weight="duotone" />,
  },
  {
    number: "02",
    label: "EVIDENCE-BACKED PLACES",
    title: "実在の場所だけを使う",
    description:
      "提案されるスポットは Google Places で実在を確認したものだけ。各アイテムの営業時間・評価・出典をバッヂから 1 件ずつ確認できます。",
    icon: <MapTrifold size={88} weight="duotone" />,
  },
  {
    number: "03",
    label: "MEASURED ROUTING",
    title: "移動時間を実測して、時刻を組み立てる",
    description:
      "Google Maps で実際の経路と所要時間を取得し、それを含めて時刻を並べます。距離に応じて徒歩・電車・車を切り替えます。",
    icon: <Clock size={88} weight="duotone" />,
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
