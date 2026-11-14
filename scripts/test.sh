#!/usr/bin/env bash
#
# Run the test suites of the loan simulator.
#
#   ./scripts/test.sh                # every target (default)
#   ./scripts/test.sh all            # every target (explicit)
#   ./scripts/test.sh engine         # the MCP server in mcp-server/  (alias: en)
#   ./scripts/test.sh backend        # the loan agent in backend/  (alias: be)
#   ./scripts/test.sh frontend       # the page in frontend/  (alias: fe)
#
# Targets combine, so several may be given.
#
# The engine and backend targets run: the scripts' syntax check (bash -n), lint and formatting
# (ruff), typecheck (mypy), import-linter layer contracts, and pytest. The frontend target runs
# lint (oxlint), component tests (vitest), then the typecheck (tsc) and production build (vite)
# that npm run build chains.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

usage() {
  echo "Usage: ./scripts/test.sh [all|engine|backend|frontend] ... (aliases: en, be, fe)" >&2
  exit 2
}

RUN_ENGINE=false
RUN_BACKEND=false
RUN_FRONTEND=false
selected=false

for arg in "$@"; do
  case "$(printf '%s' "$arg" | tr '[:upper:]' '[:lower:]')" in
    -h|--help)  print_help; exit 0 ;;
    all)        RUN_ENGINE=true; RUN_BACKEND=true; RUN_FRONTEND=true ;;
    en|engine)  RUN_ENGINE=true ;;
    be|backend) RUN_BACKEND=true ;;
    fe|frontend) RUN_FRONTEND=true ;;
    *) usage ;;
  esac
  selected=true
done

if [ "$selected" = false ]; then
  RUN_ENGINE=true
  RUN_BACKEND=true
  RUN_FRONTEND=true
fi

run_project() {  # label project_dir venv_dir ensure_function
  local label="$1" project="$2" venv="$3" ensure="$4"
  echo "==> $label"
  echo "--> scripts (bash -n)"
  for script in "$ROOT"/scripts/*.sh "$ROOT"/scripts/lib/*.sh "$ROOT"/scripts/tools/*.sh \
      "$ROOT/.githooks/pre-commit"; do
    bash -n "$script"
  done
  "$ensure"
  echo "--> lint (ruff)"
  ( cd "$project" && "$venv/bin/ruff" check src tests )
  echo "--> format (ruff format --check)"
  ( cd "$project" && "$venv/bin/ruff" format --check src tests )
  echo "--> typecheck (mypy)"
  ( cd "$project" && "$venv/bin/mypy" )
  echo "--> import-linter (layer contracts)"
  ( cd "$project" && "$venv/bin/lint-imports" )
  echo "--> pytest"
  ( cd "$project" && "$venv/bin/pytest" )
}

run_frontend() {
  echo "==> Frontend"
  command -v npm >/dev/null 2>&1 \
    || { echo "npm not found; install Node.js 22 and retry." >&2; exit 1; }
  # npm ci installs the lockfile verbatim; npm install may re-resolve and mutate it. npm writes
  # node_modules/.package-lock.json on install, so a lockfile newer than it was edited since.
  if [ ! "$FRONTEND/node_modules/.package-lock.json" -nt "$FRONTEND/package-lock.json" ]; then
    ( cd "$FRONTEND" && npm ci --no-audit --no-fund )
  fi
  echo "--> lint (oxlint)"
  ( cd "$FRONTEND" && npm run --silent lint )
  echo "--> component tests (vitest)"
  ( cd "$FRONTEND" && npm run --silent test )
  echo "--> typecheck and build (tsc -b, vite build)"
  ( cd "$FRONTEND" && npm run --silent build )
}

if [ "$RUN_ENGINE" = true ]; then
  run_project Engine "$ENGINE" "$ENGINE_VENV" ensure_engine_venv
fi
if [ "$RUN_BACKEND" = true ]; then
  run_project Backend "$BACKEND" "$BACKEND_VENV" ensure_backend_venv
fi
if [ "$RUN_FRONTEND" = true ]; then
  run_frontend
fi

echo "All requested tests passed."
