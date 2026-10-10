import { useState, type FormEvent } from "react";
import { createCampaign, type Campaign } from "./api";
import { useRunEvents } from "./useRunEvents";

const STEP_LABELS: Record<string, string> = { email_draft: "Email draft" };

export function App() {
  const [report, setReport] = useState("");
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { steps, reset } = useRunEvents(campaign?.id, setCampaign, setError);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setCampaign(null);
    reset();
    try {
      setCampaign(await createCampaign(report));
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
      {campaign && (
        <ul aria-label="Run steps">
          {Object.values(steps).map((event) => (
            <li key={event.step} data-testid={`step-${event.step}`}>
              {STEP_LABELS[event.step] ?? event.step}: {event.status}
            </li>
          ))}
        </ul>
      )}
      {campaign?.status === "failed" && <p role="alert">{campaign.failure_reason}</p>}
      {campaign?.draft && (
        <section aria-label="Email draft">
          <h2 data-testid="draft-subject">{campaign.draft.subject}</h2>
          <p>{campaign.draft.preheader}</p>
          <pre data-testid="draft-body">{campaign.draft.body}</pre>
          <p>{campaign.draft.call_to_action}</p>
        </section>
      )}
    </main>
  );
}
