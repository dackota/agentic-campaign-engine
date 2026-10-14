import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";
import { App } from "./App";
import { accessToken } from "./auth";
import type { Campaign, Me } from "./api";
import { campaign, me, stubApi, stubEventSource, type FakeStream } from "./testSupport";

const POLL_MS = 500;
const FINAL = { step: "run", status: "finished" };
const text = (id: string) => screen.getByTestId(id).textContent;

beforeEach(() => {
  sessionStorage.setItem("ace.access_token", "token");
  window.history.replaceState(null, "", "/");
});

/** The app as `user` sees it, opened on `path`; `server` is what the API holds, so a test can change it. */
function openApp(user: Me, server: { campaign: Campaign }, path: string, routes: Parameters<typeof stubApi>[0] = {}) {
  const streams = stubEventSource();
  const calls = stubApi({
    "GET /me": { ...user },
    "GET /alerts": [],
    "GET /campaigns": () => [server.campaign],
    [`GET /campaigns/${server.campaign.id}`]: () => server.campaign,
    [`GET /campaigns/${server.campaign.id}/preview`]: () => new Response("<h1>preview</h1>"),
    ...routes,
  });
  window.history.replaceState(null, "", path);
  render(<App />);
  return { streams, calls };
}
/** The nth stream the screen opens (effects run after the screen shows, so wait for it). */
const nthStream = async (streams: FakeStream[], n: number) => {
  await waitFor(() => expect(streams.length).toBeGreaterThanOrEqual(n));
  return streams[n - 1]!;
};

test("a failed run: the owner retries the step and the screen reaches Finished, with no Retry button", async () => {
  const server = { campaign: campaign({ status: "failed", failure_reason: "step 'writer' failed after 2 attempts" }) };
  const { streams } = openApp(me("owner"), server, "/campaigns/c1", {
    "POST /campaigns/c1/retry": () => (server.campaign = campaign({ status: "retrying" })),
  });

  // The run ended in failure, so its stream is done; only a retry opens a new one.
  const first = await nthStream(streams, 1);
  await act(async () => first.send({ seq: 4, step: "run", status: "failed" }));
  await userEvent.click(await screen.findByRole("button", { name: "Retry step" }));
  expect(await screen.findByText("Retrying")).toBeTruthy();
  server.campaign = campaign({ status: "finished" });
  const second = await nthStream(streams, 2);
  await act(async () => second.send({ seq: 9, ...FINAL }));

  expect(await screen.findByText("Finished")).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Retry step" })).toBeNull();
});

test("a run paused at its budget: the owner raises it and the run resumes to Finished with the new cost", async () => {
  const paused = campaign({ status: "budget_paused", budget_usd: 0.01, cost: { ...campaign().cost, cost_usd: 0.02 } });
  const server = { campaign: paused };
  const { streams, calls } = openApp(me("owner"), server, "/campaigns/c1", {
    "POST /campaigns/c1/budget": () => (server.campaign = { ...paused, status: "drafting", budget_usd: 1 }),
  });

  const first = await nthStream(streams, 1);
  await act(async () => first.send({ seq: 4, step: "run", status: "budget_paused" }));
  await userEvent.type(await screen.findByLabelText("New budget (USD)"), "1");
  await userEvent.click(screen.getByRole("button", { name: "Raise budget" }));
  await screen.findByText("Drafting");
  expect(calls.find((c) => c.path === "/campaigns/c1/budget")?.body).toEqual({ budget_usd: 1 });
  server.campaign = { ...paused, status: "finished", budget_usd: 1, cost: { ...paused.cost, cost_usd: 0.042 } };
  const second = await nthStream(streams, 2);
  await act(async () => second.send({ seq: 9, ...FINAL }));

  expect(await screen.findByText("Finished")).toBeTruthy();
  expect(text("run-cost")).toBe("$0.04");
  expect(text("run-budget")).toBe("$1.00");
});

test("an approval: Sending, then Sent with its receipt, then the A/B winner once the audience has engaged", async () => {
  const sent = campaign({ status: "sent", receipt: "mk-1" });
  const server = { campaign: campaign() };
  openApp(me("approver"), server, "/campaigns/c1", {
    "POST /campaigns/c1/approve": () => {
      server.campaign = sent;
      return campaign({ status: "sending" });
    },
  });
  const approve = await screen.findByRole("button", { name: "Approve" });
  // Testing Library's own waits hang under fake timers, so from here the test moves the clock and reads the screen.
  vi.useFakeTimers({ toFake: ["setTimeout"] });
  const wait = (ms: number) => act(() => vi.advanceTimersByTimeAsync(ms));

  fireEvent.click(approve);
  await wait(0);
  expect(text("run-status")).toBe("Sending");
  await wait(POLL_MS);
  expect(text("run-status")).toBe("Sent");
  expect(text("receipt")).toBe("mk-1");
  expect(text("ab-result")).toBe("No decision yet");

  server.campaign = { ...sent, ab_result: { status: "winner", winner: "A", confidence: 0.87 } };
  await wait(POLL_MS);
  expect(text("ab-result")).toBe("Version A won, 87% confident");

  // The call is made: the screen stops asking, so a later read does not change it.
  server.campaign = { ...sent, ab_result: { status: "winner", winner: "B", confidence: 0.6 } };
  await wait(POLL_MS);
  expect(text("ab-result")).toBe("Version A won, 87% confident");
});

test("a request answered 401 returns to the signed-out screen", async () => {
  const server = { campaign: campaign({ status: "failed" }) };
  openApp(me("owner"), server, "/campaigns/c1", {
    "POST /campaigns/c1/retry": new Response("expired", { status: 401 }),
  });

  await userEvent.click(await screen.findByRole("button", { name: "Retry step" }));

  expect(await screen.findByRole("button", { name: "Sign in" })).toBeTruthy();
  expect(screen.queryByTestId("run-status")).toBeNull();
  expect(accessToken()).toBeNull();
});

test("a sign-in the API no longer accepts shows the signed-out screen, not an error", async () => {
  openApp(me("owner"), { campaign: campaign() }, "/", { "GET /me": new Response("expired", { status: 401 }) });

  expect(await screen.findByRole("button", { name: "Sign in" })).toBeTruthy();
  expect(screen.queryByRole("alert")).toBeNull();
});

test("opening /campaigns/<id> directly shows that campaign", async () => {
  const server = { campaign: campaign({ id: "c9", report: "Salt Typhoon hits telcos\nDetails." }) };
  openApp(me("owner"), server, "/campaigns/c9");

  expect((await screen.findByRole("heading", { level: 1 })).textContent).toBe("Salt Typhoon hits telcos");
  expect(text("run-status")).toBe("Waiting for approval");
});
