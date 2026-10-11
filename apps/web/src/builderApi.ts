import { fetchJson } from "./api";
import type { Workflow } from "./workflow.gen";

export interface Rejection {
  rule: string;
  message: string;
}

function isRejection(value: unknown): value is Rejection {
  if (typeof value !== "object" || value === null) return false;
  const r = value as Record<string, unknown>;
  return typeof r.rule === "string" && typeof r.message === "string";
}

const jsonPost = (workflow: Workflow): RequestInit => ({
  method: "POST",
  headers: { "content-type": "application/json" },
  body: JSON.stringify(workflow),
});

/** The API's own checks, run without saving: the same schema and rules as a save. */
export async function validateWorkflow(workflow: Workflow): Promise<Rejection[]> {
  const body = await fetchJson("/workflows/validate", jsonPost(workflow));
  const rejections = (body as { rejections?: unknown } | null)?.rejections;
  if (!Array.isArray(rejections) || !rejections.every(isRejection)) {
    throw new Error("the API returned an unexpected validation result");
  }
  return rejections;
}

export async function saveWorkflow(name: string, workflow: Workflow): Promise<number> {
  const body = await fetchJson(`/workflows/${name}/versions`, jsonPost(workflow));
  const version = (body as { version?: unknown } | null)?.version;
  if (typeof version !== "number") throw new Error("the API returned an unexpected saved version");
  return version;
}

/** Saved version numbers of a workflow, newest first. */
export async function listVersions(name: string): Promise<number[]> {
  const body = await fetchJson(`/workflows/${name}/versions`);
  if (!Array.isArray(body)) throw new Error("the API returned an unexpected version list");
  return body.map((v: unknown) => {
    const version = (v as { version?: unknown } | null)?.version;
    if (typeof version !== "number") throw new Error("the API returned an unexpected version");
    return version;
  });
}
