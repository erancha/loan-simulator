#!/usr/bin/env bash
#
# Docker Compose helper for the engine: teardown, logs, status. Bringing it up is start.sh's job.
#
#   ./scripts/docker-helper.sh --stop [--volumes]
#       Stop and remove the engine's container and network. The engine-data volume is KEPT by
#       default so the stored market data survives a restart; --volumes (alias -v) also removes it.
#   ./scripts/docker-helper.sh --logs [-e|--errors]
#       Follow the engine's logs live (last 200 lines). -e filters to ERROR/EXCEPTION/FATAL lines.
#   ./scripts/docker-helper.sh --ps
#       Show the engine's container status.
#   -h, --help
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

do_stop() {
  local -a down=(down --remove-orphans)
  while [ $# -gt 0 ]; do
    case "$1" in
      -v|--volumes) down+=(-v) ;;
      *) echo "Unknown --stop option '$1'" >&2; exit 1 ;;
    esac
    shift
  done
  compose "${down[@]}"
}

do_logs() {
  case "${1:-}" in
    "")           compose logs -f --tail=200 ;;
    -e|--errors)  compose logs -f --tail=200 | grep -Eai '(error|exception|fatal)' ;;
    *) echo "Unknown --logs option '$1'" >&2; exit 1 ;;
  esac
}

mode="${1:-}"
case "$mode" in
  -h|--help) print_help; exit 0 ;;
  "")        print_help; exit 1 ;;
esac
shift

require_env
require_docker
case "$mode" in
  --stop) do_stop "$@" ;;
  --logs) do_logs "$@" ;;
  --ps)   compose ps "$@" ;;
  *) echo "Unknown command: $mode (expected --stop | --logs | --ps; see -h)" >&2; exit 1 ;;
esac
