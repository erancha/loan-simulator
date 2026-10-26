# CLAUDE.md

The loan simulator: a standalone Python MCP server of loan calculations over market data (the
loan engine), which a LangGraph agent will call as a tool provider (the agent is OPEN, not yet
implemented). The design is in
`docs/superpowers/specs/2026-10-26-loan-simulator-design.md`.

## Layout and the layer rule

Package `loan_engine` in `mcp-server/src`: `service → market → domain`. `domain` holds pure loan
calculations and imports no framework (pydantic is allowed: its models are the tool schemas);
`market` fetches and stores market data series; `service` is the MCP server, configuration and
startup. `lint-imports` enforces this from `mcp-server/pyproject.toml`.

## Scripts

- `./scripts/lock.sh`: recompile `mcp-server/requirements.txt` inside the Dockerfile's Python
  image after editing the dependency list; the test venv installs under its pins.
- `./scripts/test.sh [all|engine]` (alias `en`; `all` is the default target): bash syntax check of
  the scripts, ruff lint and format check, mypy, import-linter and pytest for `mcp-server/`.
- `./scripts/init-env.sh`, `./scripts/start.sh`, `./scripts/docker-helper.sh`: create `.env` with a
  generated token, run the engine in Docker Compose, and stop it or read its logs.

## Docker

`mcp-server/Dockerfile` builds from the repo root context, because it copies from `mcp-server/`
paths; `docker-compose.yml` sets `context: .` and `dockerfile: mcp-server/Dockerfile`. Settings
come from `.env` at the repo root (`.env.example` beside it documents every key).

## Facts that bite

- Money is `Decimal`, never `float`.
- The MCP SDK is 2.x (`from mcp.server import MCPServer`, `from mcp import Client`; its HTTP client
  is `httpx2`), while `langchain-mcp-adapters` requires `mcp<2`, so the agent will need a venv of
  its own, never the server's.
