# Per-asset approval

An approver decides each asset of a campaign on its own. This records the choices behind that.

## Decision

- **An asset is the output of a writer step.** Every agent step is an asset except `strategist`
  and `research`. The inbox lists the assets of campaigns that wait for approval, in the
  approver's team, that the approver did not create and that nobody has approved yet.
- **Approving every asset approves the campaign.** The last approval sends the same approve
  signal the campaign-wide `POST /campaigns/{id}/approve` sends, so the run publishes as before.
  The campaign-wide route stays for callers that approve everything at once.
- **A rejection goes to the same writer Session.** The agent issues a session per reply; the
  worker keeps those ids (`asset_sessions`) and the redo sends the approver's comment to them,
  as the brand reviewer's fixes already do. Only that step's agent is asked. The run stays in
  the approval wait, shows as drafting while the redo runs, and waits for approval again. The
  redo's tokens add to the step's row in the cost ledger.
- **The team filter is in the API for now.** Row-level security (spec decision 19) is not in
  the database yet, so the inbox and the decision routes check the campaign's team themselves
  and answer 404 for another team's campaign. Move the check into a policy when RLS lands.
- **Slack links to the inbox.** With `ACE_WEB_URL` set, the approval message ends with
  `<web url>/?inbox=<campaign id>`; the web app keeps the id through sign-in and opens the
  inbox with that campaign first. With it unset, the message has no link.
- **New tables only.** `asset_sessions` and `asset_approvals` are new, so `create_all` adds
  them; no live column change is needed.

## Limits

- The reviewer's flags stay on an asset after a redo until a new review runs; a redo is not
  reviewed again.
- A redo does not check the campaign's budget.
