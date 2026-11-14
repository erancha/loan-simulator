#!/usr/bin/env bash
#
# Run psql against the stack's Postgres: the POSTGRES_DB database of the db service in the Compose
# stack. With --ec2 as the first argument it acts on the stack's EC2 instance instead of this
# machine.
#
#   ./scripts/tools/sql-helper.sh                    open an interactive psql shell
#   ./scripts/tools/sql-helper.sh --counts           row count of every table, largest first
#   ./scripts/tools/sql-helper.sh --rows [--limit N] the first 20 rows of every table (or N),
#                                                    values cut to 80 characters
#   ./scripts/tools/sql-helper.sh -f <file> [args]   run a host SQL file (streamed in via stdin)
#   ./scripts/tools/sql-helper.sh [psql-args...]     forward args to psql, e.g. -c "SELECT 1"
#   ./scripts/tools/sql-helper.sh --backup <file>    write the whole database to a file on this
#                                                    machine (pg_dump custom format); refuses to
#                                                    overwrite a file
#   ./scripts/tools/sql-helper.sh --restore <file>   replace the database's tables with a backup's,
#                                                    after asking to type the database's name
#   ./scripts/tools/sql-helper.sh --people           every person with records: Google account ID,
#                                                    profile, checks, last activity (newest first)
#   ./scripts/tools/sql-helper.sh --reset <id>       delete every record of the person with that
#                                                    account ID, so their next sign-in is a first
#                                                    visit; asks to type the database's name
#   ./scripts/tools/sql-helper.sh --reset-all        the same for everyone
#   -h, --help                                       show this help
#
# Examples:
#   ./scripts/tools/sql-helper.sh -c "SELECT id, created_at FROM checks ORDER BY created_at;"
#   # what --rows runs:
#   ./scripts/tools/sql-helper.sh -f scripts/tools/sql/all-tables.sql -v rows=1 -v limit=20
#   # start over as a first visit on the instance (the agent stores no email address, so find
#   # yourself by your latest activity):
#   ./scripts/tools/sql-helper.sh --ec2 --people
#   ./scripts/tools/sql-helper.sh --ec2 --reset <account-id>
#   # move the data to a replaced instance:
#   ./scripts/tools/sql-helper.sh --ec2 --backup backup/loan.dump
#   ./scripts/tools/sql-helper.sh --ec2 --restore backup/loan.dump
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=../common.sh
source "$SCRIPT_DIR/common.sh"

ALL_TABLES_SQL="$SCRIPT_DIR/tools/sql/all-tables.sql"
PEOPLE_SQL="$SCRIPT_DIR/tools/sql/people.sql"
RESET_SQL="$SCRIPT_DIR/tools/sql/reset-people.sql"
ROWS_LIMIT=20

TARGET=local
if [[ "${1:-}" == --ec2 ]]; then TARGET=ec2; shift; fi

# --backup and --restore take a file on this machine and nothing else.
DUMP_MODE=""
DUMP_FILE=""
case "${1:-}" in
  --backup|--restore)
    DUMP_MODE="${1#--}"
    DUMP_FILE="${2:-}"
    [[ -n "$DUMP_FILE" && $# -eq 2 ]] || { print_help >&2; exit 2; }
    if [[ "$DUMP_MODE" == backup ]]; then
      [[ ! -e "$DUMP_FILE" ]] || { echo "$DUMP_FILE exists; name a new file" >&2; exit 1; }
    else
      [[ -f "$DUMP_FILE" ]] || { echo "Backup file not found: $DUMP_FILE" >&2; exit 1; }
    fi
    set -- ;;
esac

# --reset and --reset-all delete records after the same typed confirmation as --restore.
RESET_PERSON=""
case "${1:-}" in
  --reset)
    [[ -n "${2:-}" && $# -eq 2 ]] || { print_help >&2; exit 2; }
    RESET_PERSON="$2"
    set -- ;;
  --reset-all)
    [[ $# -eq 1 ]] || { print_help >&2; exit 2; }
    RESET_PERSON='*'
    set -- ;;
esac

case "${1:-}" in
  -h|--help) print_help; exit 0 ;;
  --counts)  shift; set -- -f "$ALL_TABLES_SQL" "$@" ;;
  --people)  shift; set -- -f "$PEOPLE_SQL" "$@" ;;
  --rows)
    shift
    if [[ "${1:-}" == "--limit" ]]; then
      [[ "${2:-}" =~ ^[0-9]+$ ]] \
        || { echo "--limit needs a row count, got: ${2:-<none>}" >&2; exit 2; }
      ROWS_LIMIT="$2"
      shift 2
    fi
    set -- -f "$ALL_TABLES_SQL" -v rows=1 -v "limit=$ROWS_LIMIT" "$@" ;;
