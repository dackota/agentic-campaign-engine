import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { Inbox } from "./Inbox";
import type { InboxAsset } from "./inboxApi";
import { stubApi, type Route } from "./testSupport";

const FLAG = { check: "banned_claim", detail: "Says 'guaranteed protection'" };
const asset = (campaign: string, step: string, over: Partial<InboxAsset> = {}): InboxAsset => ({
  campaign_id: campaign,
  title: `Campaign ${campaign}`,
  team: "demand-gen",
  created_by: "u",
  step,
  preview_url: null,
  output: { text: "hello" },
  flags: [],
  score: null,
  score_reason: null,
  ...over,
});

/** An inbox the API keeps: an approval takes the asset out; a reject sends it back and it returns. */
function fakeInbox(initial: InboxAsset[]) {
  let waiting = [...initial];
  const routes: Record<string, Route> = { "GET /inbox": () => waiting };
  for (const a of initial) {
    routes[`POST /campaigns/${a.campaign_id}/assets/${a.step}/approve`] = () => {
      waiting = waiting.filter((w) => w !== a);
      return {};
    };
    routes[`POST /campaigns/${a.campaign_id}/assets/${a.step}/reject`] = () => ({});
  }
  return stubApi(routes);
}
const posts = (calls: { method: string; path: string }[]) => calls.filter((c) => c.method === "POST");
const card = (campaign: string, step: string) => screen.findByRole("article", { name: `Campaign ${campaign}: ${step}` });
const group = (campaign: string) => screen.findByRole("region", { name: `Campaign ${campaign}` });
const renderInbox = () => render(<Inbox onSignOut={() => {}} linkedCampaign={null} />);

test("assets wait under their campaign, with how many are waiting", async () => {
  fakeInbox([asset("a", "landing_page"), asset("a", "social"), asset("b", "email_writer")]);
  renderInbox();

  expect((await within(await group("a")).findByTestId("campaign-waiting")).textContent).toBe("2 assets waiting");
  expect(within(await group("b")).getByTestId("campaign-waiting").textContent).toBe("1 asset waiting");
  expect(await card("a", "Landing page")).toBeTruthy();
  expect(await card("a", "Social post")).toBeTruthy();
});

test("flags read in plain words in a highlighted note; an unflagged asset says there are none", async () => {
  fakeInbox([asset("a", "landing_page", { flags: [FLAG] }), asset("a", "social")]);
  renderInbox();

  const flagged = within(await card("a", "Landing page")).getByTestId("asset-flags");
  expect(flagged.textContent).toContain("Banned claim");
  expect(flagged.textContent).not.toContain("banned_claim");
  expect(flagged.className).toContain("flag-note");
  expect(within(await card("a", "Social post")).getByTestId("asset-flags").textContent).toBe("No flags from the brand reviewer.");
});

test("the judge's score and reason show on the asset", async () => {
  fakeInbox([asset("a", "landing_page", { score: 4, score_reason: "Clear and on brand" }), asset("a", "social")]);
  renderInbox();

  const scored = within(await card("a", "Landing page"));
  expect(scored.getByTestId("asset-score").textContent).toBe("4/5");
  expect(scored.getByTestId("asset-score-reason").textContent).toBe("Clear and on brand");
  expect(within(await card("a", "Social post")).queryByTestId("asset-score")).toBeNull();
});

test("the inbox shows steps by plain name, never raw ids or token counts", async () => {
  fakeInbox([asset("a", "one_pager"), asset("a", "email_writer")]);
  renderInbox();
  await card("a", "One-pager");
  for (const raw of ["email_writer", "one_pager", "tokens"]) expect(document.body.textContent).not.toContain(raw);
});

test("approving an asset with a comment sends the comment and takes it out of the inbox", async () => {
  const calls = fakeInbox([asset("a", "landing_page"), asset("a", "social")]);
  renderInbox();

  const social = within(await card("a", "Social post"));
  await userEvent.type(social.getByLabelText("Comment"), "Reads well");
  await userEvent.click(social.getByRole("button", { name: "Approve" }));

  await waitFor(() => expect(screen.queryByRole("article", { name: "Campaign a: Social post" })).toBeNull());
  expect(posts(calls)).toEqual([{ method: "POST", path: "/campaigns/a/assets/social/approve", body: { comment: "Reads well" } }]);
  expect(await card("a", "Landing page")).toBeTruthy();
});

test("rejecting needs a comment, goes to the writer, and the inbox says so", async () => {
  const calls = fakeInbox([asset("a", "landing_page", { flags: [FLAG] })]);
  renderInbox();

  const landing = within(await card("a", "Landing page"));
  const reject = landing.getByRole("button", { name: /Reject/ }) as HTMLButtonElement;
  expect(reject.textContent).toContain("comment needed");
  expect(reject.disabled).toBe(true);

  await userEvent.type(landing.getByLabelText("Comment"), "Drop the hype");
  expect(reject.disabled).toBe(false);
  await userEvent.click(reject);

  expect((await screen.findByTestId("sent-back")).textContent).toContain("Sent back to the writer for a redo: Campaign a: Landing page");
  expect(posts(calls)).toEqual([{ method: "POST", path: "/campaigns/a/assets/landing_page/reject", body: { comment: "Drop the hype" } }]);
});

test("Approve all with no flags approves only that campaign's clean assets", async () => {
  const calls = fakeInbox([
    asset("a", "landing_page", { flags: [FLAG] }),
    asset("a", "social"),
    asset("a", "one_pager"),
    asset("b", "email_writer"),
  ]);
  renderInbox();

  const a = within(await group("a"));
  await userEvent.click(await a.findByRole("button", { name: "Approve all with no flags (2)" }));

  await waitFor(() => expect(a.getByTestId("campaign-waiting").textContent).toBe("1 asset waiting"));
  expect(posts(calls).map((c) => c.path)).toEqual(["/campaigns/a/assets/social/approve", "/campaigns/a/assets/one_pager/approve"]);
  expect(await card("a", "Landing page")).toBeTruthy();
  expect(within(await group("b")).getByTestId("campaign-waiting").textContent).toBe("1 asset waiting");
});

test("a campaign with nothing clean has Approve all disabled", async () => {
  fakeInbox([asset("a", "landing_page", { flags: [FLAG] })]);
  renderInbox();
  const button = (await within(await group("a")).findByRole("button", { name: "Approve all with no flags (0)" })) as HTMLButtonElement;
  expect(button.disabled).toBe(true);
});

test("an empty inbox says nothing needs approval", async () => {
  fakeInbox([]);
  renderInbox();
  expect((await screen.findByText(/Nothing needs your approval right now/)).textContent).toContain("Campaigns appear here");
});

test("an inbox that cannot be read tells the user to check their connection, not the raw error", async () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  stubApi({ "GET /inbox": new Response("db down", { status: 500 }) });
  renderInbox();
  const alert = await screen.findByRole("alert");
  expect(alert.textContent).toContain("Check your connection");
  expect(alert.textContent).not.toContain("db down");
});
