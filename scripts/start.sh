#!/usr/bin/env bash
#
# Run the loan simulator in Docker: build the images and start Postgres, the migration, the engine
# and the agent, then return once the agent answers.
#
#   ./scripts/start.sh
#
# The migration runs once before the agent starts. The engine fetches the market data before it
# listens, so every start takes a few seconds; when a fetch fails it serves the data stored by an
# earlier start. Published on this machine's loopback interface: the agent at
# localhost:AGENT_HOST_PORT (/health, /ready, /api; localhost is the origin Google sign-in is
# registered for), the engine at ENGINE_URL (MCP Inspector, with the bearer token from .env) and
# Postgres at 127.0.0.1:DB_HOST_PORT. The agent refuses to start when LLM_MODEL, LLM_API_KEY or
# GOOGLE_CLIENT_ID is blank, so the script checks them first, with the other keys the agent needs,
# and names any that an older .env lacks.
# Requires .env (./scripts/init-env.sh). Stop or inspect the stack with
# ./scripts/docker-helper.sh (--stop / --logs / --ps).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

case "${1:-}" in -h|--help) print_help; exit 0 ;; "") ;; *) print_help >&2; exit 2 ;; esac

require_env
require_docker
for key in DATABASE_URL ENGINE_URL ENGINE_BEARER_TOKEN LLM_MODEL LLM_API_KEY GOOGLE_CLIENT_ID; do
  env_value "$ENV_FILE" "$key" >/dev/null
done
ENGINE_URL="$(env_value "$ENV_FILE" ENGINE_URL)"
AGENT_URL="http://localhost:$(env_value "$ENV_FILE" AGENT_HOST_PORT)"

echo "Building and starting the database, the engine and the agent..."
compose up -d --build
wait_for_http "$ENGINE_URL" \
  || { echo "the engine did not answer on $ENGINE_URL; see ./scripts/docker-helper.sh --logs" >&2
       exit 1; }
wait_for_http "$AGENT_URL/health" \
  || { echo "the agent did not answer on $AGENT_URL; see ./scripts/docker-helper.sh --logs" >&2
       exit 1; }
echo "The agent answers at $AGENT_URL (health: /health, ready: /ready)."
echo "The engine answers at $ENGINE_URL (bearer token: ENGINE_BEARER_TOKEN in .env)."
echo "  stop it or tail logs:  ./scripts/docker-helper.sh --stop | --logs"
