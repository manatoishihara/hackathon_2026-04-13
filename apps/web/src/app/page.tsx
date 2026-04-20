export default function Home() {
  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col justify-center gap-6 px-6 py-16">
      <p className="text-sm font-medium tracking-wide text-primary">
        Phase 0.1 / Monorepo Bootstrap
      </p>
      <h1 className="text-4xl font-bold leading-tight text-text-primary sm:text-5xl">
        Routeful
      </h1>
      <p className="max-w-xl text-base leading-relaxed text-text-secondary">
        対面で使う AI 旅行計画ツール。実在するスポット・正確な交通・根拠ある予算まで提示する、evidence-based
        プランニング体験。
      </p>
      <p className="text-xs text-text-tertiary">
        このページは骨格確認用のプレースホルダです。実装は Phase 1.4 のランディングページで差し替えます。
      </p>
    </main>
  );
}
