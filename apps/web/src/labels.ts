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
export const stepLabel = (id: string): string => STEP_LABELS[id] ?? humanize(id);
export const workflowLabel = (name: string): string => WORKFLOW_LABELS[name] ?? humanize(name);
