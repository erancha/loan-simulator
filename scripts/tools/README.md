# Tools

Hands-on tools, run from any directory against the Compose stack; `--ec2` as the first argument
acts on the stack's EC2 instance. Each prints its full usage with `--help`.

- `sql-helper.sh [--ec2]` — psql on the stack's database: a shell, `-c`, a SQL file, row counts
  and rows of every table, `--backup <file>` / `--restore <file>` of the whole database,
  `--people` with `--reset <account-id>` / `--reset-all`, which delete a person's records so
  their next sign-in is a first visit, `--clone <from> <to>`, which copies one account's checks
  to another that has no records, `--ec2 --preview --copy-live`, which replaces the preview's
  database with production's and migrates it (`--copy-live` alone does it for this machine's
  database), and `--demo-check <check-id>`, which writes a check's
  stored events to the recording `demo.html` replays.
- `turn-timing.sh [--scenario S] [--runs N] [--pause S]` — runs one fixed scenario N times
  against the local stack with the real model and prints each turn's time, each model call's
  seconds and reasoning tokens, and whether each recommendation is the cheapest option that fits
  the ceiling; local only, since it starts an agent of its own that signs in with a test key.
- `lock.sh` — recompiles `mcp-server/requirements.txt` and `backend/requirements.txt` inside each
  Dockerfile's Python image; run it after editing a dependency list.

Back to the [README](../../README.md).
