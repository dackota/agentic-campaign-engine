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
