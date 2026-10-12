# Per-asset approval

Date: 2026-10-12. Status: accepted.

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

- A redo goes through the brand reviewer as a first draft does, for the step's `review_rounds`
  (at most two fix rounds), so the flags on a redone asset are the new draft's. A step that
  starts again drops the flags of its earlier run.
- A redo checks the campaign's budget before it calls the model. At the budget the run pauses
  as any agent step does, and a raise of the budget resumes the redo.
- The inbox leaves out campaigns the approver created, as `authorize` refuses an approver
  their own campaign.
- A rejection that names a step that is not an agent step is logged and dropped. The API
  accepts only asset steps, so no request reaches that path.
- A step answered from the step cache has no writer session to go back to, so its redo asks
  fresh sessions with the approver's comment and keeps those for later redos.
