# Design patterns

This document details the shapes the code repeats behind
[Architecture](architecture.md#codebase-structure): how each Python package is layered and how
the layering is enforced.

## Layers whose imports point inwards

The engine and the agent are each one package in layers whose imports point inwards only,
enforced by import-linter from each `pyproject.toml`, so a layer's rules hold however the code
grows.

The engine, `loan_engine`, is `service → market → domain`:

- `domain` holds the loan model, schedules, the historical replay, the term and loan searches
  (`policy`) and the loans a vaguely worded offer may mean (`readings`) as pure calculations. The
  household ceiling formula sits apart in `affordability`, and an import-linter contract keeps
  `policy`, `history`, `schedule` and `readings` from importing it, so no loan figure depends on
  the person's finances. Money is `Decimal`; values leave the server rounded to agorot.
- `market` fetches the Bank of Israel rate, the consumer price index and the Bank of Israel average
  consumer-loan rate, aligns them into a monthly history and keeps the last good copy on disk.
- `service` is the MCP server, configuration, the bearer-token check and startup.

The agent, `loan_agent`, is `platform → application → ports → domain`, with `adapters`
implementing the ports and never importing `application` or `platform`.

- `domain` holds the check (with its loan, term, ceiling and finances), option, awaiting offer,
  reading and recommendation types and the errors; it imports no framework.
- `ports` are the protocols the inner layers call: the engine, the repositories, the event sink
  and bus, token verification.
- `application` holds the agent graph (the only inner-layer module that imports `langgraph`
  and `langchain_core`), the check tools with the guardrail, the choice between the readings of
  an offer described in words (`application/offer_reading.py`), and the event sink.
- `adapters` implement the ports: the engine client over MCP, Google token verification, Postgres
  repositories, the in-memory event bus and the chat model.
- `platform` is the HTTP API, configuration, logging, the checkpointer, the check runner and the
  composition in `app.py`.
