import { act, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { AlertBanner } from "./AlertBanner";
import { stubApi } from "./testSupport";

const FIRING = { name: "gateway-failover", summary: "Model calls failed over to the backup provider", fired_at: "2026-10-11T10:00:00Z" };
const POLL_MS = 2000;

/** Let the banner's timers run `ms` and its reads settle. */
const wait = (ms: number) => act(() => vi.advanceTimersByTimeAsync(ms));
const banner = () => screen.queryByTestId("alert-banner");

test("the banner shows a fired alert and drops it when it resolves", async () => {
  vi.useFakeTimers();
  let alerts = [FIRING];
  stubApi({ "GET /alerts": () => alerts });
  render(<AlertBanner onSignedOut={() => {}} />);

  await wait(0);
  expect(banner()?.textContent).toContain("gateway-failover");
  expect(banner()?.textContent).toContain("Model calls failed over to the backup provider");

  alerts = [];
  await wait(POLL_MS);
  expect(banner()).toBeNull();
});

test("with no alert firing there is no banner", async () => {
  vi.useFakeTimers();
  stubApi({ "GET /alerts": [] });
  render(<AlertBanner onSignedOut={() => {}} />);
  await wait(0);
  expect(banner()).toBeNull();
});

test("an alert that fires later shows up on the next read", async () => {
  vi.useFakeTimers();
  let alerts: (typeof FIRING)[] = [];
  stubApi({ "GET /alerts": () => alerts });
  render(<AlertBanner onSignedOut={() => {}} />);
  await wait(0);
  expect(banner()).toBeNull();

  alerts = [FIRING];
  await wait(POLL_MS);
  expect(banner()?.textContent).toContain("gateway-failover");
});

test("when the alerts cannot be read the banner says so", async () => {
  vi.useFakeTimers();
  stubApi({ "GET /alerts": new Response("down", { status: 500 }) });
  render(<AlertBanner onSignedOut={() => {}} />);
  await wait(0);
  expect(banner()?.textContent).toContain("Alerts could not be read");
});

test("a signed-out answer sends the user back to sign in", async () => {
  vi.useFakeTimers();
  const onSignedOut = vi.fn();
  stubApi({ "GET /alerts": new Response("no", { status: 401 }) });
  render(<AlertBanner onSignedOut={onSignedOut} />);
  await wait(0);
  expect(onSignedOut).toHaveBeenCalledOnce();
});
