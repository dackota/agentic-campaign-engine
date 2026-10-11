import { accessToken } from "./auth";
import type { WorkflowEdge, WorkflowStep } from "./workflow.gen";

export interface EmailDraft {
  subject: string;
  preheader: string;
  body: string;
  call_to_action: string;
}

const STATUSES = [
  "drafting",
  "awaiting_approval",
  "sending",
  "sent",
  "failed",
  "retrying",
  "finished",
] as const;
type CampaignStatus = (typeof STATUSES)[number];

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
  /** The pinned workflow's edges, for drawing the graph. */
  edges: WorkflowEdge[];
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
    Array.isArray(c.edges)
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

/** Start a campaign; `workflow` names a saved workflow, empty runs the default one. */
export function createCampaign(report: string, workflow = ""): Promise<Campaign> {
  const name = workflow.trim();
  return request("/campaigns", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(name ? { report, workflow: name } : { report }),
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
function withToken(path: string, extra: Record<string, string> = {}): string {
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
const RUN_FINAL_STATUSES = ["awaiting_approval", "failed", "sent", "finished"];

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
