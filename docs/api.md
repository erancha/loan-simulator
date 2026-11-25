# API endpoints

This document details every route behind the entry points that
[Architecture](architecture.md#the-parts) summarizes: who may call it, what it takes and answers,
and its limits. The page reaches the `agent` service over an HTTP API and an event stream; the
agent reaches the `engine` service over MCP. The turns a route starts run as workers
([Workers' responsibilities and flows](workers.md)).

## Agent HTTP API (`agent` service)

FastAPI in `backend/src/loan_agent/platform/` (`app.py` and the routers under `api/`). Every
route under `/api/checks` needs the session cookie that `POST /api/auth/session` sets, and acts
only on the signed-in person's checks; [Sign-in](sign-in.md#how-it-works) has the cookie's
lifetime and the 401 that ends it. The check routes share their errors: 404 for a check, or an
awaiting offer, the person does not hold; 409 while the check runs a turn, or on an archived
check; 422 naming the figure, or what the engine or a tool refused; 429 over the message cap,
with the time of the next allowed message in the body and in `Retry-After`
([Turns and the turn cap](architecture/agent.md#turns-and-the-turn-cap)).

### Sign-in

- `GET /api/auth/config` — the public Google client id, for the page; no cookie needed.
- `POST /api/auth/session` — takes the Google ID token as `credential`, verifies it and sets
  the session cookie; answers the person as `GET /api/auth/me` does.
- `GET /api/auth/me` — the signed-in person: id, email, name and `messages`, their standing
  against the message cap (`limit`, `left`, and `next_free`, the time the next message frees,
  null while none is used). The page asks again after each send, so the count it shows is the
  one a send is refused on.
- `DELETE /api/auth/session` — signs out by clearing the cookie (204).

### Checks

- `POST /api/checks` — creates an empty check and answers its id (201).
- `GET /api/checks` — the person's checks, newest first, each with its loan, term, latest
  recommendation, awaiting offers and whether it is archived or started.
- `GET /api/checks/{check_id}` — one check with its finances, options and recommendation.
- `POST /api/checks/{check_id}/clone` — copies an idle check, its conversation and all it
  produced into a new check, and answers the copy's id (201).
- `POST /api/checks/{check_id}/archive` — closes an idle check (204).
- `POST /api/checks/{check_id}/restore` — reopens an archived check (204).
- `DELETE /api/checks/{check_id}` — removes an idle check, its conversation and all it produced
  (204); [Turns and the turn cap](architecture/agent.md#turns-and-the-turn-cap) has the order.
- `PUT /api/checks/{check_id}/finances` — replaces the figures the body names (net fixed income,
  fixed expenses) and answers the check, with the ceiling derived once both are known.
- `PUT /api/checks/{check_id}/term` — the term confirmed on the term card, 6 to 84 months, with a
  ceiling typed beside it (204).
- `PUT /api/checks/{check_id}/awaiting-offers/{awaiting_id}` — the reading the person confirms
  on an awaiting offer's card, saved as their offer (204).
- `PUT /api/checks/{check_id}/awaiting-offers/{awaiting_id}/amount` — the lender's answer to an
  offer quoted for less than the check's loan: `covers`, with the chosen `reading` (204).

### Messages and cards

Each of these takes the line the person sends as `text`, stores it and answers 202; the reply
arrives on the event stream. Only a message, and a term confirmation on some checks, reach the
model, and only those count under the cap; [Tools](architecture/agent.md#tools) has what each
does.

- `POST /api/checks/{check_id}/messages` — a message the model answers.
- `POST /api/checks/{check_id}/opening` — the opening card's `purpose` and `amount`, saved as the
  loan before the line is stored.
- `POST /api/checks/{check_id}/term-ceiling` — a `payment_ceiling` typed on the term card.
- `POST /api/checks/{check_id}/term-confirmation` — the line of a term saved through the term
  route above; a check with no option and no awaiting offer gets the offer form, any other a
  model turn.
- `POST /api/checks/{check_id}/offer-sample` — the offer chip, answered with the offer form.
- `POST /api/checks/{check_id}/unanswered` — a line nothing answers (a skip of the ceiling
  question, the offer form's "אין לי עדיין הצעה"), stored as the person's message with no model
  call and no reply; the model never reads it.
- `POST /api/checks/{check_id}/market-sample` — the market-data sample, answered from the
  engine's data.

### Event stream

- `GET /api/checks/{check_id}/events` — the check's event log replayed, then live events, as
  server-sent events; `Last-Event-ID` resumes after a stored event
  ([Events](architecture/agent.md#events)).

### Probes and the page

- `GET /health` — answers while the process runs.
- `GET /ready` — also needs the database to answer; 503 when it does not.

The built page is served at `/`, behind every route above
([Serving](architecture/page.md#serving)).

## Loan engine MCP server (`engine` service)

The engine serves Streamable HTTP at `/mcp`, stateless, with JSON responses. The agent is its
only caller, with the bearer token `ENGINE_BEARER_TOKEN`; the Host header allow-list
(`ENGINE_ALLOWED_HOSTS`) must name every Host value the engine answers. MCP Inspector calls the
same tools ([Try the engine with MCP Inspector](development.md#try-the-engine-with-mcp-inspector)).

- `simulate_loan` — a short text summary for the model; the full result, schedule included, as
  structured content.
- `simulate_scenario` — a loan priced on a scenario the person named (a yearly CPI rise and a
  yearly prime rise, each given as a figure or as the average of the last N years, either one
  defaulting to today's assumption): today's payment, the highest payment and the total repaid,
  with no historical window.
- `suggest_tracks` — a fixed and a prime track priced from the published average bank rate, and a
  pension fund's fixed track linked to the CPI.
- `market_series` — today's prime and, for the latest months, the prime and the CPI's monthly
  change, with the Bank of Israel's latest average rate on new consumer loans and its month.
- `propose_term` — the shortest term, in 6-month steps, at which both suggested tracks' first
  payment is below a limit, else 84 months, with that first payment.
- `propose_offer_term` — the same search for one real offer, up to the longest term it allows.
- `shortest_comfortable_term` — the shortest term, in 6-month steps up to 84, at which every
  suggested track's worst-case payment is at or below a ceiling, or with `any_track` at least one;
  null when none is.
- `shortest_comfortable_offer_term` — the same search for one real offer, up to the longest term it
  allows.
- `largest_comfortable_loan` — the largest loan, in whole thousands of shekels, on which at least
  one suggested track's worst-case payment fits a ceiling at a given term; null when none does.
- `assess_affordability` — the payment ceiling from net fixed income and fixed expenses, with the
  two caps it is the lower of and reason codes.
- `offer_readings` — the one-track loans an offer may mean, from the number it states or from its
  monthly payment alone, each with its first payment and today's total rate, and the fixed rate the
  payment amounts to.

The model calls `simulate_loan` and `market_series`; the agent's own check code calls the
rest, `offer_readings` among them, so the examples, the term card, the ceiling, the reading of
a vague offer and the guardrail's remedies come from code rather than from the model's choice
of tool
([architecture/agent.md](architecture/agent.md#tools)).

**Resources:** `rates://boi/history`, `rates://cpi/history` and `rates://current`.
