import { useEffect, useState, type Dispatch, type FormEvent, type ReactNode, type SetStateAction } from "react";
import {
  approveCampaign,
  createCampaign,
  getCampaign,
  getMe,
  listCampaigns,
  listWorkflows,
  previewUrl,
  raiseBudget,
  retryCampaign,
  SignedOutError,
  MAX_SCORE,
  type AbResult,
  type AssetScore,
  type Campaign,
  type CampaignCost,
  type EmailDraft,
  type Me,
  type RunEvent,
  type Usage,
} from "./api";
import { AlertBanner } from "./AlertBanner";
import { Builder } from "./Builder";
import { Dashboard } from "./Dashboard";
import { Inbox, rememberInboxLink, takeInboxLink } from "./Inbox";
import { Learnings } from "./Learnings";
import { PreviewFrame } from "./PreviewFrame";
import { accessToken, finishSignIn, signIn, signOut } from "./auth";
import { failureText, nextStepText, statusLabel, stepLabel, workflowLabel } from "./labels";
import { messageOf } from "./messages";
import { RunGraph } from "./RunGraphView";
import { campaignPath, NEW_CAMPAIGN_PATH, useRoute, type Route } from "./route";
import { Header, PRODUCT_NAME, ViewNav, type View } from "./Shell";
import { Card, EmptyBlock, ErrorBlock, LoadingBlock, StatusBadge, type Tone } from "./ui";
import { useRunEvents } from "./useRunEvents";

const POLL_MS = 500;
// The simulated audience keeps engaging after the send; watch for the A/B call this long.
const AB_WATCH_POLLS = 120;

const STATUS_TONES: Record<Campaign["status"], Tone> = {
  drafting: "info",
  awaiting_approval: "warn",
  sending: "info",
  sent: "ok",
  failed: "bad",
  retrying: "warn",
  finished: "ok",
  budget_paused: "warn",
};

const COST_DECIMALS = 4;
const REPORT_ROWS = 14;
const DEFAULT_WORKFLOW = "threat-report-to-campaign";
/** The built-in one-email pipeline: no saved workflow, so the API gets an empty name. */
const QUICK_DRAFT_LABEL = "Quick email draft";

/** Money on a main screen: dollars and cents. */
const dollarsText = (usd: number): string => `$${usd.toFixed(2)}`;

/** Tokens and dollars, e.g. "3,000 tokens, $0.0162". */
function costText(usage: Usage): string {
  return `${usage.total_tokens.toLocaleString("en-US")} tokens, $${usage.cost_usd.toFixed(COST_DECIMALS)}`;
}

async function pollWhileSending(first: Campaign, onUpdate: (c: Campaign) => void): Promise<void> {
  let current = first;
  onUpdate(current);
  while (current.status === "sending") {
    await new Promise((resolve) => setTimeout(resolve, POLL_MS));
    current = await getCampaign(current.id);
    onUpdate(current);
  }
}

/** Re-read a sent campaign until the A/B test calls a winner, or the watch runs out. */
async function watchAbResult(id: string, onUpdate: (c: Campaign) => void): Promise<void> {
  for (let i = 0; i < AB_WATCH_POLLS; i++) {
    await new Promise((resolve) => setTimeout(resolve, POLL_MS));
    const current = await getCampaign(id);
    onUpdate(current);
    if (current.ab_result.status === "winner") return;
  }
}

/** The A/B call: "Version B won, 97% confident", or "No decision yet". */
function abResultText(result: AbResult): string {
  if (result.status !== "winner" || result.confidence === null) return "No decision yet";
  return `Version ${result.winner} won, ${Math.floor(result.confidence * 100)}% confident`;
}

/** What the run cost, in dollars and cents. */
function RunCost({ cost }: { cost: CampaignCost }) {
  return (
    <p>
      Cost: <span data-testid="run-cost">{dollarsText(cost.cost_usd)}</span>
    </p>
  );
}

/** Tokens and exact cost of each model step that ran, then the run's total. For engineers. */
function RunCostDetails({ cost }: { cost: CampaignCost }) {
  return (
    <section aria-label="Run cost details">
      <ul>
        {cost.steps.map((s) => (
          <li key={s.step}>
            {s.step}: <span data-testid={`step-cost-${s.step}`}>{costText(s)}</span>
          </li>
        ))}
      </ul>
      <p>
        Total: <span data-testid="run-tokens">{costText(cost)}</span>
      </p>
    </section>
  );
}

