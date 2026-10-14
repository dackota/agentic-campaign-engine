import { accessToken } from "./auth";
import type { WorkflowEdge, WorkflowStep } from "./workflow.gen";

export interface EmailDraft {
  subject: string;
  preheader: string;
  body: string;
  call_to_action: string;
}

export const STATUSES = [
  "drafting",
  "awaiting_approval",
  "sending",
  "sent",
  "failed",
  "retrying",
  "finished",
  "budget_paused",
] as const;
export type CampaignStatus = (typeof STATUSES)[number];

/** The A/B test's call: a winner with its confidence (0 to 1), or no decision yet. */
export interface AbResult {
  status: "winner" | "no_decision";
  winner: string | null;
  confidence: number | null;
}

/** The judge's score for one asset (1 to 5) and why. */
export interface AssetScore {
  step: string;
  score: number;
  reason: string;
}

export const MAX_SCORE = 5;

function isScore(value: unknown): value is AssetScore {
  if (typeof value !== "object" || value === null) return false;
  const s = value as Record<string, unknown>;
  return typeof s.step === "string" && typeof s.score === "number" && typeof s.reason === "string";
}

export interface Campaign {
  id: string;
  report: string;
  team: string;
  created_by: string;
  status: CampaignStatus;
  draft: EmailDraft | null;
  failure_reason: string | null;
  receipt: string | null;
  /** The saved workflow the run pinned; null for the default workflow. */
  workflow: string | null;
  workflow_version: number | null;
  /** The pinned workflow's steps, in run order. */
  steps: WorkflowStep[];
  /** What the run may spend on models, in dollars; null is no limit. */
  budget_usd: number | null;
  cost: CampaignCost;
  /** The pinned workflow's edges, for drawing the graph. */
  edges: WorkflowEdge[];
  ab_result: AbResult;
  /** What the judge scored each asset. */
  scores: AssetScore[];
}

function isAbResult(value: unknown): value is AbResult {
  if (typeof value !== "object" || value === null) return false;
  const r = value as Record<string, unknown>;
  return (
    (r.status === "winner" || r.status === "no_decision") &&
    (r.winner === null || typeof r.winner === "string") &&
    (r.confidence === null || typeof r.confidence === "number")
  );
}

export interface Usage {
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  cost_usd: number;
}

export interface StepCost extends Usage {
  step: string;
  model: string;
}

/** Tokens and cost in total, and per agent step. */
export interface CampaignCost extends Usage {
  steps: StepCost[];
}

function isUsage(value: unknown): value is Usage {
  if (typeof value !== "object" || value === null) return false;
  const u = value as Record<string, unknown>;
  return (
    typeof u.input_tokens === "number" &&
    typeof u.output_tokens === "number" &&
    typeof u.total_tokens === "number" &&
    typeof u.cost_usd === "number"
  );
}

function isStepCost(value: unknown): value is StepCost {
  if (!isUsage(value)) return false;
  const s = value as unknown as Record<string, unknown>;
  return typeof s.step === "string" && typeof s.model === "string";
}

function isCost(value: unknown): value is CampaignCost {
  if (!isUsage(value)) return false;
  const steps = (value as unknown as Record<string, unknown>).steps;
  return Array.isArray(steps) && steps.every(isStepCost);
}

function isStep(value: unknown): value is WorkflowStep {
  if (typeof value !== "object" || value === null) return false;
  const s = value as Record<string, unknown>;
  return typeof s.id === "string" && typeof s.kind === "string";
}

function isCampaign(value: unknown): value is Campaign {
  if (typeof value !== "object" || value === null) return false;
  const c = value as Record<string, unknown>;
  return (
    typeof c.id === "string" &&
    typeof c.report === "string" &&
    typeof c.team === "string" &&
    typeof c.created_by === "string" &&
    typeof c.status === "string" &&
    (STATUSES as readonly string[]).includes(c.status) &&
    (c.draft === null || (typeof c.draft === "object" && c.draft !== null)) &&
    (c.failure_reason === null || typeof c.failure_reason === "string") &&
    (c.receipt === null || typeof c.receipt === "string") &&
    (c.workflow === null || typeof c.workflow === "string") &&
    (c.workflow_version === null || typeof c.workflow_version === "number") &&
    Array.isArray(c.steps) &&
    c.steps.every(isStep) &&
    (c.budget_usd === null || typeof c.budget_usd === "number") &&
    isCost(c.cost) &&
    Array.isArray(c.edges) &&
    isAbResult(c.ab_result) &&
    Array.isArray(c.scores) &&
    c.scores.every(isScore)
  );
}

/** Thrown on a 401, so the screen can send the user back to sign in. */
export class SignedOutError extends Error {}

export async function fetchJson(path: string, init?: RequestInit): Promise<unknown> {
  const headers = new Headers(init?.headers);
  const token = accessToken();
  if (token) headers.set("authorization", `Bearer ${token}`);
  const response = await fetch(`/api${path}`, { ...init, headers });
  if (response.status === 401) throw new SignedOutError("sign in again");
  if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
  return response.json();
}

async function request(path: string, init?: RequestInit): Promise<Campaign> {
  const body = await fetchJson(path, init);
  if (!isCampaign(body)) throw new Error("the API returned an unexpected campaign shape");
  return body;
}

export async function listCampaigns(): Promise<Campaign[]> {
  const body = await fetchJson("/campaigns");
  if (!Array.isArray(body) || !body.every(isCampaign)) {
    throw new Error("the API returned an unexpected campaign list");
  }
  return body;
}

