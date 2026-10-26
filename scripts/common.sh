#!/usr/bin/env bash
# Shared helpers for the loan-simulator scripts: repo paths, help text, .env and compose access,
# and engine venv provisioning.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENGINE="$ROOT/mcp-server"
ENGINE_VENV="$ENGINE/.venv"
ENV_FILE="$ROOT/.env"
COMPOSE_FILE="$ROOT/docker-compose.yml"
# Print the calling script's header comment block as --help text (single source of usage docs).
print_help() { awk 'NR==1 {next} /^#/ {sub(/^# ?/, ""); print; next} {exit}' "$0"; }

require_env() {
  [ -f "$ENV_FILE" ] || { echo ".env not found; create it first:  ./scripts/init-env.sh" >&2; exit 1; }
}

require_docker() {
  docker info >/dev/null 2>&1 \
    || { echo "Docker is not reachable; start it and retry." >&2; exit 1; }
}

# --env-file makes the .env values available to the ports mapping's interpolation.
compose() {
  (cd "$ROOT" && docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@")
}

# The value of KEY in an env file (the last assignment); fails loudly when it is absent or blank.
env_value() {  # file key
  local value
  value="$(sed -n "s/^$2=//p" "$1" | tail -n 1)"
  [ -n "$value" ] || { echo "$2 has no value in $1" >&2; exit 1; }
  printf '%s' "$value"
}

# Waits up to about a minute until the URL answers with any HTTP status; the engine's /mcp answers
# 401 without its token, which still shows it is serving.
wait_for_http() {  # url
  curl -s --retry 60 --retry-all-errors --retry-delay 1 --max-time 2 -o /dev/null "$1"
}

# The venv holds the runtime dependencies at the exact pins the image installs (requirements.txt
# as a constraint), so the suite runs on what ships; the dev tools float within pyproject.toml. It
# is current only when installed from both files as they stand now: the stamp is a copy taken
# after the last successful install, so editing either forces a reinstall. The import and
# executable probe still catches a venv broken with the stamp intact.
ensure_engine_venv() {
  [ -d "$ENGINE_VENV" ] || python3 -m venv "$ENGINE_VENV"
  local stamp="$ENGINE_VENV/.dependencies.stamp"
  if ! cat "$ENGINE/pyproject.toml" "$ENGINE/requirements.txt" | cmp -s - "$stamp" \
     || ! { "$ENGINE_VENV/bin/python" -c "import loan_engine" 2>/dev/null \
            && [ -x "$ENGINE_VENV/bin/uvicorn" ] && [ -x "$ENGINE_VENV/bin/pytest" ]; }; then
    echo "Installing engine dependencies into mcp-server/.venv..."
    ( cd "$ENGINE" && "$ENGINE_VENV/bin/pip" install --quiet --disable-pip-version-check \
        --constraint requirements.txt -e ".[dev]" )
    cat "$ENGINE/pyproject.toml" "$ENGINE/requirements.txt" > "$stamp"
  fi
}
