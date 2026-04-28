import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";

const zodRoot = resolve(__dirname, "./node_modules/zod");

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "happy-dom",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    server: {
      deps: {
        // @hookform/resolvers/zod は pnpm の isolation で `zod` / `zod/v4/core` を
        // 解決できないので inline + alias で apps/web 配下の zod に向ける
        inline: ["@hookform/resolvers"],
      },
    },
  },
  resolve: {
    alias: {
      "@": resolve(__dirname, "./src"),
      "zod/v4/core": resolve(zodRoot, "v4/core/index.js"),
      "zod/v4": resolve(zodRoot, "v4/index.js"),
      "zod/v3": resolve(zodRoot, "v3/index.js"),
      zod: resolve(zodRoot, "index.js"),
    },
  },
});
