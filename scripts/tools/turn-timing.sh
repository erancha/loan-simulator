#!/usr/bin/env bash
#
# Time the agent's turns on one fixed scenario, run several times against the local stack with the
# real model, and check that each run reaches the same recommendations. The logic is in
# turn_timing.py beside this script.
#
#   ./scripts/tools/turn-timing.sh [--scenario one-track|two-tracks] [--runs N] [--pause S]
#
# Options:
#   --scenario S  one-track (default): a 40,000 ₪ car loan over 48 months and an offer from the
#                 offer form with one track, prime + 1.5%, and no ceiling; two-tracks: a 39,000 ₪
#                 car loan over 48 months, an offer with two tracks (prime + 1.4%, and fixed 3.4%
#                 linked to the CPI), then a ceiling of 1,000 ₪, then of 2,000 ₪
#   --runs N      how many times to run the scenario, each on a new check (default 3)
#   --pause S     seconds to wait between runs (default 0), to see whether the pace of requests
#                 slows the provider
#   -h, --help    show this help
#
# Each run prints every turn's time, each model call's seconds and reasoning tokens, and any
# request the provider refused, such as a 429 over a rate limit, which its client retries inside
# the call and the call's seconds include. It also checks the facts: one option is saved per track
# of the offer, the card is made for the check's ceiling, and each recommendation prefers the
# cheapest option in total among those that fit the ceiling. A summary gives each turn's median and
# slowest time across the runs.
#
# The script starts an agent of its own on this machine, at 127.0.0.1:8111, on the Compose stack's
# database and engine, so the stack must be up (./scripts/deploy.sh). That agent verifies sign-ins
# with a key the script makes for the run instead of Google's, and signs in as the account
# turn-timing, whose checks it deletes after each run. It refuses to start while any check has a
# turn running, since a starting agent ends every turn left running in the database.
#
# A run makes real model calls on LLM_API_KEY. With gpt-5-mini, a one-track run is 1 call, under
# a cent; a two-tracks run about 5 calls, about a cent.
#
# Examples:
#   ./scripts/tools/turn-timing.sh
#   ./scripts/tools/turn-timing.sh --scenario two-tracks --runs 5
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=../common.sh
source "$SCRIPT_DIR/common.sh"

RUNS=3
SCENARIO=one-track
PAUSE=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --runs)
      [[ "${2:-}" =~ ^[1-9][0-9]*$ ]] || { print_help >&2; exit 2; }
      RUNS="$2"
      shift 2
      ;;
    --pause)
      [[ "${2:-}" =~ ^[0-9]+$ ]] || { print_help >&2; exit 2; }
      PAUSE="$2"
      shift 2
      ;;
    --scenario)
      [[ "${2:-}" == one-track || "${2:-}" == two-tracks ]] || { print_help >&2; exit 2; }
      SCENARIO="$2"
      shift 2
      ;;
    -h|--help) print_help; exit 0 ;;
    *) print_help >&2; exit 2 ;;
  esac
done

load_settings
RUNNING_TURNS_SQL="SELECT count(*) FROM check_events e
  JOIN (SELECT check_id, max(seq) seq FROM check_events WHERE type = 'turn.status'
        GROUP BY check_id) latest USING (check_id, seq)
  WHERE e.data->>'status' = 'running'"
running="$("$SCRIPT_DIR/tools/sql-helper.sh" -At -c "$RUNNING_TURNS_SQL")" || {
  echo "The local database does not answer; start the stack first: ./scripts/deploy.sh" >&2
  exit 1
}
if [[ "$running" != 0 ]]; then
  echo "$running check(s) have a turn running; wait until they end, then run this again" >&2
  exit 1
fi
ensure_backend_venv
cd "$ROOT"
exec "$BACKEND_VENV/bin/python" -I "$SCRIPT_DIR/tools/turn_timing.py" \
  --scenario "$SCENARIO" --runs "$RUNS" --pause "$PAUSE"
