import Link from "next/link";
import {
  ArrowRight,
  Calendar,
  MapTrifold,
  ShieldCheck,
} from "@phosphor-icons/react/dist/ssr";

/**
 * ランディング (01)。主役 CTA は「旅を計画する」ボタン。
 * 下にサブとして 3 軸カード（実在スポット / 時間的に成立 / 根拠ある予算）。
 *
 * デザイナーは className / レイアウト / Motion を触ってよい。
 * - AI グラデ禁止・汎用ヒーロー禁止（frontend-design.md 参照）
 * - CTA が画面の主役になっているメリハリを維持
 */
export default function Home() {
  return (
    <main className="mx-auto flex min-h-screen max-w-5xl flex-col gap-12 px-6 py-16">
      <section className="flex flex-col gap-6">
        <p className="text-sm font-medium tracking-widest text-[color:var(--color-primary)]">
          ROUTEFUL
        </p>
        <h1 className="max-w-3xl text-4xl font-bold leading-tight text-[color:var(--color-text-primary)] sm:text-5xl">
          みんなで集まって 1 画面を囲む、
          <br className="hidden sm:block" />
          evidence-based な旅行計画。
        </h1>
        <p className="max-w-2xl text-base leading-relaxed text-[color:var(--color-text-secondary)]">
          LLM の意味理解と外部 API の構造化データを組み合わせて、
          <strong className="font-medium text-[color:var(--color-text-primary)]">
            実在し時間的に成立するプラン
          </strong>
          だけを提案します。対面で 2〜5 人で使う想定です。
        </p>
        <div className="flex flex-wrap items-center gap-3">
          <Link
            href="/plan/new"
            className="inline-flex items-center gap-2 rounded-md bg-[color:var(--color-primary)] px-6 py-3 text-base font-medium text-white shadow-sm transition hover:opacity-90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--color-primary)]"
          >
            旅を計画する
            <ArrowRight size={18} weight="bold" />
          </Link>
        </div>
      </section>
      <section className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <FeatureCard
          icon={<MapTrifold size={24} weight="duotone" />}
          title="実在するスポットだけ"
          description="Google Places で検証した店や観光地のみ提案。架空の名前は出しません。"
        />
        <FeatureCard
          icon={<Calendar size={24} weight="duotone" />}
          title="時間的に成立する"
          description="Google Maps の transit 情報で移動時間を計算。営業時間内か確認した上で組み立てます。"
        />
        <FeatureCard
          icon={<ShieldCheck size={24} weight="duotone" />}
          title="根拠ある予算"
          description="宿泊・食事・観光・交通のカテゴリごとに、推定値か検証値かを Evidence バッジで明示。"
        />
      </section>
    </main>
  );
}

function FeatureCard({
  icon,
  title,
  description,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
}) {
  return (
    <article className="flex flex-col gap-3 rounded-lg border border-[color:var(--color-border)] bg-[color:var(--color-surface)] p-5">
      <div className="text-[color:var(--color-primary)]">{icon}</div>
      <h2 className="text-base font-semibold text-[color:var(--color-text-primary)]">
        {title}
      </h2>
      <p className="text-sm leading-relaxed text-[color:var(--color-text-secondary)]">
        {description}
      </p>
    </article>
  );
}
