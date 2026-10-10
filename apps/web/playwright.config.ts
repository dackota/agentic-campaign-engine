import { delimiter, resolve } from "node:path";
import { defineConfig } from "@playwright/test";

// Ports are overridable so several runs can share a machine.
const apiPort = process.env.ACE_API_PORT ?? "18080";
const webPort = process.env.ACE_WEB_PORT ?? "15173";
const dexPort = process.env.ACE_DEX_PORT ?? "15556";
const root = resolve(import.meta.dirname, "../..");
const pythonPath = [".", "apps/engine", "apps/api", "apps/worker", "services/fakes"]
  .map((p) => resolve(root, p))
  .join(delimiter);
const env = {
  ...process.env,
  ACE_API_PORT: apiPort,
  ACE_WEB_PORT: webPort,
  ACE_DEX_PORT: dexPort,
  // The harness starts Dex on this port; the web app signs in against it.
  VITE_OIDC_ISSUER: `http://127.0.0.1:${dexPort}/dex`,
  PYTHONPATH: pythonPath,
} as Record<string, string>;

const STACK_START_TIMEOUT_MS = 240_000;

export default defineConfig({
  testDir: "./e2e",
  use: { baseURL: `http://127.0.0.1:${webPort}` },
  webServer: [
    {
      // Fast depth: real Postgres, Dex, Temporal time-skipping server, scripted A2A agent.
      command: "uv run python -m tests.harness.serve",
      cwd: "../..",
      env,
      url: `http://127.0.0.1:${apiPort}/healthz`,
      timeout: STACK_START_TIMEOUT_MS,
      reuseExistingServer: false,
    },
    {
      command: `pnpm exec vite --host 127.0.0.1 --port ${webPort} --strictPort`,
      env,
      url: `http://127.0.0.1:${webPort}`,
      reuseExistingServer: false,
    },
  ],
});
