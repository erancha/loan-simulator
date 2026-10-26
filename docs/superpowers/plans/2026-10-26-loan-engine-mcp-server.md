# Loan-engine MCP server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the loan-engine MCP server: loan schedules, the historical replay, affordability
bounds and track suggestions over live Bank of Israel and CBS data, served as MCP tools and
resources over Streamable HTTP behind a bearer token, runnable alone and against MCP Inspector.

**Architecture:** A standalone Python project in `mcp-server/` (package `loan_engine`) with three
layers: `domain` (pure calculations, no I/O, no framework), `market` (fetching and storing the
three data series), and `service` (the MCP server, configuration, auth and startup). The server
knows nothing about people; it takes a profile and loans and returns results. This is plan 1 of 4;
the agent backend, the page and the evals will follow in their own plans and consume this server's
tools.

**Tech Stack:** Python 3.14 image (`requires-python >=3.12`), `mcp==2.3.*` (`MCPServer`, `Client`),
pydantic 2, `httpx2` (already the MCP SDK's HTTP client), uvicorn, pytest, ruff, mypy,
import-linter, pip-tools, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-10-26-loan-simulator-design.md` (sections 4, 5, 7, 10).

## Global Constraints

- Every number is computed in code; money is `decimal.Decimal`, never `float`. Values leave the
  server rounded to agorot (`0.01`, `ROUND_HALF_UP`); internal calculations do not round.
- Monthly rate = annual nominal percent / 1200. Prime = Bank of Israel rate + 1.5.
- Rate kinds in phase 1: `fixed`, `prime` (prime + spread); each `cpi_linked` true or false.
  Repayment methods: `spitzer` (equal payments), `equal_principal`, `balloon`.
- The server stores nothing personal and never sees the person's Google token.
- Transport: Streamable HTTP at `/mcp`, `stateless_http=True`, `json_response=True`; reachable only
  inside the Compose network; static bearer token from configuration; host-header allow-list from
  configuration.
- Market data: Bank of Israel rate `MNT_RIB_BOI_D`, CBS CPI code `120010` (URLs as in spec
  section 4), and the Bank of Israel's average rate on new unindexed household consumer loans,
  series `BNK_99010_LR_BIR_1893` in dataflow `BIR` (monthly, excludes overdrafts and
  housing-secured credit; 7.9% for 2026-08), at
  `https://edge.boi.gov.il/FusionEdgeServer/sdmx/v2/data/dataflow/BOI.STATISTICS/BIR/1.0/BNK_99010_LR_BIR_1893?startperiod=YYYY-MM-DD&format=csv`;
  send a browser-like `User-Agent` to the Bank of Israel; request CBS with `PageSize=1000` (the
  default page is 10 rows).
- If a source is unreachable the last stored series is used and every result carries its data
  date; with no stored series at all, startup fails with an error naming the missing series.
- Docs in English, present tense, no history narration (user's documentation rules); comments
  only where the code cannot say it.
- Mirror home-finance-agent conventions (`~/projects/python/home-finance-agent`): script header
  comments as `--help`, `scripts/common.sh`, lock compiled inside the Dockerfile's Python image,
  `test_requirements_lock.py`, ruff line length 100, import-linter layer contracts.

**Decisions this plan takes that the user should approve while reviewing** (spec section 11 leaves
them to the builder; each lives in one constants module so changing it is a one-line edit):
- History windows start within the last ten years of the series (a rolling 120 months). A worst
  case named after a period the person lived through is believed, and the 1990s, when inflation
  ran near 10% a year under a different monetary regime, stay out.
- Base path for "today's payment" and total cost: current rate held flat; inflation 2% a year
  (the middle of the Bank of Israel's 1-3% target) for CPI-linked tracks.
- The Bank of Israel rate is floored at 0 when a historical decrease is applied to today's rate.
- Affordability: counted income = net fixed income + 50% of variable income when the person calls
  it stable, 0% when not; ceiling = min(30% of counted income, 50% of counted income minus fixed
  expenses) minus existing loan payments, floored at 0; minimum cushion = 2 months of fixed
  expenses.
- Typical tracks come from the published Bank of Israel average, not from estimates: fixed
  unlinked at the latest monthly average rate on new household consumer loans; prime at a spread
  equal to that average minus the prime in effect in the same month (2026-08: 7.9% − 5.0% = 2.9).
  The series mixes fixed and variable rates and has no split, and no published series covers
  CPI-linked consumer loans, so the typical suggestions are unlinked only; a linked track enters
  only as a real offer. The screen labels both as "the average bank rate for household loans in
  <month>". The credit card companies' series (dataflow `CCIR`) stops at 2025-06 and is not used.
- Loan limits: principal 10,000-100,000 ₪ (set by the user), term 6-96 months.

## Review Focus

1. A term longer than the available history (e.g. 96 months against a short series) yields fewer
   or no windows; with none, `simulate_loan` returns an error saying no window is long enough, not
   an empty worst case. Test in Task 4.
2. Trade-in plus spare savings cover the goal price: `size_loan` returns a loan amount of 0 and
   the spare savings, and does not fail. Test in Task 5.
3. A source down at startup with a stored series present: startup succeeds and results carry the
   stored data date; with nothing stored, startup fails naming the series. Test in Task 6.
4. A CPI base change inside the history (the CBS rebases every two years): the inflation series
   chains through the monthly `percent`, never the index level. Test in Task 6.
5. Bad tool arguments from the model (balloon amount at or above principal, negative fee, term
   out of range, balloon with equal principal): the tool returns `is_error` with a message naming
   the field, so the model can correct itself. Test in Task 7.

---

### Task 1: Repo skeleton and the `mcp-server` project

**Files:**
- Create: `.gitignore`, `CLAUDE.md`, `LICENSE` (MIT, as home-finance-agent)
- Create: `scripts/common.sh`, `scripts/test.sh`, `scripts/lock.sh`
- Create: `mcp-server/pyproject.toml`, `mcp-server/Dockerfile`, `mcp-server/requirements.txt`
- Create: `mcp-server/src/loan_engine/__init__.py` and empty `domain/`, `market/`, `service/`
  packages
- Test: `mcp-server/tests/test_requirements_lock.py`, `mcp-server/tests/test_architecture.py`

**Interfaces:**
- Produces: `./scripts/test.sh engine` (alias `en`) runs shell checks, ruff, mypy, lint-imports
  and pytest for `mcp-server/`; later plans add `backend`, `frontend`, `evals` targets to the same
  script. `scripts/common.sh` exports `ROOT`, `ENGINE=$ROOT/mcp-server`, `ENGINE_VENV`, and
  `ensure_engine_venv` (creates the venv and installs `-e .[dev]` constrained by
  `requirements.txt`).

- [ ] **Step 1: Write `mcp-server/pyproject.toml`** modelled on home-finance-agent's
  `backend/pyproject.toml`: name `loan-engine`, dependencies `mcp>=2.3,<3`, `pydantic>=2.11`,
  `pydantic-settings>=2.15`, `httpx2>=2.16`, `uvicorn[standard]>=0.54`, `structlog>=26`; dev extras
  `pytest`, `pytest-asyncio`, `import-linter`, `ruff>=0.17,<0.18`, `mypy`, `pip-tools`, `packaging`.
  Import-linter contracts:
  - layers `loan_engine.service` over `loan_engine.market` over `loan_engine.domain`;
  - `loan_engine.domain` forbidden from `mcp`, `httpx2`, `pydantic_settings`, `starlette`,
    `uvicorn`, `structlog` (pydantic is allowed in the domain: its models are the tool schemas).
- [ ] **Step 2: Copy and adapt `scripts/common.sh`, `scripts/lock.sh` and `scripts/test.sh`** from
  home-finance-agent, keeping their header-as-help style; `lock.sh` compiles
  `mcp-server/requirements.txt` inside the `python:` image named in `mcp-server/Dockerfile`.
- [ ] **Step 3: Write `mcp-server/Dockerfile`** as home-finance-agent's backend stage (lock
  mounted, non-root user `engine`, `EXPOSE 8020`, `CMD ["python", "-m", "loan_engine"]`).
- [ ] **Step 4: Write the tests:** `test_requirements_lock.py` adapted from home-finance-agent
  (direct deps pinned, compiled on the Dockerfile's Python, Dockerfile and venv install from the
  lock); `test_architecture.py::test_layer_contracts_hold` runs `lint-imports` and asserts exit 0.
- [ ] **Step 5: Run `./scripts/lock.sh`, then `./scripts/test.sh engine`.** Expected: all checks
  pass.
- [ ] **Step 6: Write `CLAUDE.md`** (layout and layer rule, scripts, a "Facts that bite" list
  starting with: money is Decimal; MCP SDK is 2.x while `langchain-mcp-adapters` requires `mcp<2`,
  so the server and the agent never share a venv). Commit.

```bash
git add .gitignore CLAUDE.md LICENSE scripts mcp-server
git commit -m "Scaffold the loan-engine MCP server project with lock, lint and layer checks"
```

### Task 2: Domain model

**Files:**
- Create: `mcp-server/src/loan_engine/domain/models.py`, `domain/limits.py`
- Test: `mcp-server/tests/domain/test_models.py`

**Interfaces:**
- Produces (all pydantic `BaseModel`, `frozen=True`, `extra="forbid"`):
  - `RateKind = Literal["fixed", "prime"]`, `Method = Literal["spitzer", "equal_principal",
    "balloon"]`
  - `Track(principal: Decimal, term_months: int, rate_kind: RateKind, annual_rate: Decimal | None,
    prime_spread: Decimal | None, cpi_linked: bool, method: Method, balloon_amount: Decimal = 0,
    one_time_fee: Decimal = 0, monthly_fee: Decimal = 0)`; `annual_rate` required and only for
    `fixed`, `prime_spread` required and only for `prime`.
  - `Loan(tracks: list[Track])`, at least one track; `Loan.principal` property = sum.
  - `Profile(net_fixed_income: Decimal, variable_income: Decimal, variable_income_stable: bool,
    fixed_expenses: Decimal, existing_loan_payments: Decimal)`, all `>= 0`.
  - `limits.py`: `MIN_PRINCIPAL = 10000`, `MAX_PRINCIPAL = 100000`, `MIN_TERM = 6`,
    `MAX_TERM = 96`.

- [ ] **Step 1: Write failing tests** in `test_models.py`:
  - `test_fixed_track_requires_annual_rate_and_rejects_spread`
  - `test_prime_track_requires_spread_and_rejects_annual_rate`
  - `test_balloon_amount_must_be_below_principal` (`balloon_amount=25000, principal=25000` raises)
  - `test_balloon_amount_only_with_balloon_method`
  - `test_term_and_principal_limits` (5 and 97 months raise; 9,999 and 100,001 ₪ raise)
  - `test_fees_and_profile_amounts_are_non_negative`
  - `test_loan_principal_sums_tracks`
  Each validation error message names the offending field.
- [ ] **Step 2: Run** `cd mcp-server && .venv/bin/pytest tests/domain/test_models.py`. Expected:
  FAIL (import error).
- [ ] **Step 3: Implement the models** with field constraints and `model_validator(mode="after")`
  for the cross-field rules.
- [ ] **Step 4: Run the tests.** Expected: PASS.
- [ ] **Step 5: Commit** ("Define the loan, track and profile model with phase-1 limits").

### Task 3: Schedule engine

**Files:**
- Create: `mcp-server/src/loan_engine/domain/schedule.py`
- Create: `docs/calculations.md` (schedule section)
- Test: `mcp-server/tests/domain/test_schedule.py`

**Interfaces:**
- Consumes: `Track` (Task 2).
- Produces:
  - `MonthRow(month: int, annual_rate: Decimal, payment: Decimal, interest: Decimal,
    principal: Decimal, balance: Decimal)`
  - `Schedule(rows: tuple[MonthRow, ...])` with properties `first_payment`, `max_payment`,
    `total_paid` (sum of payments plus the track's `one_time_fee`).
  - `schedule(track: Track, annual_rates: Sequence[Decimal], monthly_inflation:
    Sequence[Decimal]) -> Schedule` — one rate and one inflation fraction per month (`len ==
    term_months`); inflation is ignored for unlinked tracks.

Algorithm (month k = 1..n, m = months remaining including k, r = annual_rates[k-1] / 1200):

```
if linked: balance *= 1 + inflation[k-1]; balloon_k = balloon * Π(1 + inflation[..k-1])
spitzer / balloon:  pmt = (balance - balloon_k / (1+r)^m) * r / (1 - (1+r)^-m)   # r == 0: (balance - balloon_k) / m
equal_principal:     pmt = balance / m + balance * r
interest = balance * r; principal = pmt - interest; balance -= principal
last month: payment also clears what remains (the balloon, rounding residue); balance ends at 0
payment shown = pmt + monthly_fee
```

- [ ] **Step 1: Write failing tests** (values computed independently; compare after rounding to
  0.01):
  - `test_spitzer_flat_rate`: 25,000 ₪, fixed 7.75%, 48 months, unlinked → every payment
    `607.39`, `total_paid == 29154.89`, final balance 0.
  - `test_equal_principal_first_payment`: same loan, `equal_principal` → first payment `682.29`,
    payments strictly decreasing.
  - `test_balloon`: same loan, balloon 10,000 → monthly `429.02`, last payment = `429.02` +
    10,000 (to the agora).
  - `test_zero_rate`: 12,000 ₪ at 0%, 24 months → `500.00` each.
  - `test_rate_change_recomputes_payment`: prime path 6.25% for 12 months then 9.25% → payment
    rises in month 13 and stays constant after; balance ends at 0.
  - `test_cpi_linked_balance_indexed`: fixed 4.5% linked, inflation 0.5% every month → payments
    rise every month; with zero inflation the schedule equals the unlinked one.
  - `test_fees`: `monthly_fee=10` adds 10 to every payment; `one_time_fee=300` adds 300 to
    `total_paid` only.
  - `test_rates_length_must_match_term` raises `ValueError`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement `schedule`.**
- [ ] **Step 4: Run them.** Expected: PASS.
- [ ] **Step 5: Write the schedule section of `docs/calculations.md`**: the three methods with
  their formulas, how CPI linkage indexes the balance and the balloon, fees, rounding.
- [ ] **Step 6: Commit** ("Compute monthly schedules for equal-payment, equal-principal and
  balloon tracks under changing rates and CPI").

### Task 4: Historical replay

**Files:**
- Create: `mcp-server/src/loan_engine/domain/history.py`, `domain/assumptions.py`
- Modify: `docs/calculations.md` (replay section)
- Test: `mcp-server/tests/domain/test_history.py`

**Interfaces:**
- Consumes: `schedule`, `Schedule`, `Track`, `Loan`.
- Produces:
  - `assumptions.py`: `HISTORY_MONTHS = 120`, `BASE_ANNUAL_INFLATION =
    Decimal("2.0")`, `PRIME_MARGIN = Decimal("1.5")`, `BOI_RATE_FLOOR = Decimal("0")`.
  - `MarketHistory(months: tuple[date, ...], boi_rate: tuple[Decimal, ...], monthly_inflation:
    tuple[Decimal, ...], current_boi_rate: Decimal, rate_as_of: date, cpi_as_of: date,
    consumer_rate: Decimal, consumer_rate_month: date, consumer_month_prime: Decimal)` —
    monthly, aligned, first-of-month dates; `boi_rate` is the rate in effect on that day,
    `monthly_inflation` the CPI change of that month as a fraction; `current_boi_rate` is the
    latest daily value, dated `rate_as_of`; `consumer_rate` is the latest published average on
    new household consumer loans, for `consumer_rate_month`, and `consumer_month_prime` the prime
    in effect on the first of that month.
  - `Window(start: date, end: date, max_payment: Decimal, total_paid: Decimal)`
  - `TrackOutcome(base: Schedule, worst: Window | None, max_payment_range: tuple[Decimal,
    Decimal] | None, total_paid_range: tuple[Decimal, Decimal] | None, windows: int)` —
    `worst` and the ranges are `None` for a fixed unlinked track (its payment cannot change).
  - `simulate(track: Track, history: MarketHistory) -> TrackOutcome`
  - `NoHistoryWindowError(ValueError)` raised when the term exceeds every window.

Rules (spec section 5): base path = today's rate flat, inflation `BASE_ANNUAL_INFLATION` as
`(1.02)^(1/12) - 1` per month. Windows start at every month s in the last `HISTORY_MONTHS` months with s +
term inside the series; month k of window s uses rate `max(current + (boi[s+k] - boi[s]),
BOI_RATE_FLOOR) + PRIME_MARGIN + spread` for prime tracks (fixed tracks keep their rate) and
inflation `monthly_inflation[s+k]` for linked tracks. Worst = highest `max_payment`, earliest on a
tie.

- [ ] **Step 1: Write failing tests** with a hand-built `MarketHistory`:
  - `test_fixed_unlinked_has_no_risk`: `worst is None`, `windows == 0`.
  - `test_prime_replays_changes_not_levels`: series where the rate goes 0.1 → 4.75 over 15
    months; with current 3.25 the worst window's peak rate is 3.25 + 4.65 + 1.5 + spread, not
    4.75-based.
  - `test_rate_floor`: a historical drop larger than today's rate floors the BoI rate at 0.
  - `test_worst_is_highest_peak_payment_and_earliest_on_tie`.
  - `test_linked_uses_window_inflation` and `test_prime_and_linked_move_together`.
  - `test_ranges_span_all_windows`.
  - `test_term_longer_than_history_raises` (`NoHistoryWindowError`, message names the term and
    the number of months available).
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement `simulate`** and the window enumeration.
- [ ] **Step 4: Run them.** Expected: PASS.
- [ ] **Step 5: Write the replay section of `docs/calculations.md`**: changes not levels and why,
  the floor, worst by peak payment, the rolling ten years and the 2% base inflation with their
  reasons.
- [ ] **Step 6: Commit** ("Measure each variable track against every historical window of its
  term").

### Task 5: Affordability, loan sizing and typical tracks

**Files:**
- Create: `mcp-server/src/loan_engine/domain/policy.py`
- Modify: `domain/assumptions.py` (policy constants), `docs/calculations.md` (policy section)
- Test: `mcp-server/tests/domain/test_policy.py`

**Interfaces:**
- Consumes: `Profile`, `Track`, limits.
- Produces:
  - Constants: `STABLE_VARIABLE_SHARE = Decimal("0.5")`, `INCOME_SHARE_CAP = Decimal("0.30")`,
    `DISPOSABLE_SHARE_CAP = Decimal("0.50")`, `CUSHION_MONTHS = 2`.
  - `Reason = Literal["variable_income_excluded", "variable_income_half_counted",
    "ceiling_by_income_share", "ceiling_by_disposable_income", "existing_loans_deducted",
    "no_room_for_payment"]`
  - `Bounds(payment_ceiling: Decimal, min_cushion: Decimal, counted_income: Decimal, reasons:
    list[Reason])`; `assess_affordability(profile: Profile) -> Bounds`
  - `Sizing(loan_amount: Decimal, savings_used: Decimal, cushion_kept: Decimal, spare_savings:
    Decimal)`; `size_loan(goal_price: Decimal, trade_in_value: Decimal, savings: Decimal,
    min_cushion: Decimal) -> Sizing`
  - `suggest_tracks(principal: Decimal, term_months: int, history: MarketHistory) ->
    list[Track]` — two unlinked `spitzer` tracks without fees: fixed at `consumer_rate`, and prime
    with spread `consumer_rate - consumer_month_prime`.

- [ ] **Step 1: Write failing tests:**
  - `test_reference_user`: net fixed 8,600, variable 5,000 unstable, fixed expenses 5,500, no
    loans → ceiling `1550.00`, cushion `11000.00`, reasons `["variable_income_excluded",
    "ceiling_by_disposable_income"]`.
  - `test_stable_variable_half_counted` and `test_ceiling_by_income_share`.
  - `test_existing_loans_deducted_and_floor_at_zero` (`no_room_for_payment` when ≤ 0).
  - `test_size_loan_reference_user`: price 55,000, trade-in 20,000, savings 15,000, cushion
    11,000 → loan `31000`, savings used `4000`, cushion kept `11000`, spare `0`.
  - `test_size_loan_savings_below_cushion_uses_none`.
  - `test_size_loan_covered_returns_zero_and_spare`: price 30,000, trade-in 20,000, savings
    15,000, cushion 2,000 → loan `0`, savings used `10000`, spare `3000`.
  - `test_suggest_tracks_from_published_average`: consumer rate 7.9 for 2026-08 with prime 5.0
    that month → fixed 7.9 unlinked and prime + 2.9 unlinked; no linked track.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them.** Expected: PASS.
- [ ] **Step 5: Write the policy section of `docs/calculations.md`**: each number with its reason;
  how the typical tracks derive from the published average and why there is no linked one.
- [ ] **Step 6: Commit** ("Bound the monthly payment and savings cushion, size the loan and offer
  typical tracks").

### Task 6: Market data

**Files:**
- Create: `mcp-server/src/loan_engine/market/boi.py`, `market/cbs.py`, `market/store.py`,
  `market/refresh.py`
- Create: `mcp-server/tests/market/fixtures/` (real responses, trimmed)
- Create: `docs/market-data.md`
- Test: `mcp-server/tests/market/test_boi.py`, `test_cbs.py`, `test_store.py`, `test_refresh.py`

**Interfaces:**
- Consumes: `MarketHistory` (Task 4).
- Produces:
  - `async fetch_boi(client: httpx2.AsyncClient, start: date) -> list[tuple[date, Decimal]]`
    (daily) and `boi_monthly(daily) -> list[tuple[date, Decimal]]` (value in effect on each
    first of month: the latest daily value on or before it).
  - `async fetch_cpi(client: httpx2.AsyncClient, start: date) -> list[tuple[date, Decimal]]`
    (month, change as a fraction, from `percent`).
  - `async fetch_consumer_rate(client: httpx2.AsyncClient, start: date) -> list[tuple[date,
    Decimal]]` (monthly average rate on new household consumer loans, series
    `BNK_99010_LR_BIR_1893`).
  - `SeriesStore(path: Path)` with `save(history: MarketHistory, fetched_at: datetime)` and
    `load() -> MarketHistory | None` (one JSON file, written atomically).
  - `async refresh(store: SeriesStore, client: httpx2.AsyncClient) -> MarketHistory` — fetch
    all three, build and save; on any fetch error return the stored history and log a warning; with
    nothing stored, raise `MarketDataUnavailableError` naming the series that failed.

- [ ] **Step 1: Capture fixtures** from the live APIs (the URLs in the spec and Global
  Constraints), trimmed to 2021-12 through 2023-06 for the Bank of Israel rate, the last 12 months
  of the consumer-rate series, and a span crossing a CBS base change for the CPI.
  Note the request and capture date in a fixtures README.
- [ ] **Step 2: Write failing tests** using `httpx2.MockTransport` over the fixtures:
  - `test_boi_parses_csv_and_sends_browser_user_agent`
  - `test_boi_monthly_uses_last_value_on_or_before_first_of_month` (weekends and holidays have no
    row)
  - `test_cpi_requests_page_size_1000_and_parses_percent`
  - `test_consumer_rate_parses_latest_month`
  - `test_cpi_chains_across_base_change` (Review Focus 4: inflation comes from `percent`; the
    index level jump at the base change does not appear)
  - `test_store_round_trip` and `test_store_write_is_atomic`
  - `test_refresh_falls_back_to_stored_history` and
    `test_refresh_without_store_raises_naming_series` (Review Focus 3)
- [ ] **Step 3: Run them.** Expected: FAIL.
- [ ] **Step 4: Implement.**
- [ ] **Step 5: Run them.** Expected: PASS.
- [ ] **Step 6: Write `docs/market-data.md`**: the three series, URLs, User-Agent and paging quirks,
  monthly alignment, refresh on start and daily, fallback, the data dates on every result.
- [ ] **Step 7: Commit** ("Fetch and keep the Bank of Israel rate and CPI series with a stored
  fallback").

### Task 7: The MCP server

**Files:**
- Create: `mcp-server/src/loan_engine/service/config.py`, `service/auth.py`, `service/tools.py`,
  `service/server.py`, `src/loan_engine/__main__.py`
- Test: `mcp-server/tests/service/test_tools.py`, `test_auth.py`, `test_config.py`

**Interfaces:**
- Consumes: Tasks 2-6.
- Produces (the contract plan 2's agent depends on):
  - `Settings` (pydantic-settings, prefix `ENGINE_`): `BEARER_TOKEN` (required, min 32 chars),
    `ALLOWED_HOSTS` (comma list, required), `PUBLIC_URL` (required, used for `AuthSettings`),
    `DATA_DIR` (default `/data`), `PORT` (default 8020). No default for anything required.
  - `build_server(settings: Settings, history_provider: Callable[[], MarketHistory]) ->
    MCPServer`, named `loan-engine`, with tools:
    - `assess_affordability(profile: Profile) -> Bounds`
    - `size_loan(goal_price, trade_in_value, savings, min_cushion) -> Sizing`
    - `simulate_loan(loan: Loan) -> LoanSimulation` where `LoanSimulation(tracks:
      list[TrackSimulation], first_payment, max_base_payment, total_paid, rate_as_of, cpi_as_of)`
      and `TrackSimulation` carries the `TrackOutcome` summary plus `schedule: list[MonthRow]`
      (base path). The agent will pass `schedule` to the page and strip it before the model sees
      the result.
    - `suggest_tracks(principal, term_months) -> TrackSuggestions` where
      `TrackSuggestions(tracks: list[Track], as_of: date, source: str)`; `as_of` is
      `consumer_rate_month`, `source` names the Bank of Israel series.
    And resources `rates://boi/history`, `rates://cpi/history`, `rates://current` (JSON).
    Tool descriptions are written for a model: one sentence on when to call it, one on what comes
    back.
  - `build_app(server: MCPServer, settings: Settings) -> Starlette`:
    `streamable_http_app(stateless_http=True, json_response=True, transport_security=TransportSecuritySettings(allowed_hosts=...))`, with
    `token_verifier=StaticTokenVerifier(settings.bearer_token)` (constant-time compare) and
    `AuthSettings(issuer_url=PUBLIC_URL, resource_server_url=PUBLIC_URL + "/mcp")`.
  - `python -m loan_engine`: load settings, run `refresh` once (fail on
    `MarketDataUnavailableError`), schedule a daily refresh in the server lifespan, serve with
    uvicorn on `PORT`.

- [ ] **Step 1: Write failing protocol tests** with the in-memory `mcp.Client(build_server(...))`
  and a fixed `MarketHistory`:
  - `test_lists_tools_and_resources` (names and output schemas present)
  - `test_assess_affordability_reference_user` (structured content equals Task 5's values)
  - `test_simulate_loan_returns_summary_schedule_and_data_dates`
  - `test_simulate_loan_without_history_window_is_tool_error` (Review Focus 1)
  - `test_invalid_track_is_tool_error_naming_field` for balloon ≥ principal, negative fee,
    97-month term, balloon with equal principal (Review Focus 5)
  - `test_size_loan_zero_loan` (Review Focus 2, through the protocol)
  - `test_rates_resources_return_json_with_as_of`
- [ ] **Step 2: Write failing HTTP tests** with `httpx2.ASGITransport` over `build_app`:
  - `test_missing_or_wrong_bearer_is_401`, `test_valid_bearer_lists_tools`,
    `test_unlisted_host_is_rejected`.
  - `test_settings_require_token_hosts_and_url`.
- [ ] **Step 3: Run them.** Expected: FAIL.
- [ ] **Step 4: Implement** `config.py`, `auth.py`, `tools.py` (thin: validate via the models,
  call the domain, convert errors to messages), `server.py`, `__main__.py`.
- [ ] **Step 5: Run `./scripts/test.sh engine`.** Expected: PASS.
- [ ] **Step 6: Commit** ("Serve the loan engine as MCP tools and rate resources behind a bearer
  token").

### Task 8: Run it: Compose, scripts, README

**Files:**
- Create: `docker-compose.yml` (service `engine`, volume `engine-data:/data`, no published port
  except `127.0.0.1:${ENGINE_HOST_PORT}` (8100) for MCP Inspector during development)
- Create: `.env.example` (each setting explained once, as in home-finance-agent),
  `scripts/init-env.sh` (creates `.env` with a generated 48-character token), `scripts/start.sh`,
  `scripts/docker-helper.sh`
- Create: `README.md` (leads with the design; the engine section shows how to start it and
  connect MCP Inspector with the token), `docs/architecture.md` (map; the agent and page are marked
  OPEN, not yet implemented), `docs/testing.md`
- Test: `mcp-server/tests/test_env_example.py` (every `Settings` field appears in `.env.example`
  and nothing else), `mcp-server/tests/test_compose.py` (the engine port binds to 127.0.0.1 only)

- [ ] **Step 1: Write the failing tests.**
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Write the Compose file, `.env.example` and scripts.**
- [ ] **Step 4: Run `./scripts/test.sh engine`.** Expected: PASS.
- [ ] **Step 5: Smoke run:** `./scripts/init-env.sh && ./scripts/start.sh`, then
  `npx @modelcontextprotocol/inspector` against `http://127.0.0.1:8100/mcp` with the bearer
  token; call `simulate_loan` for 31,000 ₪, prime + 2.9, 48 months, unlinked. Expected: a worst
  window with its start and end months, and data dates of today and last month.
- [ ] **Step 6: Write README, `docs/architecture.md`, `docs/testing.md`.** Commit ("Run the loan
  engine in Compose and document it").
