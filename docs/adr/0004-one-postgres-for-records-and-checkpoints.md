# 0004. One Postgres holds the agent's records and its checkpoints

- Status: Accepted
- Date: 2026-10-28

## Context

The agent keeps each person's profile, checks, saved options, recommendation and an event log
the page replays, and LangGraph needs a store for the conversation checkpoints
([ADR 0003](0003-model-led-agent-with-a-code-guardrail.md)). A deletion must remove a check's
records and its conversation together, and the stack runs on one machine under Docker Compose.

## Decision

- One Postgres 16 (the `db` service) holds the agent's tables and LangGraph's checkpoint tables.
- The agent reaches its tables through SQLAlchemy; Alembic migrates them, and the same migration
  step brings the checkpoint tables to the installed library's version.
- A one-shot `migrate` service applies both before the agent starts, so agent processes never
  race on a schema change.
- Profiles, checks and events carry the Google account's `sub` as their `user_id`; options and
  a recommendation belong to a check.

## Consequences

- One backup and one connection setting cover all of the agent's state.
- The tests run the repositories and the migration against a real Postgres through
  Testcontainers, so the backend's tests need Docker.
- The engine keeps its market data apart, as a JSON file in its own volume, since it stores
  nothing personal.
