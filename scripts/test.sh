#!/usr/bin/env bash
#
# Run the test suites of the loan simulator.
#
#   ./scripts/test.sh                # every target (default)
#   ./scripts/test.sh all            # every target (explicit)
#   ./scripts/test.sh engine         # the MCP server in mcp-server/  (alias: en)
#   ./scripts/test.sh backend        # the loan agent in backend/  (alias: be)
#
# Targets combine, so several may be given.
#
# Each target runs: the scripts' syntax check (bash -n), lint and formatting (ruff), typecheck
# (mypy), import-linter layer contracts, and pytest.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

usage() {
  echo "Usage: ./scripts/test.sh [all|engine|backend] ... (aliases: en, be)" >&2
  exit 2
}

RUN_ENGINE=false
RUN_BACKEND=false
selected=false

for arg in "$@"; do
  case "$(printf '%s' "$arg" | tr '[:upper:]' '[:lower:]')" in
    -h|--help)  print_help; exit 0 ;;
    all)        RUN_ENGINE=true; RUN_BACKEND=true ;;
    en|engine)  RUN_ENGINE=true ;;
    be|backend) RUN_BACKEND=true ;;
    *) usage ;;
  esac
  selected=true
done

if [ "$selected" = false ]; then
  RUN_ENGINE=true
  RUN_BACKEND=true
fi

run_project() {  # label project_dir venv_dir ensure_function
  local label="$1" project="$2" venv="$3" ensure="$4"
  echo "==> $label"
  echo "--> scripts (bash -n)"
  for script in "$ROOT"/scripts/*.sh; do bash -n "$script"; done
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

if [ "$RUN_ENGINE" = true ]; then
  run_project Engine "$ENGINE" "$ENGINE_VENV" ensure_engine_venv
fi
if [ "$RUN_BACKEND" = true ]; then
  run_project Backend "$BACKEND" "$BACKEND_VENV" ensure_backend_venv
fi

echo "All requested tests passed."
