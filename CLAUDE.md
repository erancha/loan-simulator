# CLAUDE.md

The loan simulator: a standalone Python MCP server of loan calculations over market data (the
loan engine, `mcp-server/`), which a LangGraph agent in `backend/` calls as a tool provider, and a
Hebrew React page in `frontend/` that the agent serves. Layout, layers and parts:
docs/architecture.md. It is the reference repo of the Docker Compose group. The checkout belongs
on the WSL ext4 filesystem, not under `/mnt/c`; docs/development.md explains the cost.

## Operations scripts (scripts/)

Every script sources `scripts/common.sh`, which exports the three settings files under
`scripts/lib/` before it calls Compose: the committed `stack-params.sh`, and the gitignored
`params.sh` and `secrets.sh`, each beside an `.example.sh` that documents its keys. A bare
`docker compose` call therefore has no settings. `.githooks/pre-commit` refuses a commit that
stages one of the gitignored files, a value of `secrets.sh`, or an address of `params.sh` other
than the license contact (`PUBLISHED_SETTINGS` of `lib/settings-guard.sh`).

- Compose hands each container only the keys it reads, listed once per service, and overrides
  `DATABASE_URL` and `ENGINE_URL` with the in-network addresses, so the files hold the host
  forms. Host commands (pytest, uvicorn) run from the repo root, because the agent reads the
  settings files by their path from the working directory.
- `mcp-server/Dockerfile` and `backend/Dockerfile` build from the repo root context, because
  they copy from `mcp-server/` and `backend/` paths. `backend/Dockerfile` also builds
  `frontend/` in a Node stage and sets `AGENT_FRONTEND_DIST` to the copy in the image. Its
  context leaves out `.git`, so `compose()` passes the version and commit date the landing
  page shows as build arguments, from `scripts/lib/build-info.sh`. The version is the release tag
  (`vMAJOR.MINOR`) plus the commits since it, so a checkout needs the tags.
- The demo page is `frontend/demo.html` with `src/demo/`, not `docs/demo/` as global section 7
  says: it is the real app over a recorded check, so it builds and ships with the page.
  `sql-helper.sh --demo-check <id>` writes its recording.
- The layer rules are enforced by `lint-imports` from each `pyproject.toml`: `loan_engine` is
  `service → market → domain`, with `domain` importing no framework but pydantic; `loan_agent`
  is `platform → application → ports → domain`, with `adapters` implementing the ports, and
  only `application/agent_graph.py` may import `langgraph` and `langchain_core`.
- Money is `Decimal`, never `float`; the page formats it from decimal strings in `money.ts`,
  never through a JS number.
- The MCP SDK is 2.x in the engine (`from mcp.server import MCPServer`, `from mcp import
  Client`; its HTTP client is `httpx2`), while the agent's `langchain-mcp-adapters` requires
  `mcp<2`. The engine and the agent never share a venv: `mcp-server/.venv` and `backend/.venv`
  are separate.
- The checkpoint serializer (`checkpoint_serde` in `platform/checkpointer.py`) passes LangGraph
  an explicit allow-list, `CHECKPOINTED_TYPES`, so it restores LangChain messages natively and
  refuses every other class; a domain class placed in the graph's state must be listed there.
- Before any AWS work, read `/mnt/c/Projects/-- docs --/aws-account-inventory.md`: it holds the
  account's state, its ground rules for credentials and changes, and the decisions made.
- `test.sh [all|engine|backend|frontend]` (aliases `en`, `be`, `fe`) — the whole quality gate:
  bash syntax check, ruff, mypy, import-linter and pytest for `mcp-server/` and `backend/`;
  oxlint, `tsc`, Vitest and the Vite build for `frontend/`.
- `init-env.sh [--force]` — creates each missing gitignored `scripts/lib/secrets.sh`,
  `params.sh` and `aws-config.sh` from its `.example.sh`, with a generated token and database
  password; an existing file is kept unless `--force` is given.
- `deploy.sh` — runs `init-env.sh` first and stops on a list of every required setting still
  blank, then builds and runs Postgres (with its schema migration), the engine and the agent in
  Docker Compose, and returns once the agent answers; `--ec2` does it on the stack's EC2
  instance behind CloudFront (`template-ec2.yaml`, `docker-compose.ec2.yml`), in the account of
  the gitignored `lib/aws-config.sh`.
- `docker-helper.sh [--ec2]` — `--stop [--volumes]`, `--logs [-e]`, `--ps`; `--ec2
  --delete-stack` deletes the EC2 stack and leaves its disk.
- `lib/ec2.sh` — the EC2 target: the stack's deploy, SSH with an Instance Connect key, Compose
  against the instance's daemon. `lib/settings-guard.sh` — the checks behind the pre-commit
  hook.
- `tools/sql-helper.sh [--ec2]` — psql on the stack's database; `--counts`, `--rows`,
  `--backup <file>`, `--restore <file>`, `--people`, `--reset <account-id>`, `--reset-all`.
- `tools/lock.sh` — recompiles each component's `requirements.txt` inside its Dockerfile's
  Python image after editing a dependency list.
