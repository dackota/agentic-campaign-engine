import { execFileSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import { delimiter, resolve } from "node:path";
import { defineConfig } from "@playwright/test";

// A port the OS has free now. The config loads synchronously, so a child node asks for it.
const FREE_PORT_SCRIPT =
  "const s = require('net').createServer().listen(0, '127.0.0.1', () => { console.log(s.address().port); s.close(); });";
const freePort = (): string => execFileSync(process.execPath, ["-e", FREE_PORT_SCRIPT], { encoding: "utf8" }).trim();
// Each port is free unless set: a fixed default clashed with port-forwards and other runs.
// Set on process.env, so the test workers, which load this file again, inherit the same ports.
process.env.ACE_API_PORT ??= freePort();
process.env.ACE_WEB_PORT ??= freePort();
process.env.ACE_DEX_PORT ??= freePort();
process.env.ACE_MARKETO_PORT ??= freePort();
const apiPort = process.env.ACE_API_PORT;
const webPort = process.env.ACE_WEB_PORT;
const dexPort = process.env.ACE_DEX_PORT;
const root = resolve(import.meta.dirname, "../..");
const pythonPath = [".", "apps/engine", "apps/api", "apps/worker", "services/fakes", "services/render", "services/mcp"]
  .map((p) => resolve(root, p))
  .join(delimiter);
const marketoPort = process.env.ACE_MARKETO_PORT;
// The alert-banner spec posts to the alert webhook with this token, so it is made fresh here
// (inherited by the test workers) and passed to the stack.
process.env.ACE_ALERT_WEBHOOK_TOKEN ??= randomBytes(24).toString("hex");
const alertToken = process.env.ACE_ALERT_WEBHOOK_TOKEN;
const env = {
  ...process.env,
  ACE_API_PORT: apiPort,
  ACE_WEB_PORT: webPort,
  ACE_DEX_PORT: dexPort,
  ACE_MARKETO_PORT: marketoPort,
  ACE_ALERT_WEBHOOK_TOKEN: alertToken,
  // The harness starts Dex on this port; the web app signs in against it.
  VITE_OIDC_ISSUER: `http://127.0.0.1:${dexPort}/dex`,
  PYTHONPATH: pythonPath,
} as Record<string, string>;

const STACK_START_TIMEOUT_MS = 240_000;
const STACK_STOP_TIMEOUT_MS = 30_000;

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
      // SIGTERM lets the stack remove its containers; the default SIGKILL leaves that to Ryuk.
      gracefulShutdown: { signal: "SIGTERM", timeout: STACK_STOP_TIMEOUT_MS },
    },
    {
      command: `pnpm exec vite --host 127.0.0.1 --port ${webPort} --strictPort`,
      env,
      url: `http://127.0.0.1:${webPort}`,
      reuseExistingServer: false,
    },
  ],
});
