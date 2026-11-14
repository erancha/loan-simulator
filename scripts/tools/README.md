# Tools

Hands-on tools, run from any directory against the Compose stack; `--ec2` as the first argument
acts on the stack's EC2 instance. Each prints its full usage with `--help`.

- `sql-helper.sh [--ec2]` — psql on the stack's database: a shell, `-c`, a SQL file, row counts
  and rows of every table, `--backup <file>` / `--restore <file>` of the whole database, and
  `--people` with `--reset <account-id>` / `--reset-all`, which delete a person's records so
  their next sign-in is a first visit.
- `lock.sh` — recompiles `mcp-server/requirements.txt` and `backend/requirements.txt` inside each
  Dockerfile's Python image; run it after editing a dependency list.

Back to the [README](../../README.md).
