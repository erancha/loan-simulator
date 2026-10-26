#!/usr/bin/env bash
#
# Run the test suites of the loan simulator.
#
#   ./scripts/test.sh                # every target (default)
#   ./scripts/test.sh all            # every target (explicit)
#   ./scripts/test.sh engine         # the MCP server in mcp-server/  (alias: en)
#
# Targets combine, so several may be given.
#
# Engine: the scripts' syntax check (bash -n), lint and formatting (ruff), typecheck (mypy),
# import-linter layer contracts, and pytest.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

usage() {
  echo "Usage: ./scripts/test.sh [all|engine] ... (aliases: en)" >&2
  exit 2
}

RUN_ENGINE=false
selected=false

for arg in "$@"; do
  case "$(printf '%s' "$arg" | tr '[:upper:]' '[:lower:]')" in
    -h|--help)  print_help; exit 0 ;;
    all)        RUN_ENGINE=true ;;
    en|engine)  RUN_ENGINE=true ;;
    *) usage ;;
  esac
  selected=true
done

if [ "$selected" = false ]; then
  RUN_ENGINE=true
fi

run_engine() {
  echo "==> Engine"
  echo "--> scripts (bash -n)"
  for script in "$ROOT"/scripts/*.sh; do bash -n "$script"; done
  ensure_engine_venv
  echo "--> lint (ruff)"
  ( cd "$ENGINE" && "$ENGINE_VENV/bin/ruff" check src tests )
  echo "--> format (ruff format --check)"
  ( cd "$ENGINE" && "$ENGINE_VENV/bin/ruff" format --check src tests )
  echo "--> typecheck (mypy)"
  ( cd "$ENGINE" && "$ENGINE_VENV/bin/mypy" )
  echo "--> import-linter (layer contracts)"
  ( cd "$ENGINE" && "$ENGINE_VENV/bin/lint-imports" )
  echo "--> pytest"
  ( cd "$ENGINE" && "$ENGINE_VENV/bin/pytest" )
}

if [ "$RUN_ENGINE" = true ]; then run_engine; fi

echo "All requested tests passed."
