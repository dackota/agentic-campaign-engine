import { useEffect, useState, type FormEvent } from "react";
import {
  approveCampaign,
  createCampaign,
  getCampaign,
  getMe,
  listCampaigns,
  previewUrl,
  raiseBudget,
  retryCampaign,
  SignedOutError,
  type Campaign,
  type CampaignCost,
  type EmailDraft,
  type Me,
  type RunEvent,
  type Usage,
} from "./api";
import { Builder } from "./Builder";
import { accessToken, finishSignIn, signIn, signOut } from "./auth";
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
  retrying: "Retrying",
  finished: "Finished",
  budget_paused: "Paused at budget",
};

const COST_DECIMALS = 4;

/** Tokens and dollars, e.g. "3,000 tokens, $0.0162". */
function costText(usage: Usage): string {
  return `${usage.total_tokens.toLocaleString("en-US")} tokens, $${usage.cost_usd.toFixed(COST_DECIMALS)}`;
}

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

interface RunStepsProps {
  dag: WorkflowStep[];
  events: Record<string, RunEvent>;
  cost: CampaignCost;
}

/** The pinned workflow's steps in run order, each with its latest status and, for a model
 * step that ran, its tokens and cost; then the run's total. */
function RunSteps({ dag, events, cost }: RunStepsProps) {
  const costs = new Map(cost.steps.map((s) => [s.step, s]));
  return (
    <>
      <ul aria-label="Run steps">
        {dag.map((step) => {
          const stepCost = costs.get(step.id);
          return (
            <li key={step.id} data-testid={`step-${step.id}`}>
              {STEP_LABELS[step.id] ?? step.id}: {events[step.id]?.status ?? PENDING}
              {stepCost && (
                <>
                  {" "}
                  (<span data-testid={`step-cost-${step.id}`}>{costText(stepCost)}</span>)
                </>
              )}
            </li>
          );
        })}
      </ul>
      <p>
        Cost: <span data-testid="run-cost">{costText(cost)}</span>
      </p>
    </>
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

/** Owners run campaigns, so they raise the budget of a paused one. The API enforces the same. */
function canRaiseBudget(me: Me, campaign: Campaign): boolean {
  return campaign.status === "budget_paused" && me.roles.includes("owner");
}

/** Owners run campaigns, so they retry the step that stopped one. The API enforces the same. */
function canRetry(me: Me, campaign: Campaign): boolean {
  return campaign.status === "failed" && me.roles.includes("owner");
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
  const { steps, reset, resume } = useRunEvents(campaign?.id, setCampaign, setError);

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
    create: (report: string, workflow: string, budgetUsd: number | null) =>
      attempt(async () => {
        await show(createCampaign(report, workflow, budgetUsd));
        await refresh();
      }),
    raiseBudget: (id: string, budgetUsd: number) =>
      attempt(async () => {
        setCampaign(await raiseBudget(id, budgetUsd));
        resume();
        await refresh();
      }),
    approve: (id: string) =>
      attempt(async () => {
        await pollWhileSending(await approveCampaign(id), setCampaign);
        await refresh();
      }),
    retry: (id: string) =>
      attempt(async () => {
        setCampaign(await retryCampaign(id));
        resume();
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

interface NewCampaignFormProps {
  onCreate: (report: string, workflow: string, budgetUsd: number | null) => void;
}

/** A dollar amount typed in a form, or null when the field is blank. */
function dollarsOf(text: string): number | null {
  return text.trim() ? Number(text) : null;
}

function NewCampaignForm({ onCreate }: NewCampaignFormProps) {
  const [report, setReport] = useState("");
  const [workflow, setWorkflow] = useState("");
  const [budget, setBudget] = useState("");

  function submit(event: FormEvent) {
    event.preventDefault();
    onCreate(report, workflow, dollarsOf(budget));
  }

  return (
    <>
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
        <label>
          Budget (USD)
          <input
            type="number"
            min="0"
            step="any"
            value={budget}
            onChange={(e) => setBudget(e.target.value)}
            placeholder="no limit"
          />
        </label>
        <button type="submit" disabled={!report.trim()}>
          Create campaign
        </button>
      </form>
    </>
  );
}

interface RaiseBudgetFormProps {
  onRaise: (budgetUsd: number) => void;
}

function RaiseBudgetForm({ onRaise }: RaiseBudgetFormProps) {
  const [budget, setBudget] = useState("");

  function submit(event: FormEvent) {
    event.preventDefault();
    const dollars = dollarsOf(budget);
    if (dollars !== null) onRaise(dollars);
  }

  return (
    <form onSubmit={submit}>
      <label>
        New budget (USD)
        <input
          type="number"
          min="0"
          step="any"
          value={budget}
          onChange={(e) => setBudget(e.target.value)}
        />
      </label>
      <button type="submit" disabled={!budget.trim()}>
        Raise budget
      </button>
    </form>
  );
}

interface RunViewProps {
  me: Me;
  campaign: Campaign;
  steps: Record<string, RunEvent>;
  onApprove: (id: string) => void;
  onRetry: (id: string) => void;
  onRaiseBudget: (id: string, budgetUsd: number) => void;
}

function RunView({ me, campaign, steps, onApprove, onRetry, onRaiseBudget }: RunViewProps) {
  const hasStatus = campaign.status !== "drafting" && campaign.status !== "failed";
  return (
    <>
      <RunSteps dag={campaign.steps} events={steps} cost={campaign.cost} />
      {campaign.budget_usd !== null && (
        <p>
          Budget: <span data-testid="run-budget">${campaign.budget_usd.toFixed(COST_DECIMALS)}</span>
        </p>
      )}
      {canRaiseBudget(me, campaign) && (
        <RaiseBudgetForm onRaise={(dollars) => onRaiseBudget(campaign.id, dollars)} />
      )}
      {campaign.status === "failed" && <p role="alert">{campaign.failure_reason}</p>}
      {canRetry(me, campaign) && (
        <button type="button" onClick={() => onRetry(campaign.id)}>
          Retry step
        </button>
      )}
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
      {campaign.workflow_version !== null && (
        <p>
          Workflow: <span data-testid="workflow-version">{`${campaign.workflow} version ${campaign.workflow_version}`}</span>
        </p>
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
  const [view, setView] = useState<"campaigns" | "builder">("campaigns");

  return (
    <main>
      <SignedInBar email={me.email} onSignOut={onSignOut} />
      <nav>
        <button type="button" onClick={() => setView("campaigns")}>
          Campaigns
        </button>{" "}
        <button type="button" onClick={() => setView("builder")}>
          Workflow builder
        </button>
      </nav>
      {view === "builder" ? (
        <Builder />
      ) : (
        <Campaigns
          me={me}
          error={error}
          list={campaigns}
          run={run}
        />
      )}
    </main>
  );
}

type CampaignRun = ReturnType<typeof useCampaignRun>;

interface CampaignsProps {
  me: Me;
  error: string | null;
  list: Campaign[];
  run: CampaignRun;
}

function Campaigns({ me, error, list, run }: CampaignsProps) {
  return (
    <>
      <CampaignList campaigns={list} onOpen={(id) => void run.open(id)} />
      <NewCampaignForm
        onCreate={(report, workflow, budgetUsd) => void run.create(report, workflow, budgetUsd)}
      />
      {error && <p role="alert">{error}</p>}
      {run.campaign && (
        <RunView
          me={me}
          campaign={run.campaign}
          steps={run.steps}
          onApprove={(id) => void run.approve(id)}
          onRetry={(id) => void run.retry(id)}
          onRaiseBudget={(id, budgetUsd) => void run.raiseBudget(id, budgetUsd)}
        />
      )}
    </>
  );
}
