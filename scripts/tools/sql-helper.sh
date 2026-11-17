#!/usr/bin/env bash
#
# Run psql against the stack's Postgres: the POSTGRES_DB database of the db service in the Compose
# stack. With --ec2 as the first argument it acts on the stack's EC2 instance instead of this
# machine; --ec2 --preview acts on the preview beside it (deploy.sh --ec2 --preview).
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
#                                                    checks, last activity (newest first)
#   ./scripts/tools/sql-helper.sh --reset <id>       delete every record of the person with that
#                                                    account ID, so their next sign-in is a first
#                                                    visit; asks to type the database's name
#   ./scripts/tools/sql-helper.sh --reset-all        the same for everyone
#   ./scripts/tools/sql-helper.sh --clone <from> <to>
#                                                    copy every check of account <from> to
#                                                    account <to> under new ids; stops when <to>
#                                                    has any record (reset it first);
#                                                    asks to type the database's name
#   ./scripts/tools/sql-helper.sh --ec2 --preview --copy-live
#                                                    replace the preview's database with a copy
#                                                    of production's (read only there), then run
#                                                    the preview's schema migration on it and
#                                                    print the revision before and after: a
#                                                    rehearsal of production's next upgrade;
#                                                    asks to type the database's name
#   ./scripts/tools/sql-helper.sh --demo-check <id>  write the stored events of the check with that
#                                                    id (the #check= part of the page's URL) to
#                                                    frontend/src/demo/recording.json, the
#                                                    recording demo.html replays
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
#   # give a test account another person's checks to replay their session:
#   ./scripts/tools/sql-helper.sh --ec2 --clone <their-account-id> <test-account-id>
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
CLONE_SQL="$SCRIPT_DIR/tools/sql/clone-person.sql"
DEMO_CHECK_SQL="$SCRIPT_DIR/tools/sql/demo-check.sql"
DEMO_RECORDING="$ROOT/frontend/src/demo/recording.json"
ROWS_LIMIT=20

TARGET=local
if [[ "${1:-}" == --ec2 ]]; then TARGET=ec2; shift; fi
# Only --preview selects the preview, never a value left in the calling shell.
unset DEPLOY_PREVIEW
PREVIEW=""
if [[ "${1:-}" == --preview ]]; then
  [[ "$TARGET" == ec2 ]] || { echo "--preview needs --ec2 before it" >&2; exit 2; }
  export DEPLOY_PREVIEW=1
  PREVIEW=1
  shift
fi

