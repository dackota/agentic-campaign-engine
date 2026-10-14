import { defineConfig } from "@playwright/test";
import base from "../playwright.config";

// Records the demo video on the fast stack: `make record-demo`. Not part of `make test`.
export default defineConfig({
  ...base,
  testDir: ".",
  timeout: 300_000,
  outputDir: "../test-results/demo",
  use: {
    ...base.use,
    viewport: { width: 1280, height: 720 },
    video: { mode: "on", size: { width: 1280, height: 720 } },
    launchOptions: { slowMo: 120 },
  },
});
