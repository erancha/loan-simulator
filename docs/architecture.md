# Architecture

How the loan simulator is built, and why. The design as a whole is in
[the design document](superpowers/specs/2026-10-26-loan-simulator-design.md); this page maps what
the repo holds and marks what it does not yet. Formulas and policy numbers are in
[calculations.md](calculations.md), the market data in [market-data.md](market-data.md), and how
each part is tested in [testing.md](testing.md).

## Parts

| Part | Status |
|---|---|
| Loan engine, `mcp-server/` | Implemented. |
| Agent, `backend/` | OPEN — not yet implemented. |
| Page, `frontend/` | OPEN — not yet implemented. |
| Evals | OPEN — not yet implemented. |

## The loan engine

An MCP server that takes a profile and loans and returns numbers. It stores nothing personal and
receives no sign-in credentials. It serves Streamable HTTP at `/mcp`, stateless, with JSON
responses. The agent will be its only caller, and the person's Google token (sign-in is OPEN, not
yet implemented) will stay with the agent.

One package, `loan_engine`, in three layers whose imports point inwards only, enforced by
import-linter:

- `domain` holds the loan model, schedules, the historical replay and the policy as pure
  calculations. Money is `Decimal`; values leave the server rounded to agorot.
- `market` fetches the Bank of Israel rate, the consumer price index and the Bank of Israel average
  consumer-loan rate, aligns them into a monthly history and keeps the last good copy on disk.
- `service` is the MCP server, configuration, the bearer-token check and startup.

Startup refreshes the market data once, then serves and refreshes daily side by side. With no
fetchable data and none stored, or when a daily refresh raises, the process exits with the error
rather than serving without data.

## Configuration

Settings come from `ENGINE_`-prefixed environment variables, which Compose reads from `.env` at the
repo root. A missing or malformed required setting stops startup. Each key is explained once, in
`.env.example`; `test_env_example.py` fails when it and the settings differ.

## Deployment

`docker-compose.yml` runs one service, `engine`, built from the repo root with
`mcp-server/Dockerfile`. The `engine-data` volume is mounted at `/data` and holds the stored market
data across restarts. The agent will reach the engine at `engine:<ENGINE_PORT>` inside the Compose
network; the one published port, `ENGINE_HOST_PORT` on `127.0.0.1`, serves MCP Inspector and binds
to the loopback interface only (`test_compose.py`). The Host header allow-list
(`ENGINE_ALLOWED_HOSTS`) must name every Host value the engine answers.
