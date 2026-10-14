import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const apiPort = process.env.ACE_API_PORT ?? "8000";

export default defineConfig({
  plugins: [react()],
  // Unit tests and component tests share one run; jsdom serves the component ones.
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
    setupFiles: ["./src/test-setup.ts"],
  },
  server: {
    proxy: {
      "/api": {
        target: `http://127.0.0.1:${apiPort}`,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
