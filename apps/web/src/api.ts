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

async function request(path: string, init?: RequestInit): Promise<Campaign> {
  const response = await fetch(`/api${path}`, init);
  if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
  return (await response.json()) as Campaign;
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
