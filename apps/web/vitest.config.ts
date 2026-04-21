import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "happy-dom",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    // Next.js App Router の client/server 境界はここでは検証しない。
    // transit.ts 単体の挙動にフォーカスする。
  },
});
