import { fetchJson, withToken } from "./api";

/** One asset waiting for the approver: a writer's output with the reviewer's flags. */
export interface InboxAsset {
  campaign_id: string;
  title: string;
  team: string;
  created_by: string;
  step: string;
  /** The API path that renders the asset; null when only its text can be shown. */
  preview_url: string | null;
  output: unknown;
  flags: ReviewFlag[];
  /** The judge's score (1 to 5) and reason; null when the asset was not judged. */
  score: number | null;
  score_reason: string | null;
}

export interface ReviewFlag {
  check: string;
  detail: string;
}

function isFlag(value: unknown): value is ReviewFlag {
  if (typeof value !== "object" || value === null) return false;
  const f = value as Record<string, unknown>;
  return typeof f.check === "string" && typeof f.detail === "string";
}

function isInboxAsset(value: unknown): value is InboxAsset {
  if (typeof value !== "object" || value === null) return false;
  const a = value as Record<string, unknown>;
  return (
    typeof a.campaign_id === "string" &&
    typeof a.title === "string" &&
    typeof a.step === "string" &&
    (a.preview_url === null || typeof a.preview_url === "string") &&
    (a.score === null || typeof a.score === "number") &&
    (a.score_reason === null || typeof a.score_reason === "string") &&
    Array.isArray(a.flags) &&
    a.flags.every(isFlag)
  );
}

export async function listInbox(): Promise<InboxAsset[]> {
  const body = await fetchJson("/inbox");
  if (!Array.isArray(body) || !body.every(isInboxAsset)) {
    throw new Error("the API returned an unexpected inbox");
  }
  return body;
}

export type Decision = "approve" | "reject";

/** Approve or reject one asset with a comment; a rejection sends it back to its writer. */
export async function decideAsset(
  asset: Pick<InboxAsset, "campaign_id" | "step">,
  decision: Decision,
  comment: string,
): Promise<void> {
  await fetchJson(`/campaigns/${asset.campaign_id}/assets/${asset.step}/${decision}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ comment }),
  });
}

/** The asset's preview URL for an iframe, which cannot send the Authorization header. */
export function assetPreviewSrc(path: string): string {
  return withToken(path);
}
