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
  const showError = (e: unknown) => setError(messageOf(e));

  useEffect(() => {
    (async () => {
      await finishSignIn();
      if (!accessToken()) return setSession({ state: "signed-out" });
      setSession({ state: "signed-in", me: await getMe() });
    })().catch((e: unknown) => {
      signOut();
      if (!(e instanceof SignedOutError)) showError(e);
      setSession({ state: "signed-out" });
    });
  }, []);

  if (session.state === "loading") return <main aria-busy="true" />;
  if (session.state === "signed-out") {
    return (
      <main>
        <h1>Agentic Campaign Engine</h1>
        {error && <p role="alert">{error}</p>}
        <button type="button" onClick={() => void signIn().catch(showError)}>
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

type Fail = (e: unknown) => void;

/** The campaigns the user can see, loaded on sign-in; `refresh` reloads them. */
function useCampaignList(fail: Fail): { campaigns: Campaign[]; refresh: () => Promise<void> } {
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);

  async function refresh() {
    try {
      setCampaigns(await listCampaigns());
    } catch (e) {
      fail(e);
    }
  }

  useEffect(() => {
    void refresh();
    // Load the list once on sign-in; the actions refresh it.
  }, []);

  return { campaigns, refresh };
}

/** The campaign on screen and its run: open one, create one, approve it. */
function useCampaignRun(
  fail: Fail,
  setError: (message: string | null) => void,
  refresh: () => Promise<void>,
) {
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const { steps, reset } = useRunEvents(campaign?.id, setCampaign, setError);

  async function attempt(task: () => Promise<void>) {
    setError(null);
    try {
      await task();
    } catch (e) {
      fail(e);
    }
  }

  async function show(next: Promise<Campaign>) {
    setCampaign(null);
    reset();
    setCampaign(await next);
  }

  return {
    campaign,
    steps,
    open: (id: string) => attempt(() => show(getCampaign(id))),
    create: (report: string) =>
      attempt(async () => {
        await show(createCampaign(report));
        await refresh();
      }),
    approve: (id: string) =>
      attempt(async () => {
        await pollWhileSending(await approveCampaign(id), setCampaign);
        await refresh();
      }),
  };
}

interface SignedInBarProps {
  email: string;
  onSignOut: () => void;
}

function SignedInBar({ email, onSignOut }: SignedInBarProps) {
  return (
    <p>
      Signed in as <span data-testid="signed-in-as">{email}</span>{" "}
      <button type="button" onClick={onSignOut}>
        Sign out
      </button>
    </p>
  );
}

function NewCampaignForm({ onCreate }: { onCreate: (report: string) => void }) {
  const [report, setReport] = useState("");

  function submit(event: FormEvent) {
    event.preventDefault();
    onCreate(report);
  }

  return (
    <>
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
    </>
  );
}

interface RunViewProps {
  me: Me;
  campaign: Campaign;
  steps: Record<string, RunEvent>;
  onApprove: (id: string) => void;
}

function RunView({ me, campaign, steps, onApprove }: RunViewProps) {
  const hasStatus = campaign.status !== "drafting" && campaign.status !== "failed";
  return (
    <>
      <RunSteps steps={steps} />
      {campaign.status === "failed" && <p role="alert">{campaign.failure_reason}</p>}
      {campaign.draft && <DraftView draft={campaign.draft} />}
      {campaign.draft && <EmailPreview id={campaign.id} />}
      {hasStatus && (
        <p>
          Status: <span data-testid="run-status">{STATUS_LABELS[campaign.status]}</span>
        </p>
      )}
      {canApprove(me, campaign) && (
        <button type="button" onClick={() => onApprove(campaign.id)}>
          Approve
        </button>
      )}
      {campaign.receipt && (
        <p>
          Receipt: <code data-testid="receipt">{campaign.receipt}</code>
        </p>
      )}
    </>
  );
}

interface WorkspaceProps {
  me: Me;
  onSignOut: () => void;
}

function Workspace({ me, onSignOut }: WorkspaceProps) {
  const [error, setError] = useState<string | null>(null);
  const fail: Fail = (e) => (e instanceof SignedOutError ? onSignOut() : setError(messageOf(e)));
  const { campaigns, refresh } = useCampaignList(fail);
  const run = useCampaignRun(fail, setError, refresh);

  return (
    <main>
      <SignedInBar email={me.email} onSignOut={onSignOut} />
      <CampaignList campaigns={campaigns} onOpen={(id) => void run.open(id)} />
      <NewCampaignForm onCreate={(report) => void run.create(report)} />
      {error && <p role="alert">{error}</p>}
      {run.campaign && (
        <RunView
          me={me}
          campaign={run.campaign}
          steps={run.steps}
          onApprove={(id) => void run.approve(id)}
        />
      )}
    </main>
  );
}