/** The judge's score and reason for each asset of the run. */
function RunScores({ scores }: { scores: AssetScore[] }) {
  if (scores.length === 0) return <EmptyBlock>No quality check yet.</EmptyBlock>;
  return (
    <section aria-label="Judge scores">
      <ul className="score-list">
        {scores.map((s) => (
          <li key={s.step}>
            {stepLabel(s.step)}: <strong data-testid={`judge-score-${s.step}`}>{`${s.score}/${MAX_SCORE}`}</strong>{" "}
            <span data-testid={`judge-reason-${s.step}`}>{s.reason}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function DraftView({ draft, id, showDetails }: { draft: EmailDraft; id: string; showDetails: boolean }) {
  return (
    <>
      <h3 data-testid="draft-subject">{draft.subject}</h3>
      <p className="hint">{draft.preheader}</p>
      <EmailPreview id={id} />
      {/* The raw text is for engineers; a marketer reads the rendered email above. */}
      {showDetails && <pre data-testid="draft-body">{draft.body}</pre>}
    </>
  );
}

/** The list label for a campaign: the first line of its report. */
function titleOf(campaign: Campaign): string {
  return campaign.report.split("\n", 1)[0] ?? campaign.id;
}

/** A link to a path inside the app: a real href, so it opens in a new tab and can be shared. */
function NavLink({ path, go, className, children }: NavLinkProps) {
  return (
    <a
      href={path}
      className={className}
      onClick={(e) => {
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
        e.preventDefault();
        go(path);
      }}
    >
      {children}
    </a>
  );
}

interface NavLinkProps {
  path: string;
  go: (path: string) => void;
  className?: string;
  children: ReactNode;
}

/** Owners run campaigns, so only they see the way to start one. The API enforces the same. */
const canCreate = (me: Me): boolean => me.roles.includes("owner");

function CampaignCard({ me, campaign, go }: { me: Me; campaign: Campaign; go: (path: string) => void }) {
  return (
    <li className="card-item">
      <Card>
        <h3 className="card-title">
          <NavLink path={campaignPath(campaign.id)} go={go}>
            {titleOf(campaign)}
          </NavLink>
        </h3>
        <p>
          <span data-testid="card-status">
            <StatusBadge tone={STATUS_TONES[campaign.status]}>{statusLabel(campaign.status)}</StatusBadge>
          </span>
        </p>
        <dl className="card-facts">
          <dt>Owner</dt>
          {/* The API names the creator by an opaque id, so the card says only whether it is you. */}
          <dd data-testid="card-owner">{campaign.created_by === me.subject ? "You" : "A teammate"}</dd>
          <dt>Started</dt>
          <dd data-testid="card-started">
            <time dateTime={campaign.created_at}>{new Date(campaign.created_at).toLocaleString()}</time>
          </dd>
          <dt>Cost</dt>
          <dd data-testid="card-cost">{dollarsText(campaign.cost.cost_usd)}</dd>
        </dl>
      </Card>
    </li>
  );
}

interface CampaignHomeProps {
  me: Me;
  campaigns: Campaign[] | null;
  go: (path: string) => void;
}

function CampaignHome({ me, campaigns, go }: CampaignHomeProps) {
  return (
    <section>
      <div className="page-head">
        <h1>Campaigns</h1>
        {canCreate(me) && (
          <NavLink path={NEW_CAMPAIGN_PATH} go={go} className="btn btn-primary">
            New campaign
          </NavLink>
        )}
      </div>
      {campaigns === null ? (
        <LoadingBlock>Loading your campaigns…</LoadingBlock>
      ) : campaigns.length === 0 ? (
        <EmptyBlock>
          No campaigns yet.{" "}
          {canCreate(me) ? (
            <NavLink path={NEW_CAMPAIGN_PATH} go={go} className="btn btn-primary">
              Start your first campaign
            </NavLink>
          ) : (
            "An owner on your team can start one."
          )}
        </EmptyBlock>
      ) : (
        <ul aria-label="Campaigns" className="card-list">
          {campaigns.map((c) => (
            <CampaignCard key={c.id} me={me} campaign={c} go={go} />
          ))}
        </ul>
      )}
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
    <PreviewFrame title="Email preview" src={previewUrl(id)} isTall />
  );
}

export function App() {
  const [session, setSession] = useState<Session>({ state: "loading" });
  const [error, setError] = useState<string | null>(null);
  const showError = (e: unknown) => setError(messageOf(e));

  useEffect(() => {
    rememberInboxLink();
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

  if (session.state === "loading") {
    return (
      <main aria-busy="true">
        <LoadingBlock />
      </main>
    );
  }
  if (session.state === "signed-out") {
    return (
      <main>
        <h1>{PRODUCT_NAME}</h1>
        {error && <ErrorBlock>{error}</ErrorBlock>}
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
function useCampaignList(fail: Fail): { campaigns: Campaign[] | null; refresh: () => Promise<void> } {
  // null until the first read, so home shows a loading state, not an empty one.
  const [campaigns, setCampaigns] = useState<Campaign[] | null>(null);

  async function refresh() {
    try {
      setCampaigns(await listCampaigns());
    } catch (e) {
      setCampaigns((shown) => shown ?? []);
      fail(e);
    }
  }

  useEffect(() => {
    void refresh();
    // Load the list once on sign-in; the actions refresh it.
  }, []);

  return { campaigns, refresh };
}

/** Run a user action: clear the last error first, and show the action's failure. */
async function attemptAction(
  task: () => Promise<void>,
  setError: (message: string | null) => void,
  fail: Fail,
): Promise<void> {
  setError(null);
  try {
    await task();
  } catch (e) {
    fail(e);
  }
}

/** Approve, follow the send, then watch for the A/B call without holding the page. */
async function approveAndWatch(
  id: string,
  setCampaign: Dispatch<SetStateAction<Campaign | null>>,
  refresh: () => Promise<void>,
  fail: Fail,
): Promise<void> {
  await pollWhileSending(await approveCampaign(id), setCampaign);
  await refresh();
  // Not awaited: the page stays usable while the audience engages. A failed read
  // only stops the watch; the shown result stays as last read.
  void watchAbResult(id, (next) => setCampaign((shown) => (shown?.id === id ? next : shown))).catch(fail);
}

/** The campaign on screen and its run: open one, create one, approve it. */
function useCampaignRun(
  go: (path: string) => void,
  fail: Fail,
  setError: (message: string | null) => void,
  refresh: () => Promise<void>,
) {
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const { events, reset, resume } = useRunEvents(campaign?.id, setCampaign, setError);
  const attempt = (task: () => Promise<void>) => attemptAction(task, setError, fail);

  function show(next: Promise<Campaign>): Promise<Campaign> {
    setCampaign(null);
    reset();
    return next.then((shown) => {
      setCampaign(shown);
      return shown;
    });
  }

  return {
    campaign,
    events,
    open: (id: string) => attempt(async () => void (await show(getCampaign(id)))),
    create: (report: string, workflow: string, budgetUsd: number | null) =>
      attempt(async () => {
        const created = await show(createCampaign(report, workflow, budgetUsd));
        go(campaignPath(created.id));
        await refresh();
      }),
    raiseBudget: (id: string, budgetUsd: number) =>
      attempt(async () => {
        setCampaign(await raiseBudget(id, budgetUsd));
        resume();
        await refresh();
      }),
    approve: (id: string) => attempt(() => approveAndWatch(id, setCampaign, refresh, fail)),
    retry: (id: string) =>
      attempt(async () => {
        setCampaign(await retryCampaign(id));
        resume();
        await refresh();
      }),
  };
}

interface NewCampaignFormProps {
  onCreate: (report: string, workflow: string, budgetUsd: number | null) => void;
}

/** A dollar amount typed in a form, or null when the field is blank. */
function dollarsOf(text: string): number | null {
  return text.trim() ? Number(text) : null;
}

/** The saved workflows by name; the standard one is chosen to start with. */
function WorkflowPicker({ value, onChange }: { value: string; onChange: (name: string) => void }) {
  const [workflows, setWorkflows] = useState([DEFAULT_WORKFLOW]);
  const [hasListError, setHasListError] = useState(false);

  useEffect(() => {
    listWorkflows()
      .then((names) => setWorkflows(names.includes(DEFAULT_WORKFLOW) ? names : [DEFAULT_WORKFLOW, ...names]))
      .catch((e: unknown) => {
        console.error("could not list saved workflows", e);
        setHasListError(true);
      });
  }, []);

  return (
    <>
      {/* The select sits beside its label, not inside: the label's text must stay "Workflow". */}
      <label htmlFor="workflow-picker">Workflow</label>
      <select id="workflow-picker" value={value} onChange={(e) => onChange(e.target.value)}>
        {workflows.map((name) => (
          <option key={name} value={name}>
            {workflowLabel(name)}
          </option>
        ))}
        <option value="">{QUICK_DRAFT_LABEL}</option>
      </select>
      {hasListError && <p>Could not load your saved workflows, so only the standard one is offered.</p>}
    </>
  );
}

/** The optional spend limit, with what it does in words. */
function BudgetField({ value, onChange }: { value: string; onChange: (text: string) => void }) {
  return (
    <>
      <label>
        Budget (USD)
        <input
          type="number"
          min="0"
          step="any"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="no limit"
          aria-describedby="budget-hint"
        />
      </label>
      <p id="budget-hint" className="hint">
        Optional. The campaign pauses if it reaches this amount.
      </p>
    </>
  );
}

function NewCampaignForm({ onCreate }: NewCampaignFormProps) {
  const [report, setReport] = useState("");
  const [workflow, setWorkflow] = useState(DEFAULT_WORKFLOW);
  const [budget, setBudget] = useState("");
  const hasReport = report.trim() !== "";

  function submit(event: FormEvent) {
    event.preventDefault();
    onCreate(report, workflow, dollarsOf(budget));
  }

  return (
    <>
      <h1>New campaign</h1>
      <form onSubmit={submit} className="new-campaign">
        <label>
          Threat report
          <textarea
            value={report}
            onChange={(e) => setReport(e.target.value)}
            rows={REPORT_ROWS}
            aria-describedby="report-hint"
          />
        </label>
        <p id="report-hint" className="hint">
          Paste the threat report or advisory. The first line becomes the campaign title.
        </p>
        <WorkflowPicker value={workflow} onChange={setWorkflow} />
        <BudgetField value={budget} onChange={setBudget} />
        <button
          type="submit"
          className="btn btn-primary"
          disabled={!hasReport}
          aria-describedby={hasReport ? undefined : "create-reason"}
        >
          Create campaign
        </button>
        {!hasReport && (
          <p id="create-reason" className="hint">
            Add your threat report to start the campaign.
          </p>
        )}
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
  events: RunEvent[];
  onApprove: (id: string) => void;
  onRetry: (id: string) => void;
  onRaiseBudget: (id: string, budgetUsd: number) => void;
}

/** The workflow the run pinned, by name; its raw id and the run id sit behind Details. */
function RunWorkflow({ campaign, showDetails }: { campaign: Campaign; showDetails: boolean }) {
  return (
    <>
      {campaign.workflow_version !== null && (
        <p>
          Workflow:{" "}
          <span data-testid="workflow-version">{`${workflowLabel(campaign.workflow ?? DEFAULT_WORKFLOW)} version ${campaign.workflow_version}`}</span>
        </p>
      )}
      {showDetails && <RunIds campaign={campaign} />}
    </>
  );
}

/** The raw ids an engineer needs to find the run in logs and the database. */
function RunIds({ campaign }: { campaign: Campaign }) {
  return (
    <p>
      Workflow id: <code data-testid="workflow-id">{campaign.workflow ?? DEFAULT_WORKFLOW}</code>, run id:{" "}
      <code>{campaign.id}</code>
    </p>
  );
}

function RunCards({ campaign, showDetails }: { campaign: Campaign; showDetails: boolean }) {
  return (
    <div className="card-grid">
      <Card label="Quality">
        <h2>Quality</h2>
        <RunScores scores={campaign.scores} />
      </Card>
      <Card label="Cost">
        <h2>Cost</h2>
        <RunCost cost={campaign.cost} />
        {campaign.budget_usd !== null && (
          <p>
            Budget: <span data-testid="run-budget">{dollarsText(campaign.budget_usd)}</span>
          </p>
        )}
        {showDetails && <RunCostDetails cost={campaign.cost} />}
      </Card>
      <div className="card-wide">
        <Card label="Draft">
          <h2>Draft</h2>
          {campaign.draft ? (
            <DraftView draft={campaign.draft} id={campaign.id} showDetails={showDetails} />
          ) : (
            <EmptyBlock>The draft appears here when the AI finishes writing it.</EmptyBlock>
          )}
        </Card>
      </div>
    </div>
  );
}

function RunView({ me, campaign, events, onApprove, onRetry, onRaiseBudget }: RunViewProps) {
  const [showDetails, setShowDetails] = useState(false);
  return (
    <>
      <h1 className="page-title">{titleOf(campaign)}</h1>
      <p>
        <StatusBadge tone={STATUS_TONES[campaign.status]}>
          <span data-testid="run-status">{statusLabel(campaign.status)}</span>
        </StatusBadge>
      </p>
      <p className="next-step" data-testid="next-step">
        {nextStepText(campaign.status)}
      </p>
      {campaign.status === "failed" && <ErrorBlock>{failureText(campaign.failure_reason)}</ErrorBlock>}
      {campaign.status === "failed" && showDetails && <pre data-testid="failure-raw">{campaign.failure_reason}</pre>}
      <div className="action-row">
        {canRetry(me, campaign) && (
          <button type="button" className="btn btn-primary" onClick={() => onRetry(campaign.id)}>
            Retry step
          </button>
        )}
        {canRaiseBudget(me, campaign) && (
          <RaiseBudgetForm onRaise={(dollars) => onRaiseBudget(campaign.id, dollars)} />
        )}
        {canApprove(me, campaign) && (
          <button type="button" className="btn btn-primary" onClick={() => onApprove(campaign.id)}>
            Approve
          </button>
        )}
        <button type="button" aria-expanded={showDetails} onClick={() => setShowDetails(!showDetails)}>Details</button>
      </div>
      <RunGraph dag={campaign.steps} edges={campaign.edges} events={events} showDetails={showDetails} />
      <RunCards campaign={campaign} showDetails={showDetails} />
      {(campaign.status === "sent" || campaign.status === "finished") && (
        <p>
          A/B result: <span data-testid="ab-result">{abResultText(campaign.ab_result)}</span>
        </p>
      )}
      <RunWorkflow campaign={campaign} showDetails={showDetails} />
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

type CampaignRun = ReturnType<typeof useCampaignRun>;

/** A campaign's own URL opens it, on a reload or a shared link too. */
function useOpenRouteCampaign(route: Route, run: CampaignRun): void {
  const routeId = route.page === "campaign" ? route.id : null;
  useEffect(() => {
    if (routeId !== null && run.campaign?.id !== routeId) void run.open(routeId);
    // Open when the address changes; `run` is rebuilt each render.
  }, [routeId]);
}

function Workspace({ me, onSignOut }: WorkspaceProps) {
  const [error, setError] = useState<string | null>(null);
  const fail: Fail = (e) => (e instanceof SignedOutError ? onSignOut() : setError(messageOf(e)));
  const { campaigns, refresh } = useCampaignList(fail);
  const { route, go } = useRoute();
  const run = useCampaignRun(go, fail, setError, refresh);
  const [linkedCampaign] = useState(takeInboxLink);
  const [view, setView] = useState<View>(linkedCampaign ? "inbox" : "campaigns");
  const goCampaigns = (path: string) => {
    setView("campaigns");
    go(path);
  };
  useOpenRouteCampaign(route, run);

  return (
    <>
      <Header me={me} onSignOut={onSignOut} />
      <ViewNav me={me} view={view} onView={(v) => (v === "campaigns" ? goCampaigns("/") : setView(v))} />
      <main>
      <AlertBanner onSignedOut={onSignOut} />
      {view === "builder" ? (
        <Builder />
      ) : view === "dashboard" ? (
        <Dashboard onSignOut={onSignOut} />
      ) : view === "inbox" ? (
        <Inbox onSignOut={onSignOut} linkedCampaign={linkedCampaign} />
      ) : view === "learnings" ? (
        <Learnings
          canDelete={me.roles.includes("approver")}
          onOpenCampaign={(id) => {
            goCampaigns(campaignPath(id));
          }}
          onSignOut={onSignOut}
        />
      ) : (
        <Campaigns
          me={me}
          error={error}
          list={campaigns}
          run={run}
          route={route}
          go={goCampaigns}
        />
      )}
      </main>
    </>
  );
}


interface CampaignsProps {
  me: Me;
  error: string | null;
  list: Campaign[] | null;
  run: CampaignRun;
  route: Route;
  go: (path: string) => void;
}

function Campaigns({ me, error, list, run, route, go }: CampaignsProps) {
  const errorBlock = error && <ErrorBlock>{error}</ErrorBlock>;
  if (route.page === "home") {
    return (
      <>
        {errorBlock}
        <CampaignHome me={me} campaigns={list} go={go} />
      </>
    );
  }
  if (route.page === "new") {
    return canCreate(me) ? (
      <>
        <NewCampaignForm
          onCreate={(report, workflow, budgetUsd) => void run.create(report, workflow, budgetUsd)}
        />
        {errorBlock}
      </>
    ) : (
      <EmptyBlock>Only an owner can start a campaign.</EmptyBlock>
    );
  }
  return (
    <>
      <NavLink path="/" go={go}>
        All campaigns
      </NavLink>
      {errorBlock}
      {!run.campaign && !error && <LoadingBlock>Loading the campaign…</LoadingBlock>}
      {run.campaign && (
        <RunView
          me={me}
          campaign={run.campaign}
          events={run.events}
          onApprove={(id) => void run.approve(id)}
          onRetry={(id) => void run.retry(id)}
          onRaiseBudget={(id, budgetUsd) => void run.raiseBudget(id, budgetUsd)}
        />
      )}
    </>
  );
}