COPY_LIVE=""
if [[ "${1:-}" == --copy-live ]]; then
  [[ -n "$PREVIEW" && $# -eq 1 ]] || { print_help >&2; exit 2; }
  COPY_LIVE=1
  set --
fi

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

# --clone writes records after the same typed confirmation.
CLONE_FROM=""
CLONE_TO=""
if [[ "${1:-}" == --clone ]]; then
  [[ -n "${2:-}" && -n "${3:-}" && $# -eq 3 ]] || { print_help >&2; exit 2; }
  CLONE_FROM="$2"
  CLONE_TO="$3"
  [[ "$CLONE_FROM" != "$CLONE_TO" ]] || { echo "--clone needs two different accounts" >&2; exit 2; }
  set --
fi

DEMO_CHECK=""
if [[ "${1:-}" == --demo-check ]]; then
  [[ -n "${2:-}" && $# -eq 2 ]] || { print_help >&2; exit 2; }
  DEMO_CHECK="$2"
  set --
fi

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

# Reads no input, so a confirmation that follows it still reads the answer typed or piped in.
schema_revision() {
  compose exec -T db "${PSQL[@]}" -At -c "SELECT version_num FROM alembic_version" < /dev/null
}

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
elif [[ -n "$COPY_LIVE" ]]; then
  # Production's Postgres runs on the same Docker daemon as the preview's, in production's
  # Compose project (the name of docker-compose.yml), so its dump streams straight into the
  # preview's: no copy lands on a disk.
  live_project="$(awk '/^name:/ {print $2}' "$ROOT/docker-compose.yml")"
  live_db="$(docker ps -q --filter "label=com.docker.compose.project=$live_project" \
    --filter label=com.docker.compose.service=db)"
  [[ -n "$live_db" ]] ||
    { echo "Production's database is not running on the instance; deploy it first:" \
        "./scripts/deploy.sh --ec2" >&2; exit 1; }
  echo "The preview's schema revision: $(schema_revision)"
  echo "This replaces the preview's database '$POSTGRES_DB' with a copy of production's."
  read -r -p "Type the database's name to continue: " answer
  [[ "$answer" == "$POSTGRES_DB" ]] || { echo "Nothing copied." >&2; exit 1; }
  # The preview's own schema goes first: a restore drops only the objects production's dump
  # holds, and a table only the preview's newer migrations made would make the migration fail.
  compose exec -T db "${PSQL[@]}" -q -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
  docker exec "$live_db" pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom |
    compose exec -T db pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner \
      --single-transaction
  live_revision="$(schema_revision)"
  echo "Production's schema revision, now the preview's: $live_revision"
  if ! compose run --rm migrate; then
    echo "The migration failed on the copy of production's data; the preview's database stays" \
      "at revision $live_revision for inspection (sql-helper.sh --ec2 --preview), and the" \
      "preview's agent keeps running on it unrestarted" >&2
    exit 1
  fi
  echo "After the migration: $(schema_revision)"
  compose restart agent
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
elif [[ -n "$CLONE_FROM" ]]; then
  # Checked before the confirmation, so a wrong account ID stops without a prompt; the SQL file
  # checks the same inside its transaction.
  people="$(compose exec -T db "${PSQL[@]}" -At < "$PEOPLE_SQL")"
  awk -F'|' -v person="$CLONE_FROM" '$1 == person && $2 > 0' <<< "$people" | grep -q . ||
    { echo "Account $CLONE_FROM has no checks to copy; list the account IDs with --people" >&2
      exit 1; }
  ! awk -F'|' -v person="$CLONE_TO" '$1 == person' <<< "$people" | grep -q . ||
    { echo "Account $CLONE_TO has records; reset it first: --reset $CLONE_TO" >&2; exit 1; }
  echo "This copies every check of account $CLONE_FROM to account $CLONE_TO in database" \
    "'$POSTGRES_DB' ($TARGET)."
  read -r -p "Type the database's name to continue: " answer
  [[ "$answer" == "$POSTGRES_DB" ]] || { echo "Nothing copied." >&2; exit 1; }
  compose exec -T db "${PSQL[@]}" -q -At -v "from=$CLONE_FROM" -v "to=$CLONE_TO" \
    < "$CLONE_SQL" | tail -n 1 | xargs -I{} echo "Copied {} checks to account $CLONE_TO."
elif [[ -n "$DEMO_CHECK" ]]; then
  recording="$(compose exec -T db "${PSQL[@]}" -At -v "check=$DEMO_CHECK" < "$DEMO_CHECK_SQL")"
  [[ -n "$recording" ]] ||
    { echo "No events of check $DEMO_CHECK ($TARGET); copy its id from #check= in the URL" >&2
      exit 1; }
  python3 -m json.tool --indent 2 --no-ensure-ascii <<< "$recording" > "$DEMO_RECORDING"
  echo "Wrote ${DEMO_RECORDING#"$ROOT"/}; check it holds no real figures before committing."
elif [[ -n "$SQL_FILE" ]]; then
  compose exec -T db "${PSQL[@]}" "$@" < "$SQL_FILE"
elif [[ $# -eq 0 ]]; then
  # An interactive shell needs a TTY, so -T is left off.
  compose exec db "${PSQL[@]}"
else
  compose exec -T db "${PSQL[@]}" "$@"
fi