export interface Me {
  subject: string;
  email: string;
  team: string | null;
  roles: string[];
}

function isMe(value: unknown): value is Me {
  if (typeof value !== "object" || value === null) return false;
  const m = value as Record<string, unknown>;
  return (
    typeof m.subject === "string" &&
    typeof m.email === "string" &&
    (m.team === null || typeof m.team === "string") &&
    Array.isArray(m.roles) &&
    m.roles.every((r) => typeof r === "string")
  );
}

export async function getMe(): Promise<Me> {
  const body = await fetchJson("/me");
  if (!isMe(body)) throw new Error("the API returned an unexpected user shape");
  return body;
}

/** The names of the saved workflows, for the new-campaign picker. */
export async function listWorkflows(): Promise<string[]> {
  const body = await fetchJson("/workflows");
  if (!Array.isArray(body) || !body.every((n) => typeof n === "string")) {
    throw new Error("the API returned an unexpected workflow list");
  }
  return body;
}

/** Start a campaign; `workflow` names a saved workflow, empty runs the default one.
 * `budgetUsd` caps what the run spends on models; null is no limit. */
export function createCampaign(
  report: string,
  workflow = "",
  budgetUsd: number | null = null,
): Promise<Campaign> {
  const name = workflow.trim();
  return request("/campaigns", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      report,
      ...(name ? { workflow: name } : {}),
      ...(budgetUsd === null ? {} : { budget_usd: budgetUsd }),
    }),
  });
}

/** Set a new budget; a run paused at its budget goes on. */
export function raiseBudget(id: string, budgetUsd: number): Promise<Campaign> {
  return request(`/campaigns/${id}/budget`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ budget_usd: budgetUsd }),
  });
}

export function getCampaign(id: string): Promise<Campaign> {
  return request(`/campaigns/${id}`);
}

export function approveCampaign(id: string): Promise<Campaign> {
  return request(`/campaigns/${id}/approve`, { method: "POST" });
}

/** The retry-step action: re-run the step that stopped a failed run. */
export function retryCampaign(id: string): Promise<Campaign> {
  return request(`/campaigns/${id}/retry`, { method: "POST" });
}

/** A URL the browser loads itself (an iframe, an EventSource), so it cannot send the
 * Authorization header: the API also takes the token as the `access_token` parameter. */
export function withToken(path: string, extra: Record<string, string> = {}): string {
  const query = new URLSearchParams({ ...extra, access_token: accessToken() ?? "" });
  return `/api${path}?${query}`;
}

export function previewUrl(id: string): string {
  return withToken(`/campaigns/${id}/preview`);
}

export interface RunEvent {
  seq: number;
  step: string;
  status: string;
  reason: string | null;
  /** The tokens an agent step used, on its succeeded event. */
  tokens: number | null;
}

const RUN_STEP = "run";
const RUN_FINAL_STATUSES = ["awaiting_approval", "failed", "sent", "finished", "budget_paused"];

export function isFinalEvent(event: RunEvent): boolean {
  return event.step === RUN_STEP && RUN_FINAL_STATUSES.includes(event.status);
}

function isRunEvent(value: unknown): value is RunEvent {
  if (typeof value !== "object" || value === null) return false;
  const e = value as Record<string, unknown>;
  return (
    typeof e.seq === "number" &&
    typeof e.step === "string" &&
    typeof e.status === "string" &&
    (e.reason === null || typeof e.reason === "string") &&
    (e.tokens === null || typeof e.tokens === "number")
  );
}

/** Follow a run's event stream from the event after `afterSeq`; close it after the final
 * event. Returns a stop function. */
export function watchRun(
  id: string,
  afterSeq: number,
  onEvent: (event: RunEvent) => void,
  onError: (message: string) => void,
): () => void {
  const source = new EventSource(
    withToken(`/campaigns/${id}/events`, { after: String(afterSeq) }),
  );
  source.addEventListener("step", (message) => {
    let parsed: unknown;
    try {
      parsed = JSON.parse((message as MessageEvent<string>).data);
    } catch (e) {
      console.error("run event was not JSON", e);
      parsed = null;
    }
    if (!isRunEvent(parsed)) {
      source.close();
      onError("the API sent an unexpected run event");
      return;
    }
    onEvent(parsed);
    if (isFinalEvent(parsed)) source.close();
  });
  source.onerror = () => {
    // CONNECTING means the browser is retrying from the last event id; CLOSED means it gave up.
    if (source.readyState !== EventSource.CLOSED) return;
    onError("lost the live run status; reload to see the latest");
  };
  // A dropped connection is retried by the browser, resuming from the last event id.
  return () => source.close();
}

/** An alert Grafana raised that has not resolved yet. */
export interface FiringAlert {
  name: string;
  summary: string;
  fired_at: string;
}

function isFiringAlert(value: unknown): value is FiringAlert {
  if (typeof value !== "object" || value === null) return false;
  const a = value as Record<string, unknown>;
  return (
    typeof a.name === "string" && typeof a.summary === "string" && typeof a.fired_at === "string"
  );
}

/** The alerts firing now, for the banner. */
export async function listAlerts(): Promise<FiringAlert[]> {
  const body = await fetchJson("/alerts");
  if (!Array.isArray(body) || !body.every(isFiringAlert)) {
    throw new Error("the API returned an unexpected alert shape");
  }
  return body;
}
