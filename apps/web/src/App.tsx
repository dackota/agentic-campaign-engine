import { useState, type FormEvent } from "react";
import {
  approveCampaign,
  createCampaign,
  getCampaign,
  type Campaign,
  type EmailDraft,
  type RunEvent,
} from "./api";
import { messageOf } from "./messages";
import { useRunEvents } from "./useRunEvents";
import type { WorkflowStep } from "./workflow.gen";

const POLL_MS = 500;

const STEP_LABELS: Record<string, string> = { email_draft: "Email draft" };

const STATUS_LABELS: Record<Campaign["status"], string> = {
  drafting: "Drafting",
  awaiting_approval: "Waiting for approval",
  sending: "Sending",
  sent: "Sent",
  failed: "Failed",
  finished: "Finished",
};

const PENDING = "pending";

async function pollWhileSending(first: Campaign, onUpdate: (c: Campaign) => void): Promise<void> {
  let current = first;
  onUpdate(current);
  while (current.status === "sending") {
    await new Promise((resolve) => setTimeout(resolve, POLL_MS));
    current = await getCampaign(current.id);
    onUpdate(current);
  }
}

/** The pinned workflow's steps in run order, each with its latest status. */
function RunSteps({ dag, events }: { dag: WorkflowStep[]; events: Record<string, RunEvent> }) {
  return (
    <ul aria-label="Run steps">
      {dag.map((step) => (
        <li key={step.id} data-testid={`step-${step.id}`}>
          {STEP_LABELS[step.id] ?? step.id}: {events[step.id]?.status ?? PENDING}
        </li>
      ))}
    </ul>
  );
}

function DraftView({ draft }: { draft: EmailDraft }) {
  return (
    <section aria-label="Email draft">
      <h2 data-testid="draft-subject">{draft.subject}</h2>
      <p>{draft.preheader}</p>
      <pre data-testid="draft-body">{draft.body}</pre>
      <p>{draft.call_to_action}</p>
    </section>
  );
}

export function App() {
  const [report, setReport] = useState("");
  const [workflow, setWorkflow] = useState("");
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { steps, reset } = useRunEvents(campaign?.id, setCampaign, setError);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setCampaign(null);
    reset();
    try {
      setCampaign(await createCampaign(report, workflow));
    } catch (e) {
      setError(messageOf(e));
    }
  }

  async function approve(id: string) {
    setError(null);
    try {
      await pollWhileSending(await approveCampaign(id), setCampaign);
    } catch (e) {
      setError(messageOf(e));
    }
  }

  return (
    <main>
      <h1>New campaign</h1>
      <form onSubmit={submit}>
        <label>
          Threat report
          <textarea value={report} onChange={(e) => setReport(e.target.value)} rows={10} />
        </label>
        <label>
          Workflow
          <input
            value={workflow}
            onChange={(e) => setWorkflow(e.target.value)}
            placeholder="default"
          />
        </label>
        <button type="submit" disabled={!report.trim()}>
          Create campaign
        </button>
      </form>
      {error && <p role="alert">{error}</p>}
      {campaign && <RunSteps dag={campaign.steps} events={steps} />}
      {campaign?.status === "failed" && <p role="alert">{campaign.failure_reason}</p>}
      {campaign?.draft && <DraftView draft={campaign.draft} />}
      {campaign && campaign.status !== "drafting" && campaign.status !== "failed" && (
        <p>
          Status: <span data-testid="run-status">{STATUS_LABELS[campaign.status]}</span>
        </p>
      )}
      {campaign?.status === "awaiting_approval" && (
        <button type="button" onClick={() => void approve(campaign.id)}>
          Approve
        </button>
      )}
      {campaign?.receipt && (
        <p>
          Receipt: <code data-testid="receipt">{campaign.receipt}</code>
        </p>
      )}
    </main>
  );
}