esac

# -f names a path on the host, not inside the container, so the file is streamed in via stdin
# rather than psql's own -f (which would resolve the path container-side).
SQL_FILE=""
if [[ "${1:-}" == "-f" || "${1:-}" == "--file" ]]; then
  SQL_FILE="${2:-}"
  if [[ -z "$SQL_FILE" || ! -f "$SQL_FILE" ]]; then
    echo "SQL file not found: ${SQL_FILE:-<none given>}" >&2
    exit 1
  fi
  shift 2
fi

load_settings
if [[ "$TARGET" == ec2 ]]; then use_ec2; fi
require_docker

PSQL=(psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1)
if [[ "$DUMP_MODE" == backup ]]; then
  # Written beside the target and renamed when complete, so a failed dump leaves no file that
  # looks like a backup. The dump holds every person's data, so only its owner may read it.
  draft="$(mktemp "$DUMP_FILE.XXXXXX")"
  trap 'rm -f "$draft"' ERR
  compose exec -T db pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom > "$draft"
  mv "$draft" "$DUMP_FILE"
  echo "Wrote $DUMP_FILE ($(du -h "$DUMP_FILE" | cut -f1))."
elif [[ "$DUMP_MODE" == restore ]]; then
  echo "This replaces every table of database '$POSTGRES_DB' ($TARGET) with the backup's."
  read -r -p "Type the database's name to continue: " answer
  [[ "$answer" == "$POSTGRES_DB" ]] || { echo "Not restored." >&2; exit 1; }
  compose exec -T db pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    --clean --if-exists --no-owner --single-transaction < "$DUMP_FILE"
  echo "Restored $DUMP_FILE; restart the agent: ./scripts/deploy.sh"
elif [[ -n "$RESET_PERSON" ]]; then
  if [[ "$RESET_PERSON" == '*' ]]; then whom="everyone"; else whom="account $RESET_PERSON"; fi
  # A mistyped account ID would otherwise report a reset that deleted nothing.
  held="$(compose exec -T db "${PSQL[@]}" -At -v "person=$RESET_PERSON" < "$PEOPLE_SQL" |
    awk -F'|' -v person="$RESET_PERSON" 'person == "*" || $1 == person' | wc -l)"
  [[ "$held" -gt 0 ]] ||
    { echo "No records of $whom; list the account IDs with --people" >&2; exit 1; }
  echo "This deletes every record of $whom in database '$POSTGRES_DB' ($TARGET)."
  read -r -p "Type the database's name to continue: " answer
  [[ "$answer" == "$POSTGRES_DB" ]] || { echo "Nothing deleted." >&2; exit 1; }
  compose exec -T db "${PSQL[@]}" -q -v "person=$RESET_PERSON" < "$RESET_SQL"
  echo "Deleted; the next sign-in of $whom starts as a first visit."
elif [[ -n "$SQL_FILE" ]]; then
  compose exec -T db "${PSQL[@]}" "$@" < "$SQL_FILE"
elif [[ $# -eq 0 ]]; then
  # An interactive shell needs a TTY, so -T is left off.
  compose exec db "${PSQL[@]}"
else
  compose exec -T db "${PSQL[@]}" "$@"
fi
