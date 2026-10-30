#!/usr/bin/env bash
# Shared helpers for the loan-simulator scripts: repo paths, help text, .env and compose access,
# and venv provisioning for the engine and the agent.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENGINE="$ROOT/mcp-server"
ENGINE_VENV="$ENGINE/.venv"
BACKEND="$ROOT/backend"
BACKEND_VENV="$BACKEND/.venv"
FRONTEND="$ROOT/frontend"
ENV_FILE="$ROOT/.env"
COMPOSE_FILE="$ROOT/docker-compose.yml"
# Print the calling script's header comment block as --help text (single source of usage docs).
print_help() { awk 'NR==1 {next} /^#/ {sub(/^# ?/, ""); print; next} {exit}' "$0"; }

require_env() {
  [ -f "$ENV_FILE" ] \
    || { echo ".env not found; create it first:  ./scripts/init-env.sh" >&2; exit 1; }
}

require_docker() {
  docker info >/dev/null 2>&1 \
    || { echo "Docker is not reachable; start it and retry." >&2; exit 1; }
}

# --env-file makes the .env values available to the ${...} interpolation and to the keys each
# service lists in its environment.
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

# A project's venv holds the runtime dependencies at the exact pins the image installs
# (requirements.txt as a constraint), so the suite runs on what ships; the dev tools float within
# pyproject.toml. It is current only when installed from both files as they stand now: the stamp is
# a copy taken after the last successful install, so editing either forces a reinstall. The import
# and executable probe still catches a venv broken with the stamp intact. The engine and the agent
# never share a venv: their mcp majors differ.
ensure_venv() {  # project_dir venv_dir import_name server_executable
  local project="$1" venv="$2" module="$3" executable="$4"
  [ -d "$venv" ] || python3 -m venv "$venv"
  local stamp="$venv/.dependencies.stamp"
  if ! cat "$project/pyproject.toml" "$project/requirements.txt" | cmp -s - "$stamp" \
     || ! { "$venv/bin/python" -c "import $module" 2>/dev/null \
            && [ -x "$venv/bin/$executable" ] && [ -x "$venv/bin/pytest" ]; }; then
    echo "Installing dependencies into ${project#"$ROOT"/}/.venv..."
    ( cd "$project" && "$venv/bin/pip" install --quiet --disable-pip-version-check \
        --constraint requirements.txt -e ".[dev]" )
    cat "$project/pyproject.toml" "$project/requirements.txt" > "$stamp"
  fi
}

ensure_engine_venv() { ensure_venv "$ENGINE" "$ENGINE_VENV" loan_engine uvicorn; }
ensure_backend_venv() { ensure_venv "$BACKEND" "$BACKEND_VENV" loan_agent uvicorn; }
