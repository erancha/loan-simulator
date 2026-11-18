#!/usr/bin/env bash
# Shared helpers for the loan-simulator scripts: repo paths, help text, the settings files under
# scripts/lib/, compose access, and venv provisioning for the engine and the agent.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENGINE="$ROOT/mcp-server"
ENGINE_VENV="$ENGINE/.venv"
BACKEND="$ROOT/backend"
BACKEND_VENV="$BACKEND/.venv"
FRONTEND="$ROOT/frontend"
# The stack's settings: stack-params.sh is committed; params.sh (this deployment's own settings)
# and secrets.sh are gitignored and created by init-env.sh from their .example.sh files.
STACK_PARAMS_FILE="$ROOT/scripts/lib/stack-params.sh"
PARAMS_FILE="$ROOT/scripts/lib/params.sh"
SECRETS_FILE="$ROOT/scripts/lib/secrets.sh"
# The deploying user's AWS credentials and region, read only for the EC2 target.
AWS_CONFIG_FILE="$ROOT/scripts/lib/aws-config.sh"
# The Compose files of the target: docker-compose.yml alone on this machine; use_ec2 of
# lib/ec2.sh adds the instance's override.
COMPOSE_FILES=("$ROOT/docker-compose.yml")
# Print the calling script's header comment block as --help text (single source of usage docs).
print_help() { awk 'NR==1 {next} /^#/ {sub(/^# ?/, ""); print; next} {exit}' "$0"; }

# shellcheck source=lib/settings-guard.sh
source "$ROOT/scripts/lib/settings-guard.sh"
# shellcheck source=lib/ec2.sh
source "$ROOT/scripts/lib/ec2.sh"

# Exports every setting of the three files into this shell, which is where docker compose takes
# the ${...} values and each service's keys from. Stops when a gitignored file is missing, when
# git tracks it, or when a tracked file holds one of its secrets or addresses.
load_settings() {
  # shellcheck source=lib/stack-params.sh
  source "$STACK_PARAMS_FILE"
  source_checked_file "$PARAMS_FILE" assert_addresses_untracked
  source_checked_file "$SECRETS_FILE" assert_secrets_untracked
  # The preview runs on production's instance: production's own when production is the host, else
  # the instance production is a guest on.
  if [[ "${DEPLOY_PREVIEW:-}" == 1 ]]; then
    export HOST_STACK_NAME="${EC2_HOST_STACK:-$EC2_STACK}"
  fi
}

# Adds each listed setting that is blank or still its example's <placeholder> to
# MISSING_SETTINGS, with the file under scripts/lib/ that sets it, so one run names them all.
MISSING_SETTINGS=()
collect_missing_settings() {  # file key...
  local file="$1" key
  shift
  for key in "$@"; do
    [[ -n "${!key:-}" && "${!key}" != "<"*">" ]] || MISSING_SETTINGS+=("$key ($file)")
  done
}

# Stops when collect_missing_settings found any, listing every one of them.
require_collected_settings() {
  [ "${#MISSING_SETTINGS[@]}" -eq 0 ] && return
  echo "Fill in these settings under scripts/lib/, then run the script again:" >&2
  printf '  %s\n' "${MISSING_SETTINGS[@]}" >&2
  exit 1
}

require_docker() {
  docker info >/dev/null 2>&1 \
    || { echo "Docker is not reachable; start it and retry." >&2; exit 1; }
}

# Compose reads the ${...} values and the keys each service lists in its environment from this
# shell, so the settings are loaded first, with the build the agent image's page names.
compose() {
  load_settings
  local build_info line
  build_info="$("$ROOT/scripts/lib/build-info.sh")"
  while IFS= read -r line; do export "$line"; done <<< "$build_info"
  local file
  local -a files=()
  for file in "${COMPOSE_FILES[@]}"; do files+=(-f "$file"); done
  (cd "$ROOT" && docker compose "${files[@]}" "$@")
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
