# loan-simulator

The loan simulator is a Hebrew-only AI agent that helps a person decide on a short- or
medium-term loan (a car, a renovation, a consumer purchase): how much to borrow, how much savings
to keep, for how long, and on which track. The model leads the conversation and decides what to
ask; code computes every number and sets the bounds the recommendation must respect. The engine
prices each track at what it costs today and at what it would have cost had interest rates or
inflation moved as they did in the worst comparable period on record; the page shows both.

This repo holds the loan engine, the agent and the page. The evals are OPEN, not yet
implemented (#2).

**Contents:** [Architecture](#architecture) · [The loan engine](#the-loan-engine) ·
[The agent](#the-agent) · [The page](#the-page) · [Getting started](#getting-started) ·
[Scripts](#scripts) · [Testing](#testing) · [License](#license)

## Architecture

```mermaid
flowchart LR
  U((Person)) --> P["Page - frontend/<br/>React, Hebrew"]
  P -->|"HTTP API, event stream"| A
  subgraph AGENT[Agent - backend/]
    A["FastAPI and LangGraph loop:<br/>sign-in, profile, checks"] --> DB[(Postgres)]
  end
  A -->|MCP over Streamable HTTP<br/>bearer token| E
  subgraph ENGINE[Loan engine - mcp-server/]
    E["MCP server: tools and rate resources"] --> D[Loan calculations]
    E --> M[(Stored market data)]
  end
  M -.->|daily refresh| S["Bank of Israel and<br/>Central Bureau of Statistics"]
  classDef done fill:#dbeafe,stroke:#1d4ed8,color:#111827
  class P,U,A,DB,E,D,M done
  style AGENT fill:#eff6ff,stroke:#1d4ed8
  style ENGINE fill:#eff6ff,stroke:#1d4ed8
```

The model chooses what to ask and which tool to call; the engine returns the numbers and the
bounds. The engine knows nothing about people and stores nothing personal: it takes a profile and
loans and returns results. Details: [docs/architecture.md](docs/architecture.md); every formula
and policy number with its reasoning: [docs/calculations.md](docs/calculations.md); the market
data sources and what happens when one is down: [docs/market-data.md](docs/market-data.md).

**Stack:** Python, the MCP SDK, LangGraph, FastAPI, SQLAlchemy and Alembic, Postgres, uvicorn,
TypeScript, React, Vite, Docker.

## The loan engine

`mcp-server/` is a standalone Python MCP server of loan calculations over market data.

**Tools**

| Tool | Returns |
|---|---|
| `assess_affordability` | A monthly payment ceiling and a minimum savings cushion from a profile, with reason codes. |
| `size_loan` | The loan amount for a goal price, savings and cushion. |
| `simulate_loan` | A short text summary for the model; the full result, schedule included, as structured content. |
| `shortest_comfortable_term` | The shortest term, in 6-month steps, at which the suggested tracks' worst-case payment stays within 90% of the ceiling. |
| `shortest_comfortable_offer_term` | The same search for one real offer, up to the longest term it allows. |
| `suggest_tracks` | A fixed and a prime track priced from the published average bank rate. |
| `market_series` | Today's prime and, for the latest months, the prime and the CPI's monthly change. |

**Resources:** `rates://boi/history`, `rates://cpi/history` and `rates://current`.

**Market data.** The engine fetches the Bank of Israel rate and the consumer price index before it
listens (the first start takes a few seconds longer), keeps them in the `engine-data` volume, and
refreshes them daily.

## The agent

`backend/` is a FastAPI service that leads a Hebrew conversation with a language model, calls the
engine's tools and its own, and keeps each person's profile, checks, options and recommendation in
Postgres. People sign in with Google ([docs/sign-in.md](docs/sign-in.md)); sign-in is restricted by
the OAuth app's list of test users. The model never produces a figure: every number comes from a
tool result, and `present_recommendation` refuses an option that borrows less than the loan the
engine sized or whose worst-case payment is above the ceiling. A reply streams to the page as it is
written, and a person may send `AGENT_TURN_LIMIT` messages per `AGENT_TURN_WINDOW_HOURS` (20 per 24
hours as shipped), unless `AGENT_TURN_LIMIT_OVERRIDES` sets their own limit. The loop, the tools,
the events and what happens on failure: [docs/architecture/agent.md](docs/architecture/agent.md).

## The page

`frontend/` is a Hebrew, right-to-left React app that the agent serves. A person signs in with
Google, chats with the assistant, corrects their profile in a side panel and reads the
recommendation as a card: the loan amount, term and payment, each option's worst-case payment and
the period it comes from, and the ceiling and cushion behind it. Every figure on the card comes
from stored engine results, never from the model's text. The layout, the data flow and how the
page is served: [docs/architecture/page.md](docs/architecture/page.md).

## Getting started

Requires Docker.

```bash
./scripts/init-env.sh      # creates .env with a generated bearer token and database password
# fill in LLM_MODEL, LLM_API_KEY and GOOGLE_CLIENT_ID in .env (docs/sign-in.md)
./scripts/start.sh         # builds the images, starts Postgres, the migration, the engine and
                           # the agent, and returns once the agent answers
```

Then open `http://localhost:8101`, sign in with a Google account listed as a test user, and start
a check.

Every setting is explained once, in [.env.example](.env.example). The agent refuses to start while
`LLM_MODEL`, `LLM_API_KEY` or `GOOGLE_CLIENT_ID` is blank. Stop the stack, follow its logs or see
its status with `./scripts/docker-helper.sh --stop | --logs | --ps` (`--stop --volumes` also
removes the stored market data and the database).

**Addresses.** Each service has a port inside the Compose network, where the services reach each
other by name, and a port published on this machine's loopback interface only, where you reach
it. As shipped in `.env.example`:

| Service | On this machine | Inside the Compose network |
|---|---|---|
| Agent | `http://localhost:8101` (`AGENT_HOST_PORT`): the page at `/`, `/health`, `/ready`, `/api` | `agent:8000` (`AGENT_PORT`) |
| Engine | `http://localhost:8100/mcp` (`ENGINE_HOST_PORT`), for MCP Inspector | `engine:8020` (`ENGINE_PORT`) |
| Postgres | `127.0.0.1:8102` (`DB_HOST_PORT`), for an agent or a psql run on the host | `db:5432` (`DB_PORT`) |

A published port must be free on this machine; change it in `.env` if it is not. Open the agent as
`localhost`, the origin Google sign-in is registered for; a new `AGENT_HOST_PORT` needs the same
change in the Google client's authorized redirect URI ([docs/sign-in.md](docs/sign-in.md)).

### Try the engine with MCP Inspector

```bash
npx @modelcontextprotocol/inspector
```

The command opens Inspector in the browser.

1. Add a server (or edit the HTTP one Inspector lists) with the transport **streamable-http** and
   the URL `http://localhost:<ENGINE_HOST_PORT>/mcp`.
2. In the server's **Settings**, under **Custom Headers**, add the header `Authorization` with
   the value `Bearer ` followed by `ENGINE_BEARER_TOKEN` from `.env`. Leave the OAuth settings
   empty: the engine takes this one fixed token.
3. Connect with the server's toggle, open **Tools** and pick `simulate_loan`. Its one argument,
   `loan`, takes the tracks of the loan; switch on **Edit as JSON** to paste them. For a loan of
   31,000 ₪ at prime + 2.9, 48 months, unlinked:

   ```json
   {"tracks": [{"principal": "31000", "term_months": 48, "rate_kind": "prime",
                "prime_spread": "2.9", "cpi_linked": false, "method": "spitzer"}]}
   ```

The result's structured content gives today's payment, the peak recurring payment and total,
the balloon due for a balloon track, the worst historical window (the past run of months as long
as the term whose rate and inflation moves give the highest payment) with its start and end
months, the range across all such windows, the schedule, and the data dates the figures rest on:
the Bank of Israel rate of today and the consumer price index of last month or the month before.
Its text content is a short summary of the same figures without the schedule, sized for a
language model's context.

## Scripts

All live in `scripts/`; run with `--help` for full usage.

| Script | Purpose |
|---|---|
| `init-env.sh` | Create `.env` with a generated bearer token and database password; `--force` overwrites an existing one. |
| `start.sh` | Build and start Postgres, the migration, the engine and the agent in Docker, and return once they answer. |
| `docker-helper.sh` | Stop (`--stop`, `--volumes` also removes the market data and the database), follow logs, or show status. |
| `sql-helper.sh` | Run psql against the stack's database: a shell, `-c`, a SQL file, or row counts (`--counts`) and rows (`--rows`) of every table. |
| `lock.sh` | Recompile `mcp-server/requirements.txt` and `backend/requirements.txt` inside each Dockerfile's Python image. |
| `test.sh` | Script syntax, lint, types, import layers and tests for the engine and the backend; lint, types, tests and a build for the page. |

## Testing

```bash
./scripts/test.sh          # every target: the engine, the backend and the page
./scripts/test.sh engine   # lint, types, import layers, tests
./scripts/test.sh backend  # the same for the agent; its database tests need Docker
./scripts/test.sh frontend # lint, types, component tests and a build; needs Node.js 22
```

What each layer proves: [docs/testing.md](docs/testing.md).

## License

Source-available under the [PolyForm Noncommercial License 1.0.0](LICENSE). Reading the source,
forking it and running a private deployment are free for anyone, companies included:
[NOTICE](NOTICE) grants that explicitly for evaluating the project or its author. Building a
commercial product or service on it needs a commercial license: erancha@gmail.com.
