import { useEffect, useState, type FormEvent } from "react";
import {
  approveCampaign,
  createCampaign,
  getCampaign,
  getMe,
  listCampaigns,
  previewUrl,
  SignedOutError,
  type Campaign,
  type EmailDraft,
  type Me,
  type RunEvent,
} from "./api";
import { accessToken, finishSignIn, signIn, signOut } from "./auth";
import { messageOf } from "./messages";
import { useRunEvents } from "./useRunEvents";

const POLL_MS = 500;

const STEP_LABELS: Record<string, string> = { email_draft: "Email draft" };

const STATUS_LABELS: Record<Campaign["status"], string> = {
  drafting: "Drafting",
  awaiting_approval: "Waiting for approval",
  sending: "Sending",
  sent: "Sent",
  failed: "Failed",
};

async function pollWhileSending(first: Campaign, onUpdate: (c: Campaign) => void): Promise<void> {
  let current = first;
  onUpdate(current);
  while (current.status === "sending") {
    await new Promise((resolve) => setTimeout(resolve, POLL_MS));
    current = await getCampaign(current.id);
    onUpdate(current);
  }
}

function RunSteps({ steps }: { steps: Record<string, RunEvent> }) {
  return (
    <ul aria-label="Run steps">
      {Object.values(steps).map((event) => (
        <li key={event.step} data-testid={`step-${event.step}`}>
          {STEP_LABELS[event.step] ?? event.step}: {event.status}
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

/** The list label for a campaign: the first line of its report. */
function titleOf(campaign: Campaign): string {
  return campaign.report.split("\n", 1)[0] ?? campaign.id;
}

interface CampaignListProps {
  campaigns: Campaign[];
  onOpen: (id: string) => void;
}

function CampaignList({ campaigns, onOpen }: CampaignListProps) {
  return (
    <section>
      <h2>Campaigns</h2>
      <ul aria-label="Campaigns">
        {campaigns.length === 0 && <li>No campaigns yet.</li>}
        {campaigns.map((c) => (
          <li key={c.id}>
            <button type="button" onClick={() => onOpen(c.id)}>
              {titleOf(c)}
            </button>{" "}
            {STATUS_LABELS[c.status]}
          </li>
        ))}
      </ul>
    </section>
  );
}

/** Approvers approve; nobody approves a campaign they created. The API enforces the same. */
function canApprove(me: Me, campaign: Campaign): boolean {
  return (
    campaign.status === "awaiting_approval" &&
    me.roles.includes("approver") &&
    campaign.created_by !== me.subject
  );
}

type Session = { state: "loading" } | { state: "signed-out" } | { state: "signed-in"; me: Me };

interface EmailPreviewProps {
  id: string;
}

function EmailPreview({ id }: EmailPreviewProps) {
  return (
    <iframe
      title="Email preview"
      src={previewUrl(id)}
      sandbox=""
      style={{ width: "100%", height: 640, border: "1px solid #ccc" }}
    />
  );
}

export function App() {
  const [session, setSession] = useState<Session>({ state: "loading" });
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      await finishSignIn();
      if (!accessToken()) return setSession({ state: "signed-out" });
      setSession({ state: "signed-in", me: await getMe() });
    })().catch((e: unknown) => {
      signOut();
      if (!(e instanceof SignedOutError)) setError(messageOf(e));
      setSession({ state: "signed-out" });
    });
  }, []);

  if (session.state === "loading") return <main aria-busy="true" />;
  if (session.state === "signed-out") {
    return (
      <main>
        <h1>Agentic Campaign Engine</h1>
        {error && <p role="alert">{error}</p>}
        <button
          type="button"
          onClick={() => void signIn().catch((e: unknown) => setError(messageOf(e)))}
        >
          Sign in
        </button>
      </main>
    );
  }
  return (
    <Workspace
      me={session.me}
      onSignOut={() => {
        signOut();
        setSession({ state: "signed-out" });
      }}
    />
  );
}

interface WorkspaceProps {
  me: Me;
  onSignOut: () => void;
}

function Workspace({ me, onSignOut }: WorkspaceProps) {
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [report, setReport] = useState("");
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { steps, reset } = useRunEvents(campaign?.id, setCampaign, setError);

  function fail(e: unknown) {
    if (e instanceof SignedOutError) return onSignOut();
    setError(messageOf(e));
  }

  async function refresh() {
    try {
      setCampaigns(await listCampaigns());
    } catch (e) {
      fail(e);
    }
  }

  useEffect(() => {
    void refresh();
    // Load the list once on sign-in; actions below refresh it.
  }, []);

  async function open(id: string) {
    setError(null);
    setCampaign(null);
    reset();
    try {
      setCampaign(await getCampaign(id));
    } catch (e) {
      fail(e);
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setCampaign(null);
    reset();
    try {
      setCampaign(await createCampaign(report));
      await refresh();
    } catch (e) {
      fail(e);
    }
  }

  async function approve(id: string) {
    setError(null);
    try {
      await pollWhileSending(await approveCampaign(id), setCampaign);
      await refresh();
    } catch (e) {
      fail(e);
    }
  }

  return (
    <main>
      <p>
        Signed in as <span data-testid="signed-in-as">{me.email}</span>{" "}
        <button type="button" onClick={onSignOut}>
          Sign out
        </button>
      </p>
      <CampaignList campaigns={campaigns} onOpen={(id) => void open(id)} />
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
      {campaign && <RunSteps steps={steps} />}
      {campaign?.status === "failed" && <p role="alert">{campaign.failure_reason}</p>}
      {campaign?.draft && <DraftView draft={campaign.draft} />}
      {campaign?.draft && <EmailPreview id={campaign.id} />}
      {campaign && campaign.status !== "drafting" && campaign.status !== "failed" && (
        <p>
          Status: <span data-testid="run-status">{STATUS_LABELS[campaign.status]}</span>
        </p>
      )}
      {campaign && canApprove(me, campaign) && (
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
