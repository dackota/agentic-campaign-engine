import { useEffect, useState, type Dispatch, type SetStateAction } from "react";
import {
  approveCampaign,
  createCampaign,
  getCampaign,
  getMe,
  listCampaigns,
  raiseBudget,
  retryCampaign,
  SignedOutError,
  type Campaign,
  type Me,
} from "./api";
import { AlertBanner } from "./AlertBanner";
import { Builder } from "./Builder";
import { canCreate, CampaignHome, NavLink } from "./CampaignHome";
import { Dashboard } from "./Dashboard";
import { Inbox, rememberInboxLink, takeInboxLink } from "./Inbox";
import { Learnings } from "./Learnings";
import { accessToken, finishSignIn, signIn, signOut } from "./auth";
import { messageOf } from "./messages";
import { NewCampaignForm } from "./NewCampaignForm";
import { RunView } from "./RunView";
import { campaignPath, useRoute, type Route } from "./route";
import { Header, PRODUCT_NAME, ViewNav, type View } from "./Shell";
import { EmptyBlock, ErrorBlock, LoadingBlock } from "./ui";
import { useRunEvents } from "./useRunEvents";

const POLL_MS = 500;
// The simulated audience keeps engaging after the send; watch for the A/B call this long.
const AB_WATCH_POLLS = 120;

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

type Session = { state: "loading" } | { state: "signed-out" } | { state: "signed-in"; me: Me };

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
