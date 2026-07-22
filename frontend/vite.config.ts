import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const entry = mode === "live-research" ? "live-research" : "maitu";

  return {
    root: entry,
    base: `/${entry}/`,
    plugins: [react()],
    build: {
      outDir: `../dist/${entry}`,
      emptyOutDir: true,
    },
    server: {
      port: entry === "maitu" ? 5174 : 5175,
      proxy: {
        "/api": {
          target: "http://127.0.0.1:8000",
          changeOrigin: true,
        },
      },
    },
    test: {
      root: ".",
      environment: "jsdom",
      globals: true,
      setupFiles: "./src/test/setup.ts",
      css: true,
    },
  };
});
