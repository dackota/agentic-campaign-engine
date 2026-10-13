# Decision: turning learnings off for a run (S9)

Date: 2026-10-12. Status: accepted.

## Decision

The learning-curve script turns learnings off by deleting each campaign's learning through
the API as soon as the campaign has settled, before the next campaign starts. The agents
then search an empty store, so no campaign benefits from an earlier one.

## Why

- No change to the engine, the agents, or the MCP server: the smallest option. The proof
  exercises the same code path production uses, with the store empty.
- A delete is a tombstone (docs/decisions/learnings-store.md), so the audience's later opens
  cannot bring the learning back.
- Options passed over: an env flag that makes `search_learnings` return nothing (a code path
  that exists only for the proof), and a second team with its own store (needs another
  approver and cluster setup).

## Cost

A learning exists for a short moment between the winner being called and the delete. The
next campaign only starts after the delete, so no agent can read it.

## Run order

When one invocation runs both sides, the learnings-off side goes first. The learnings-on run
keeps its learnings, so if it went first they would sit in the team's store while the off
run's agents search, and the off baseline would not be clean. Off first leaves the store
empty (each off learning is deleted) when the on run starts. Passed over: on first, which
reads more naturally but contaminates the baseline. The table and chart still list on, then off.
