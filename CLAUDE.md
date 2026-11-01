# CLAUDE.md

The loan simulator: a standalone Python MCP server of loan calculations over market data (the
loan engine), which a LangGraph agent in `backend/` calls as a tool provider (the evals are
OPEN). The page is a Hebrew React app in `frontend/` that the agent serves. The design is
described in `docs/architecture.md` and the pages it links.

## Layout and the layer rule

Package `loan_engine` in `mcp-server/src`: `service → market → domain`. `domain` holds pure loan
calculations and imports no framework (pydantic is allowed: its models are the tool schemas);
`market` fetches and stores market data series; `service` is the MCP server, configuration and
startup. `lint-imports` enforces this from `mcp-server/pyproject.toml`.

Package `loan_agent` in `backend/src`: `platform → application → ports → domain`, with `adapters`
implementing the ports and never importing `application` or `platform`. The inner layers import no
framework; only `application/agent_graph.py` may import `langgraph` and `langchain_core`.
`lint-imports` enforces this from `backend/pyproject.toml`.

The page in `frontend/src`: `api/` (client and types), `auth/`, `shell/` (header, checks list,
tabs), `check/` (event reducer `events.ts`, card mapping `card.ts`, Hebrew text `copy.ts`),
`profile/`. Money is formatted from decimal strings by `money.ts`, never through a JS number.

## Scripts

- `./scripts/lock.sh`: recompile `mcp-server/requirements.txt` and `backend/requirements.txt`
  inside each Dockerfile's Python image after editing a dependency list; each test venv installs
  under the pins of its own lockfile.
- `./scripts/test.sh [all|engine|backend|frontend]` (aliases `en`, `be`, `fe`; `all` is the default
  target): bash syntax check of the scripts, ruff lint and format check, mypy, import-linter and
  pytest for `mcp-server/` and `backend/`; oxlint, `tsc`, Vitest and the Vite build for
  `frontend/`.
- `./scripts/init-env.sh`, `./scripts/start.sh`, `./scripts/docker-helper.sh`: create `.env` with a
  generated token and database password, run Postgres, the migration, the engine and the agent in
  Docker Compose, and stop them or read their logs. `./scripts/sql-helper.sh` runs psql against
  the stack's database.

## Docker

`mcp-server/Dockerfile` and `backend/Dockerfile` build from the repo root context, because they
copy from `mcp-server/` and `backend/` paths; `docker-compose.yml` sets `context: .` and
`dockerfile: mcp-server/Dockerfile` for the engine and `backend/Dockerfile` for the migration and
the agent. Settings come from `.env` at the repo root (`.env.example` beside it documents every
key); compose hands each container only the keys it reads, listed once per service, and overrides
`DATABASE_URL` and `ENGINE_URL` with the in-network addresses, so `.env` holds the host forms.
`backend/Dockerfile` also builds `frontend/` in a Node stage and sets `AGENT_FRONTEND_DIST` to the
copy in the image. `npm run dev` in `frontend/` proxies `/api` to the agent on 8101.
Host commands (pytest, uvicorn) run from the repo root, because the agent reads `.env` from the
working directory.

## AWS

Before any AWS work, read `/mnt/c/Projects/-- docs --/aws-account-inventory.md`: it holds the
account's state, its ground rules for credentials and changes, and the decisions made and still
open. This repo holds only the deployment plan, `docs/superpowers/ec2-lift-and-shift.md`.

## Facts that bite

- Money is `Decimal`, never `float`.
- The MCP SDK is 2.x in the engine (`from mcp.server import MCPServer`, `from mcp import Client`;
  its HTTP client is `httpx2`), while the agent's `langchain-mcp-adapters` requires `mcp<2`. The
  engine and the agent never share a venv: `mcp-server/.venv` and `backend/.venv` are separate.
- The checkpoint serializer (`checkpoint_serde` in `platform/checkpointer.py`) passes LangGraph an
  explicit allow-list, `CHECKPOINTED_TYPES`, so it restores LangChain messages natively and refuses
  every other class whatever the environment says; a domain class placed in the graph's state must
  be listed there.
