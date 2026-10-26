#!/usr/bin/env bash
#
# Run the loan engine in Docker: build the image and start the MCP server, then return once it
# answers.
#
#   ./scripts/start.sh
#
# The engine fetches the market data before it listens, so every start takes a few seconds; when
# a fetch fails it serves the data stored by an earlier start. It listens on 127.0.0.1 at
# ENGINE_HOST_PORT from .env, at /mcp (MCP Inspector, README), and needs the bearer token from
# .env. Requires .env (./scripts/init-env.sh). Stop or inspect it with ./scripts/docker-helper.sh
# (--stop / --logs / --ps).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

case "${1:-}" in -h|--help) print_help; exit 0 ;; "") ;; *) print_help >&2; exit 2 ;; esac

require_env
require_docker
ENGINE_URL="http://127.0.0.1:$(env_value "$ENV_FILE" ENGINE_HOST_PORT)/mcp"

echo "Building and starting the loan engine..."
compose up -d --build
wait_for_http "$ENGINE_URL" \
  || { echo "the engine did not answer on $ENGINE_URL; see ./scripts/docker-helper.sh --logs" >&2
       exit 1; }
echo "The engine answers at $ENGINE_URL (bearer token: ENGINE_BEARER_TOKEN in .env)."
echo "  stop it or tail logs:  ./scripts/docker-helper.sh --stop | --logs"
