# Data model

This document details the storage that [Architecture](architecture.md#storage) summarizes: every
table of the agent's Postgres, its keys and what it holds, the engine's market data file and what
the page keeps in the browser.

## Postgres

One Postgres holds the agent's tables (checks, options, awaiting offers, recommendations, the
event log and the times kept from deleted checks) and the LangGraph checkpoint tables
([ADR 0004](adr/0004-one-postgres-for-records-and-checkpoints.md)). The `migrate` service applies
both before the agent starts ([Workers' responsibilities and flows](workers.md#migrate)). A check
row holds the loan, the confirmed term, the ceiling with its source, and the two finances
figures; there is no per-person record.

Checks and events carry the Google account's `sub` as their `user_id`; options, awaiting offers
and recommendations belong to a check. An `awaiting_offers` row, keyed by its check and its own
id, holds the lender and, as JSON, what the lender quoted (amount, term, stated number, payment),
the type words, the readings with the likely one, and the prime they were priced at; a later save
of the same offer replaces the row and keeps its first time, so the list keeps its order. A clone
copies its source's awaiting offers with its options and recommendation, and
`scripts/tools/sql/reset-people.sql` deletes them with the person's checks.
`./scripts/tools/sql-helper.sh --counts` lists the tables with their row counts.

Each table, with its primary key and its index:

- `checks` (`id`; `user_id`) — the check's loan, term, ceiling with its source, finances, and when
  it was archived.
- `options` (`check_id`, `id`; `check_id`) — one priced track of a check: its loan, source,
  lender, offer date, longest term and the engine's figures.
- `awaiting_offers` (`check_id`, `id`) — an offer waiting for its lender's answer.
- `recommendations` (`check_id`) — the check's recommendation, one per check.
- `check_events` (`check_id`, `seq`; `user_id`, `type`, `created_at`) — the check's append-only
  event log ([Events](architecture/agent.md#events)).
- `deleted_event_times` (`id`; `user_id`, `type`, `created_at`) — the times of a deleted check's
  counted messages (`message.counted`), kept only while the turn cap's window still counts them
  ([Turns and the turn cap](architecture/agent.md#turns-and-the-turn-cap)).

## Market data

The engine's market data is one JSON file, `/data/market.json` in the engine's `engine-data`
volume; [Market data](market-data.md#storage) has its format and how a save replaces it.

## The page

The page keeps only browser conveniences: the sign-in nonce in the tab's `sessionStorage`, and in
`localStorage` the card's width and the day the person last tapped the market-data sample.
