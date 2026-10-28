# Testing

What each layer of tests proves, and how to run it.

```bash
./scripts/test.sh            # every target (engine and backend)
./scripts/test.sh engine     # script syntax, ruff lint and format, mypy, import-linter, pytest
./scripts/test.sh backend    # the same gates for the agent
```

No test reaches the Bank of Israel or the Central Bureau of Statistics: fetchers run against
recorded responses, and the server against stored histories built in the tests. No test reaches
Google or a model provider either: tests sign their own tokens and script the chat model. The
Postgres tests start a `postgres:16` container through testcontainers, so the backend target needs
Docker.

## Engine

**Static gates** fail the run before any test: `bash -n` on every script, ruff lint, ruff format
in check mode, mypy, and the import-linter contracts that keep `service → market → domain`
pointing inwards.

**Domain** tests run on plain values: schedules for each repayment method with changing rates and
CPI, the historical replay and its worst window, and the policy bounds, each against hand-computed
figures from [calculations.md](calculations.md).

**Market** tests drive the parsers with recorded Bank of Israel and CBS responses, the monthly
alignment, the stored-series fallback when a source fails, and the failure when nothing is stored
([market-data.md](market-data.md)).

**Service** tests call the tools and resources through an MCP client against the real HTTP app:
the bearer token is required, the host allow-list holds, results are rounded to agorot, and
startup and the daily refresh fail loudly.

**Deployment files** are checked without Docker: `test_env_example.py` requires `.env.example` to
document every engine setting and no other `ENGINE_` key (the agent's test owns the rest), and
`init-env.sh` to write settings the engine accepts and to leave no `.env` when a written value
fails its check; `test_compose.py` requires that the engine's published port binds to `127.0.0.1`
through the `ENGINE_HOST_PORT` and `ENGINE_PORT` variables, that the market data volume is mounted
and that the engine's container receives only its own keys; and `test_requirements_lock.py`
requires the lock to match `pyproject.toml` and the image.

## Backend

**Static gates** are the same as the engine's: `bash -n`, ruff, mypy and import-linter contracts
that keep `platform → application → ports → domain` pointing inwards, adapters off `application`
and `platform`, and the inner layers free of frameworks, except `langgraph` and `langchain_core`
in `application/agent_graph.py`.

**Domain and application** tests run on plain values and fakes: the profile's missing fields and
staleness, the option figures' JSON encoding, the check tools, and the guardrail's refusals (no
loan needed, principal below the sized loan, a sized loan beyond the engine's maximum, worst-case
payment above the ceiling), each with the message the model reads. The agent graph runs against a
scripted fake chat model, which proves tool wiring, that every tool the system prompt names is
bound, the model's retry after a refusal, resuming a saved conversation, and that the person's ID
token never reaches a checkpoint (a test scans every saved blob).

**Adapters** tests cover the engine client against a stub MCP server, Google token verification
against tokens signed in the tests, and the Postgres repositories on a real database.

**Platform** tests drive the HTTP API through the real app with fake infrastructure: sign-in and
the 401 answer on every route outside a short public list and the 404 answers, profile and check
routes, the event stream's replay, Last-Event-ID resume and its dropping of fragments the replay
already sent complete, the turn cap and conflict answers, the runner's streaming and failure
events, a turn after a model failure, the turn step limit, restart recovery, settings validation,
and that the migration builds the tables, matches the ORM and downgrades.

**Deployment files** are checked without Docker, as for the engine: each service's
`test_env_example.py` requires `.env.example` to document its keys and nothing else (together every
key is owned once) and `init-env.sh` to write settings the services accept;
`backend/tests/test_compose.py` requires every published port to bind to `127.0.0.1` through its
variable, the agent to wait for the database, the migration and the engine, and each container to
receive only the keys it reads.

**Not covered here.** A Hebrew conversation against a real model needs `LLM_MODEL`, `LLM_API_KEY`
and `GOOGLE_CLIENT_ID`; it is run by hand after `./scripts/start.sh`. The page and the evals
(recorded personas judged by a model, run on demand because they cost money) are OPEN, not yet
implemented.
