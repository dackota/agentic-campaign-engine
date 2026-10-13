import { fetchJson } from "./api";

/** A called A/B winner kept for the agents, with the campaign it came from. */
export interface Learning {
  id: string;
  text: string;
  reason: string;
  campaign_id: string;
  campaign_title: string;
  created_at: string;
}

function isLearning(value: unknown): value is Learning {
  if (typeof value !== "object" || value === null) return false;
  const l = value as Record<string, unknown>;
  return (
    typeof l.id === "string" &&
    typeof l.text === "string" &&
    typeof l.reason === "string" &&
    typeof l.campaign_id === "string" &&
    typeof l.campaign_title === "string" &&
    typeof l.created_at === "string"
  );
}

export async function listLearnings(): Promise<Learning[]> {
  const body = await fetchJson("/learnings");
  if (!Array.isArray(body) || !body.every(isLearning)) {
    throw new Error("the API returned unexpected learnings");
  }
  return body;
}

/** Remove a bad learning, so the agents stop reading it. Approvers only. */
export async function deleteLearning(id: string): Promise<void> {
  await fetchJson(`/learnings/${id}`, { method: "DELETE" });
}
