export interface EmailDraft {
  subject: string;
  preheader: string;
  body: string;
  call_to_action: string;
}

export interface Campaign {
  id: string;
  report: string;
  status: "drafting" | "drafted" | "failed";
  draft: EmailDraft | null;
  failure_reason: string | null;
}

const STATUSES = ["drafting", "drafted", "failed"];

function isCampaign(value: unknown): value is Campaign {
  if (typeof value !== "object" || value === null) return false;
  const c = value as Record<string, unknown>;
  return (
    typeof c.id === "string" &&
    typeof c.report === "string" &&
    typeof c.status === "string" &&
    STATUSES.includes(c.status) &&
    (c.draft === null || (typeof c.draft === "object" && c.draft !== null)) &&
    (c.failure_reason === null || typeof c.failure_reason === "string")
  );
}

async function request(path: string, init?: RequestInit): Promise<Campaign> {
  const response = await fetch(`/api${path}`, init);
  if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
  const body: unknown = await response.json();
  if (!isCampaign(body)) throw new Error("the API returned an unexpected campaign shape");
  return body;
}

export function createCampaign(report: string): Promise<Campaign> {
  return request("/campaigns", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ report }),
  });
}

export function getCampaign(id: string): Promise<Campaign> {
  return request(`/campaigns/${id}`);
}

export interface RunEvent {
  seq: number;
  step: string;
  status: string;
  reason: string | null;
}

const RUN_STEP = "run";
const RUN_FINAL_STATUSES = ["drafted", "failed"];

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
    (e.reason === null || typeof e.reason === "string")
  );
}

/** Follow a run's event stream; close it after the final event. Returns a stop function. */
export function watchRun(
  id: string,
  onEvent: (event: RunEvent) => void,
  onError: (message: string) => void,
): () => void {
  const source = new EventSource(`/api/campaigns/${id}/events`);
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
