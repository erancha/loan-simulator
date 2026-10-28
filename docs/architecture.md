# Architecture

How the loan simulator is built, and why. This page maps what the repo holds and marks what it
does not yet. Formulas and policy numbers are in [calculations.md](calculations.md), the market
data in [market-data.md](market-data.md), the agent in
[architecture/agent.md](architecture/agent.md), sign-in in [sign-in.md](sign-in.md), and how each
part is tested in [testing.md](testing.md).

## Parts

| Part | Status |
|---|---|
| Loan engine, `mcp-server/` | Implemented. |
| Agent, `backend/` | Implemented: [architecture/agent.md](architecture/agent.md). |
| Page, `frontend/` | OPEN — not yet implemented. |
| Evals | OPEN — not yet implemented. |

## The loan engine

An MCP server that takes a profile and loans and returns numbers. It stores nothing personal and
receives no sign-in credentials. It serves Streamable HTTP at `/mcp`, stateless, with JSON
responses. The agent is its only caller, and the person's Google token stays with the agent
([sign-in.md](sign-in.md)).

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

## The agent

A FastAPI service in `backend/`, package `loan_agent`, in layers whose imports point inwards only,
enforced by import-linter: `platform → application → ports → domain`, with `adapters`
implementing the ports and never importing `application` or `platform`.

- `domain` holds the profile, check, option and recommendation types and the errors; it imports no
  framework.
- `ports` are the protocols the inner layers call: the engine, the repositories, the event sink
  and bus, token verification.
- `application` holds the agent graph (the only inner-layer module that imports `langgraph`
  and `langchain_core`), the check tools with the guardrail, and the event sink.
- `adapters` implement the ports: the engine client over MCP, Google token verification, Postgres
  repositories, the in-memory event bus and the chat model.
- `platform` is the HTTP API, configuration, logging, the checkpointer, the check runner and the
  composition in `app.py`.

The agent is built here rather than as a hosted assistant (a custom GPT, a Claude project)
because a person saves several options, compares them, and pauses a check to collect offers and
resumes it days later: state the app must own. LangGraph gives the loop that state: the
conversation is a graph whose state is checkpointed to Postgres after every step, so a check
resumes after a restart and a failed turn leaves the conversation where it was. The model leads
the conversation instead of following a scripted flow, at a higher cost per conversation; the
chat model is whichever provider `LLM_MODEL` names, so the model changes without a code change.

How a conversation runs, the guardrail, the turn cap and the events are in
[architecture/agent.md](architecture/agent.md). One Postgres holds the agent's tables and the
LangGraph checkpoints.

## Configuration

Settings come from environment variables, which Compose reads from `.env` at the repo root: the
engine's are `ENGINE_`-prefixed, the agent's are not. Compose hands each container only the keys
it reads, listed once per service in `docker-compose.yml`, so the engine never receives the
agent's model key or database password. A host process started from the repo root reads the same
file. A missing or malformed required setting stops startup, and a blank value counts as missing.
Each key is explained once, in `.env.example`; `mcp-server/tests/test_env_example.py` and
`backend/tests/test_env_example.py` fail when it and the settings differ, each owning its
service's keys, and each service's `test_compose.py` fails when its container receives a key it
does not read. `ENGINE_BEARER_TOKEN` is defined once and read by both services.

## Deployment

`docker-compose.yml` runs four services:

- `engine`, built from the repo root with `mcp-server/Dockerfile`. The `engine-data` volume is
  mounted at `/data` and holds the stored market data across restarts. The Host header allow-list
  (`ENGINE_ALLOWED_HOSTS`) must name every Host value the engine answers.
- `db`, Postgres 16 with the `db-data` volume and a `pg_isready` healthcheck.
- `migrate`, a one-shot run of `alembic upgrade head` from the agent image, after `db` is healthy.
- `agent`, built from the repo root with `backend/Dockerfile`, after `db` is healthy, `migrate` has
  completed and `engine` is healthy (it accepts connections, which is after its market data
  fetch). Compose overrides `DATABASE_URL` and `ENGINE_URL` with the in-network addresses
  (`db:<DB_PORT>`, `engine:<ENGINE_PORT>`); `.env` holds the host forms. Its healthcheck calls
  `/health`.

Three ports are published, each on `127.0.0.1` only through its `.env` variable (the reason is in
the header of `docker-compose.yml`; `backend/tests/test_compose.py` checks it): `ENGINE_HOST_PORT`
for MCP Inspector, `AGENT_HOST_PORT` for the agent's API and `DB_HOST_PORT` for Postgres, 8100 to
8102 as shipped. `./scripts/start.sh` brings the stack up and returns once the engine and the agent
answer.
