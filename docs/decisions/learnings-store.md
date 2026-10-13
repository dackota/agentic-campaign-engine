# Decision: the learnings store (S9)

Date: 2026-10-12. Status: accepted.

## Decision

A called A/B winner becomes one learning: the winning email's subject, preheader and call
to action, the reason it won (opens per variant and the confidence), the metrics, the source
campaign, and an embedding in a pgvector `vector(256)` column (`ace_engine/learnings.py`,
table `learnings`). The research and writer agents search learnings through the read-only
MCP tool `search_learnings` before they write. Approvers delete a bad learning in the app.

## Choices the ticket left open

- **When a learning is made.** The Marketo activity webhook records each open, then asks the
  A/B check (`campaign_api/ab_result.py`) whether it can call a winner. The first time it
  can, the learning is written. A unique key on the campaign keeps it to one per campaign.
  If the embedding call fails, the activity is kept and the next open tries again.
- **Team scope.** The table belongs to a campaign, so row-level security scopes it like
  every other campaign table: no new policy code. The API reads and deletes through
  `row_security.for_team`. The MCP server cannot tell which team an agent works for, so it
  runs once per team (`ace-mcp-learnings-<team>`, `ACE_TEAM`), and each team's
  RemoteMCPServer copy points at its own server (the team overlay patches the URL). The copy
  in the kagent namespace reads as no team and finds nothing.
- **Embeddings.** At live depth, `GatewayEmbedder` posts to the gateway's OpenAI-shaped
  `/embeddings` route and asks for 256 dimensions. At fast depth, or with no embedding URL
  or model set, a fixed stand-in is used: each word is hashed into one of 256 positions,
  and the vector is scaled to unit length. Texts that share words land close together, so
  search works in tests without a model. OpenCode Go lists no embedding model (checked
  2026-10-12, docs/sources.md), so the chart leaves the embedding URL and model blank until
  the gateway gets an embedding backend.
- **Search order.** Cosine distance (`<=>`), and the newest learning first among equals.
  Five results.
- **Who deletes.** The approve role. Owners and viewers read only.
- **Delete keeps a tombstone.** A delete sets `deleted_at`; the view and the search skip
  such rows. The audience keeps opening a sent campaign, and each open asks whether to make
  the learning, so a row that was really deleted would come straight back.
- **Postgres image.** `pgvector/pgvector:0.8.1-pg16` replaces `postgres:16-alpine` in the
  chart and the test harness. The API runs `CREATE EXTENSION IF NOT EXISTS vector` at start.

## Live database

Each start now applies this (`make_engine` adds the table, `row_security.install` the grant
and policy): [additive-schema-at-start.md](additive-schema-at-start.md).

`Base.metadata.create_all` creates the new table but never adds columns. For the
end-of-batch deploy, the additive SQL is:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS learnings (
  id uuid PRIMARY KEY,
  campaign_id uuid NOT NULL REFERENCES campaigns (id) UNIQUE,
  text text NOT NULL,
  reason text NOT NULL,
  metrics json NOT NULL,
  embedding vector(256) NOT NULL,
  created_at timestamptz NOT NULL,
  deleted_at timestamptz
);
ALTER TABLE learnings ENABLE ROW LEVEL SECURITY;
CREATE POLICY learnings_by_team ON learnings TO ace_team
  USING (EXISTS (SELECT 1 FROM campaigns c WHERE c.id = campaign_id
                 AND c.team = current_setting('ace.team', true)))
  WITH CHECK (EXISTS (SELECT 1 FROM campaigns c WHERE c.id = campaign_id
                      AND c.team = current_setting('ace.team', true)));
GRANT SELECT, INSERT, UPDATE, DELETE ON learnings TO ace_team;
```

The API's start runs the same policy and grant (`row_security.install`).

The image swap moves the database from musl (Alpine) to glibc (Debian). Text indexes built
under one C library's collation can sort wrong under the other, so the live volume needs a
`REINDEX DATABASE ace` after the swap, or a fresh volume.
