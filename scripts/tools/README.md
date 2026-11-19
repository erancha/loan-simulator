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
- `lock.sh` — recompiles `mcp-server/requirements.txt` and `backend/requirements.txt` inside each
  Dockerfile's Python image; run it after editing a dependency list.

Back to the [README](../../README.md).
