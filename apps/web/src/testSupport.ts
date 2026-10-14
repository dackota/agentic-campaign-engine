import { vi } from "vitest";
import type { Campaign, Me } from "./api";

/** A signed-in user; the subject is what `created_by` is compared with. */
export const me = (...roles: string[]): Me => ({
  subject: "user-me",
  email: "me@demo.example",
  team: "demand-gen",
  roles,
});

/** A campaign as the API sends it; each test overrides only what it is about. */
export function campaign(overrides: Partial<Campaign> = {}): Campaign {
  return {
    id: "c1",
    report: "Volt Typhoon targets edge routers\nActors exploit VPN appliances.",
    team: "demand-gen",
    created_by: "user-someone-else",
    created_at: "2026-10-11T10:00:00Z",
    status: "awaiting_approval",
    draft: null,
    failure_reason: null,
    receipt: null,
    workflow: null,
    workflow_version: null,
    steps: [],
    budget_usd: null,
    cost: { input_tokens: 0, output_tokens: 0, total_tokens: 0, cost_usd: 0, steps: [] },
    edges: [],
    ab_result: { status: "no_decision", winner: null, confidence: null },
    scores: [],
    ...overrides,
  };
}

/** One request the screen made to the API. */
export interface ApiCall {
  method: string;
  path: string;
  body: unknown;
}

/** What a route answers: a JSON body, a whole Response, or a function of the request body. */
export type Route = Response | ((body: unknown) => unknown) | readonly unknown[] | Record<string, unknown>;

/** Stand in for the API: routes are keyed "METHOD /path" (without /api). Returns the calls made. */
export function stubApi(routes: Record<string, Route>): ApiCall[] {
  const calls: ApiCall[] = [];
  vi.stubGlobal("fetch", async (input: string, init?: RequestInit): Promise<Response> => {
    const url = new URL(input, "http://localhost");
    const method = init?.method ?? "GET";
    const path = url.pathname.replace(/^\/api/, "");
    const body = typeof init?.body === "string" ? (JSON.parse(init.body) as unknown) : undefined;
    calls.push({ method, path, body });
    const route = routes[`${method} ${path}`];
    if (route === undefined) return new Response("no such route", { status: 404 });
    const answer = typeof route === "function" ? (route as (b: unknown) => unknown)(body) : route;
    return answer instanceof Response ? answer : Response.json(answer);
  });
  return calls;
}
