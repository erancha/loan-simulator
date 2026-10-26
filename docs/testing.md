# Testing

What each layer of tests proves, and how to run it.

```bash
./scripts/test.sh            # every target (today: engine)
./scripts/test.sh engine     # script syntax, ruff lint and format, mypy, import-linter, pytest
```

No test reaches the Bank of Israel or the Central Bureau of Statistics: fetchers run against
recorded responses, and the server against stored histories built in the tests.

## Engine

**Static gates** fail the run before any test: `bash -n` on every script, ruff lint, ruff format
in check mode, mypy, and the import-linter contracts that keep `service → market → domain`
pointing inwards.

**Domain** tests run on plain values: schedules for each repayment method with changing rates and
CPI, the historical replay and its worst window, and the policy bounds, each against hand-computed
figures from [calculations.md](calculations.md).

**Market** tests drive the parsers with recorded Bank of Israel and CBS responses, the monthly
alignment, the stored-series fallback when a source fails, and the failure when nothing is stored
([market-data.md](market-data.md)).

**Service** tests call the tools and resources through an MCP client against the real HTTP app:
the bearer token is required, the host allow-list holds, results are rounded to agorot, and
startup and the daily refresh fail loudly.

**Deployment files** are checked without Docker: `test_env_example.py` requires `.env.example` to
document every setting and nothing else, and `init-env.sh` to write settings the engine accepts and
to leave no `.env` when a written value fails its check; `test_compose.py` requires that the
engine's only published port binds to `127.0.0.1` through the `ENGINE_HOST_PORT` and `ENGINE_PORT`
variables and that the market data volume is mounted; and `test_requirements_lock.py` requires the
lock to match `pyproject.toml` and the image.
