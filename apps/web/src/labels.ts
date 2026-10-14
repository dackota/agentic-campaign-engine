import type { CampaignStatus } from "./api.ts";
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

const WORKFLOW_LABELS: Record<string, string> = {
  "threat-report-to-campaign": "Threat report to campaign",
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
