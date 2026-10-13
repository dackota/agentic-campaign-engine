# Each start adds the columns the models have and the database lacks

Date: 2026-10-13. Status: proposed (#84).

## Decision

- `make_engine` brings an existing database up to the models at every start of the API, the
  worker, and the learnings MCP server. After `create_all` (missing tables), it compares each
  model table's columns with the live table and adds each missing column, with its type,
  NOT NULL, and server default as the model declares them. Then it adds every index the
  models declare that the database lacks. Every name in its DDL is quoted.
- It only adds. It never drops, renames, or retypes a column, and it never writes a row. A
  column left in the database after it left the models stays.
- One process does this at a time (a Postgres advisory lock), because the API and the worker
  start together.
- (Landed by ticket 02, not 01.) A column the database cannot add with the rows it holds (NOT NULL with no server default,
  on a table with rows) stops the start with an error that names `table.column`. The api pod
  stays unready and `make up` fails at the Helm wait. Nothing is half-changed: the step runs
  in one transaction.
- No Alembic. No migration scripts, no version table.

## Rules for a model change

- A new column on an existing table is nullable or has a `server_default`.
- A new foreign key or unique constraint on an existing table ships its own SQL in the ticket.
  The start does not add constraints.
- Dropping, renaming, or retyping a column is a user decision and ships its own SQL.

## Why

Every column added to a live table so far was additive (notes for #84: `budget_micros`,
`tokens`, `use_step_cache`, `cache_hit`, ...). `create_all` made the tables but not these
columns, so `make up` on an existing cluster gave HTTP 500 until someone ran
`ALTER TABLE ... ADD COLUMN` by hand (#57). An additive comparison at start fixes that class
with the library we already use. Alembic would add a dependency, a baseline for every
existing database, and a script per change, for drops and retypes we do not do.

## Consequences

- `make up` on an existing cluster needs no hand SQL for new tables, columns, grants, or
  policies (`row_security.install` already puts back the grants and policies).
- The hand SQL in [learnings-store.md](learnings-store.md),
  [team-step-limit.md](team-step-limit.md), and [step-cache.md](step-cache.md) is history. It
  is no longer a deploy step.
- A drop or retype still needs a plan of its own.
