import type { AbResult, Campaign, CampaignStatus, Usage } from "./api.ts";
import type { StepKind } from "./workflow.gen.ts";

/** The one place ids become words a marketer reads. Ids not listed are made readable by `humanize`. */
const STEP_LABELS: Record<string, string> = {
  strategist: "Strategy",
  research: "Research",
  design: "Design",
  landing_page: "Landing page",
  social: "Social post",
  one_pager: "One-pager",
  email_writer: "Email",
  email_draft: "Email draft",
  judge: "Quality check",
  approval: "Approval",
  publish: "Publish",
};

const KIND_LABELS: Record<StepKind, string> = {
  agent: "AI step",
  render: "Render",
  approval: "Approval",
  publish: "Publish",
  wait: "Wait",
};

/** The standard saved workflow: the one the new-campaign form starts on. */
export const DEFAULT_WORKFLOW = "threat-report-to-campaign";

const WORKFLOW_LABELS: Record<string, string> = {
  [DEFAULT_WORKFLOW]: "Threat report to campaign",
};

/** "my_new-step" becomes "My new step". */
function humanize(id: string): string {
  const words = id.replace(/[_-]+/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export const kindLabel = (kind: StepKind): string => KIND_LABELS[kind];
/** Own keys only: an id like "constructor" must not read an inherited member. */
const named = (labels: Record<string, string>, id: string): string | undefined =>
  Object.hasOwn(labels, id) ? labels[id] : undefined;

export const stepLabel = (id: string): string => named(STEP_LABELS, id) ?? humanize(id);
export const workflowLabel = (name: string): string => named(WORKFLOW_LABELS, name) ?? humanize(name);

const FLAG_LABELS: Record<string, string> = {
  uncited_fact: "Uncited fact",
  banned_claim: "Banned claim",
  off_brand_word: "Off-brand word",
  length: "Wrong length",
};

/** The brand reviewer's check ids, as the words a marketer reads. */
export const flagLabel = (check: string): string => named(FLAG_LABELS, check) ?? humanize(check);

const KIND_DESCRIPTIONS: Record<StepKind, string> = {
  agent: "An AI writes or prepares something, like an email or a social post.",
  render: "Turns finished content into a ready-to-use file or page.",
  approval: "A person says yes before anything goes further.",
  publish: "Sends the approved content out.",
  wait: "Pauses the workflow for a set time.",
};

export const kindDescription = (kind: StepKind): string => KIND_DESCRIPTIONS[kind];

const STATUS_LABELS: Record<CampaignStatus, string> = {
  drafting: "Drafting",
  awaiting_approval: "Waiting for approval",
  sending: "Sending",
  sent: "Sent",
  failed: "Failed",
  retrying: "Retrying",
  finished: "Finished",
  budget_paused: "Paused at budget",
};

export const statusLabel = (status: CampaignStatus): string => STATUS_LABELS[status];

const NEXT_STEPS: Record<CampaignStatus, string> = {
  drafting: "The AI is writing the draft.",
  awaiting_approval: "Waiting for an approver.",
  sending: "Sending the approved campaign.",
  sent: "Sent. We are watching which version wins.",
  failed: "A step failed. An owner can retry it.",
  retrying: "Trying the failed step again.",
  finished: "All done.",
  budget_paused: "Paused at the budget. An owner can raise it to continue.",
};

/** The one sentence at the top of a campaign page: what happens next. */
export const nextStepText = (status: CampaignStatus): string => NEXT_STEPS[status];

const STEP_STATUS_LABELS: Record<string, string> = {
  started: "Running",
  succeeded: "Done",
  failed: "Failed",
  pending: "Waiting",
};

/** A step's run status as the word a marketer reads. */
export const stepStatusLabel = (status: string): string => named(STEP_STATUS_LABELS, status) ?? humanize(status);

const FAILED_STEP = /^step '([^']+)' failed(?: after (\d+) attempts?)?\b/;

/** A failed run's reason in plain words: the step's plain name and the attempts, never the raw error. */
export function failureText(reason: string | null): string {
  const found = reason ? FAILED_STEP.exec(reason) : null;
  if (!found) return "A step did not finish.";
  const attempts = Number(found[2]);
  const after = attempts ? ` after ${attempts} ${attempts === 1 ? "attempt" : "attempts"}` : "";
  return `The ${stepLabel(found[1])} step did not finish${after}.`;
}

const COST_DECIMALS = 4;

/** Money on a main screen: dollars and cents. */
export const dollarsText = (usd: number): string => `$${usd.toFixed(2)}`;

/** A dollar amount typed in a form, or null when the field is blank. */
export function dollarsOf(text: string): number | null {
  return text.trim() ? Number(text) : null;
}

/** Tokens and dollars, e.g. "3,000 tokens, $0.0162". */
export function costText(usage: Usage): string {
  return `${usage.total_tokens.toLocaleString("en-US")} tokens, $${usage.cost_usd.toFixed(COST_DECIMALS)}`;
}

/** The A/B call: "Version B won, 97% confident", or "No decision yet". */
export function abResultText(result: AbResult): string {
  if (result.status !== "winner" || result.confidence === null) return "No decision yet";
  return `Version ${result.winner} won, ${Math.floor(result.confidence * 100)}% confident`;
}

/** The list label for a campaign: the first line of its report. */
export function campaignTitle(campaign: Campaign): string {
  return campaign.report.split("\n", 1)[0] ?? campaign.id;
}
