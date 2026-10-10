import { useState, type FormEvent } from "react";
import { approveCampaign, createCampaign, getCampaign, type Campaign } from "./api";

const POLL_MS = 500;

const STATUS_LABELS: Record<Campaign["status"], string> = {
  drafting: "Drafting",
  awaiting_approval: "Waiting for approval",
  sending: "Sending",
  sent: "Sent",
  failed: "Failed",
};

async function pollWhile(
  first: Campaign,
  isBusy: (c: Campaign) => boolean,
  onUpdate: (c: Campaign) => void,
): Promise<void> {
  let current = first;
  onUpdate(current);
  while (isBusy(current)) {
    await new Promise((resolve) => setTimeout(resolve, POLL_MS));
    current = await getCampaign(current.id);
    onUpdate(current);
  }
}

export function App() {
  const [report, setReport] = useState("");
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setCampaign(null);
    try {
      await pollWhile(await createCampaign(report), (c) => c.status === "drafting", setCampaign);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function approve(id: string) {
    setError(null);
    try {
      await pollWhile(
        await approveCampaign(id),
        (c) => c.status === "sending",
        setCampaign,
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
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
        <button type="submit" disabled={!report.trim()}>
          Create campaign
        </button>
      </form>
      {error && <p role="alert">{error}</p>}
      {campaign?.status === "drafting" && <p>Drafting the email...</p>}
      {campaign?.status === "failed" && <p role="alert">{campaign.failure_reason}</p>}
      {campaign?.draft && (
        <section aria-label="Email draft">
          <h2 data-testid="draft-subject">{campaign.draft.subject}</h2>
          <p>{campaign.draft.preheader}</p>
          <pre data-testid="draft-body">{campaign.draft.body}</pre>
          <p>{campaign.draft.call_to_action}</p>
        </section>
      )}
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
