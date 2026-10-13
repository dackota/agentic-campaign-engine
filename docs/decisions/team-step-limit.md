# Decision: a per-team step limit held in Postgres (S11)

Date: 2026-10-12. Status: accepted.

## Decision

Each team may run at most `team_step_limit` model-calling steps at once (`ACE_TEAM_STEP_LIMIT`
on the worker, default 8). A step takes one of its team's slots just before its model call
(`run_agent_step`, `redo_asset`) and gives it back after, however the call ends. When the
team's slots are all taken, the step waits in the workflow and asks again, after 1 s, then
doubling up to 8 s. Other teams' steps do not wait on it.

The slots are rows in `step_slots` (`ace_engine/team_slots.py`), one per running step, keyed
by the step's idempotency key. A claim counts the team's rows under a per-team advisory
transaction lock, so two claims cannot both take the last slot, and every worker replica
counts the same rows.

## Choices the ticket left open

- **One limit for every team.** Equal limits are the fair share the slice asks for. A
  per-team override can come when a team needs a different one.
- **Wait in the workflow, not in the activity.** A step waiting inside its activity would
  spend its own start-to-close timeout in the queue, and a long queue at live depth would
  time it out and lose the run. A workflow timer costs nothing while it waits.
- **A lease, not a lock held by a connection.** A slot whose worker died must free itself.
  Each row carries `expires_at`: the step's timeout times its attempts, plus two minutes. A
  claim drops the team's expired rows first.
- **Slots only around model calls.** Approval, publish and wait steps call no model, so
  they never take a slot; a step paused at its budget holds none while it waits.
- **Runs that started before this change** replay without slots (`workflow.patched`).

## Database

New table, additive only:

```sql
CREATE TABLE IF NOT EXISTS step_slots (
    key VARCHAR(255) PRIMARY KEY,
    campaign_id UUID NOT NULL REFERENCES campaigns (id),
    team VARCHAR(100) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_step_slots_team ON step_slots (team);
GRANT SELECT, INSERT, UPDATE, DELETE ON step_slots TO ace_team;
ALTER TABLE step_slots ENABLE ROW LEVEL SECURITY;
CREATE POLICY step_slots_by_team ON step_slots TO ace_team
    USING (EXISTS (SELECT 1 FROM campaigns c
                   WHERE c.id = campaign_id AND c.team = current_setting('ace.team', true)))
    WITH CHECK (EXISTS (SELECT 1 FROM campaigns c
                        WHERE c.id = campaign_id AND c.team = current_setting('ace.team', true)));
```

`row_security.install` grants it to the team role and gives it the campaign-joined policy on
every start, like every team table.
