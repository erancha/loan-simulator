# Testing

What each layer of tests proves, and how to run it; this page details the tests behind
[Development & deployment](development.md#backend-tests).

```bash
./scripts/test.sh            # every target (engine, backend and frontend)
./scripts/test.sh engine     # script syntax, ruff lint and format, mypy, import-linter, pytest
./scripts/test.sh backend    # the same gates for the agent
./scripts/test.sh frontend   # oxlint, tsc, Vitest, the Vite build (needs Node.js 22)
```

`.github/workflows/ci.yml` runs each target of `./scripts/test.sh` on every push and pull request.

No test reaches the Bank of Israel or the Central Bureau of Statistics: fetchers run against
recorded responses, and the server against stored histories built in the tests. No test reaches
Google or a model provider either: tests sign their own tokens and script the chat model. No
frontend test reaches the network: `fetch` and `EventSource` are stubbed. The
Postgres tests start a `postgres:16` container through testcontainers, so the backend target needs
Docker.

## Engine

**Static gates** fail the run before any test: `bash -n` on every script, ruff lint, ruff format
in check mode, mypy, and the import-linter contracts that keep `service → market → domain`
pointing inwards and the loan arithmetic off the affordability module.

**Domain** tests run on plain values: schedules for each repayment method with changing rates and
CPI, the historical replay and its worst window, the payment ceiling, and the term and loan
searches (the first-payment proposal, the comfortable terms with and without `any_track`, an
offer's own maximum, the largest loan, and the 84-month limit), each against hand-computed figures
from [calculations.md](calculations.md).

**Market** tests drive the parsers with recorded Bank of Israel and CBS responses, the monthly
alignment, the stored-series fallback when a source fails, and the failure when nothing is stored
([market-data.md](market-data.md)).

**Service** tests call the tools and resources through an MCP client against the real HTTP app:
the bearer token is required, the host allow-list holds, results are rounded to agorot, and
startup and the daily refresh fail loudly.

**Deployment files** are checked without Docker: `test_settings_files.py` requires the settings
files under `scripts/lib/` to document every engine setting and no other `ENGINE_` key (the
agent's test owns the rest), and `init-env.sh` to write settings the engine accepts, to keep an
existing file without `--force`, and to leave no settings file when a written value fails its
check; `test_compose.py` requires that the engine's published port binds to `127.0.0.1`
through the `ENGINE_HOST_PORT` and `ENGINE_PORT` variables, that the market data volume is mounted
and that the engine's container receives only its own keys; and `test_requirements_lock.py`
requires the lock to match `pyproject.toml` and the image.

## Backend

**Static gates** are the same as the engine's: `bash -n`, ruff, mypy and import-linter contracts
that keep `platform → application → ports → domain` pointing inwards, adapters off `application`
and `platform`, and the inner layers free of frameworks, except `langgraph` and `langchain_core`
in `application/agent_graph.py`.

**Domain and application** tests run on plain values and fakes: the finances' missing figures and
their refusals, a loan of 0 refused, a ceiling held only with its source, the option figures' JSON
encoding, the market-data answer's lines (an unchanged prime, a single change, a falling CPI), and
the check tools, each refusal with the message the model reads. The loan and term tools prove the
saved loan, an amount the engine does not price, the term card's 60 months for a car without a
ceiling and the ceiling deciding a car's term with one, the first-payment search without a ceiling,
the worst-case search with one, a term outside 6 to 84 months, and that the term the last card
showed is refused as a new card while another term gets one. The comparison tests prove the classes
of a gap (זניח, במקצת, ברור) on the figures of a real conversation, and that options of another term
are not compared. The offer tests prove an open offer priced at the confirmed term or at its shorter
maximum, a term change that prices open offers again and leaves fixed ones, an engine refusal there
that saves nothing, and an option saved again with the same figures refused while another lender's
is saved. The ceiling and finances tools prove a stated ceiling, a derived one that replaces it, a
bad figure or an engine refusal that saves nothing, and the request to recommend again after a
ceiling change. The guardrail's tests prove an unchecked recommendation without a ceiling and a
checked one within it, an option of another amount, an example of another term refused and not named
as fitting, and each answer above the ceiling: a refusal naming a saved option that fits, else a
recommendation presented above the ceiling with its remedy, a longer term, the largest loan when 84
months do not fit, and none for a ceiling too low for any loan; for a check with offers, the longer
term an open offer allows or the turn to the lenders, with no example search; and a balloon is
judged on its recurring payment. A saved offer deletes the check's examples with a recommendation
that names one, and an example is refused once the check holds an offer. The ask tool's tests prove
the emitted question and its fixed result, and its refusals: a field the check already holds, named
with its value, and English in the text. The offer form's tool tests prove the question it emits,
with what the person said or with nothing, and its refusal of a check with no loan. The state
block's tests prove the loan, term, ceiling and recommendation states, and the previous check's
finances.

The agent graph runs against a scripted fake chat model, which proves tool wiring, that every tool
the system prompt names is bound, ask among them, that it lists the same loan sources as the page,
the model's retry after a refusal, resuming a saved conversation, and that the person's ID token
never reaches a checkpoint (a test scans every saved blob). For ask it proves that the turn ends
after a successful ask, even beside a failed sibling call, and that each refusal returns to the
model as an error result: two asks in one message, a question with both or neither of field and
text, an empty question, a single choice. For the recommendation section it proves that one written
without its tool is discarded and redone once, and that a call from an earlier turn does not count.
For the state block it proves that a figure the page saved reaches the model without a tool call,
that the block is built fresh at each model call within a turn and is absent from the checkpoint,
and that `ask_term` ends the turn like `ask`, refused beside a second question.

**Adapters** tests cover the engine client against a stub MCP server, Google token verification
against tokens signed in the tests, and the Postgres repositories on a real database: a check's
loan, term, ceiling and finances round trip, a stored finances object with a missing figure is
refused, the latest finances skip the current check and incomplete ones, and a clone copies all
of them.

**Platform** tests drive the HTTP API through the real app with fake infrastructure: sign-in and the
401 answer on every route outside a short public list and the 404 answers, the check routes and `PUT
/api/checks/{id}/finances` and `/term` (with and without a ceiling) with their 404, 409 and 422
answers, the event stream's replay, each stored frame's time, Last-Event-ID resume and its dropping
of fragments the replay already sent complete, the turn cap with its per-person overrides, the
conflict answers, deleting a check with its conversation, which gives no messages back under the
cap, cloning a check with its log and conversation, whose copied messages use none of the cap, with
the handoff event left on the source and not copied to a later clone, the refusal of a message to an
archived check, archiving by the person and restoring, the runner's streaming and failure events, a
turn after a model failure, the turn step limit, a turn ended at the third identical tool call, the
market-data sample answered from the data with no model call and kept in the conversation, the
offer chip answered with the offer form and no model call and recorded for the next turn, the
ceiling typed on the term card saved with a card for it and no model call, the ceiling question the
runner asks once after a recommendation without a ceiling, and not over a question of the model's,
restart recovery, settings validation, and that the migration builds the tables, matches the ORM,
downgrades, and refuses to run its loan-first step on a database that still holds checks.

**Deployment files** are checked without Docker, as for the engine: each service's
`test_settings_files.py` requires the settings files to document its keys and nothing else
(together every key is owned once), the committed `stack-params.sh` to hold no secret, and
`init-env.sh` to write settings the services accept;
`backend/tests/test_compose.py` requires every published port to bind to `127.0.0.1` through its
variable, the agent to wait for the database, the migration and the engine, and each container to
receive only the keys it reads.

## Frontend

**Static gates** fail the run before any test: oxlint (including the rules of hooks), `tsc -b`
over the app and the config, and, after the tests, the Vite build the Docker image also runs.

**Reducer.** `events.test.ts` replays recorded events into the state: a replay builds the
conversation in order, a reply fragment is replaced by its complete message and ignored after it, a
repeated sequence number changes nothing, a second save of one option keeps its place, options saved
after a recommendation are tracked until the next recommendation, removed examples leave the
options with the recommendation when it named one, and a turn end is counted only when a running
turn goes idle. Its liveness tests prove that a question becomes an entry that is
live once the turn is idle, that no question is live while a turn runs, and that status and
finances events leave it open while a person's message closes it. The loan, term, ceiling and
finances events set the check's figures, and an archive and a restore add and drop the closing
note.

**Card.** `card.test.ts` maps stored results to what the card shows: the decision sentence, the
green and amber chips for each kind of track (prime, linked, balloon), the offer sources, the three
group titles, the three check states (unchecked, fits with the ceiling and its source, above with
both payments), the examples for another term left out of the group while offers stay, the other
options cheapest first, and the error for a recommended option that is not saved.
`RecommendationCard.test.tsx` renders the model: the labelled options, the chip that marks an
example and not a real offer, the open and closable fold, and the empty states.

**Event stream hook.** `useCheckEvents.test.ts` runs the hook against a fake `EventSource`:
frames reduce into state, a fragment carries no sequence number, a malformed frame is reported
and skipped, switching checks closes the old stream, and a closed stream signals sign-out.

**Figures panel.** `FinancesPanel.test.tsx` proves that a save puts the figure and then sends its
update line, that a refused save shows the rejection and sends nothing, that the panel shows a
stated or a derived ceiling with its source, and that a read-only panel takes no edit.

**Chat.** `Chat.test.tsx` proves the bubbles, the thinking bubble, the input locked while a turn
runs, Enter against Shift+Enter, the text kept when a send is refused, and that the log follows
new and streamed text and content that grows by itself until the reader scrolls up. It also proves
that a question is its own turn with a control only while live, that a question ending the
conversation is announced with its lead-in and label, that the opening line stays first, and
that a sample fills the input without sending until the model asks its first question, that the
market-data sample stays after a tap, and that the offer chip sends its sentence on the tap.
`serverSamples.test.ts` proves which wordings count as the market-data sample and as the offer
chip's sentence.

**Question bubble.** `QuestionBubble.test.tsx` proves each control and the line it sends: a money
answer saved and sent, a loan amount sent without a save, purpose choices with no text box, free
questions with and without choices, the skip line, and the ceiling question's "לא יודע/ת". The term
card shows its term and first payment, starts its two boxes at the proposed term and the check's
ceiling, confirms the term in its box with a new ceiling only when one was typed, asks for a card
from a new ceiling when the term is left as proposed, refuses a term outside 6 to 84 months or a
cleared ceiling, and has one button. It also proves that a refused save or a non-number keeps the
question open with its reason, and that a closed bubble shows only the question.

**Check page.** `CheckPage.test.tsx` replays a recorded conversation into all three panes and proves
sending, the cap notice with the local time on a 429, the silent 409, the clone offer's two choices,
and when the checks list changes: once when a turn this page started ends, and not for replayed
turns. For questions it proves that a finances answer is saved to the check and then sent as a line,
that a refused save sends nothing, that a capped send after a saved answer keeps the bubble, that a
skip sends its line without a save and a failed skip keeps the bubble, and that a typed message
closes the live question. For the term card it proves that the confirm button and the card's number
typed in the chat both save the term before sending "אישור: 78 חודשים", that a new ceiling alone is
one request with its line, that another term with a new ceiling saves both before the line, and that
another number typed in the chat goes to the model as text. For the figures panel it proves that it
stays hidden until the check has figures, that an edited figure is saved and followed by its update
line, and that a running turn or an archived check offers no edit.

**Offer form.** `OfferForm.test.tsx` proves the message the form words from a lender, its tracks
and the longest period; that an empty box, a percentage above 30, a lender of spaces or a period
that is no whole number of months in range is marked and nothing is sent; that a comma or a
percent sign in a percentage is read as the number; that the boxes start with what the assistant
passed, a margin under prime as "פריים מינוס"; that rows are added up to four and removed; and
that an answered form shows no boxes.

**Shell and sign-in.** `Shell.test.tsx` proves the header and sign-out, the empty state and creating
a check, the list's titles, terms and markers, the archived checks folded in their own group
(unfolded on load when every check is archived), cloning from the list, the archive icon of a live
check, the absence of both the duplicate and archive icons on a check holding only the opening
line, that archiving the open check opens the newest live one or a new check, the restore icon of
an archived one, the side tab named "בדיקות", selection by hash and the fallback to the newest
check, the tab bar, and that a late list answer does not overwrite a newer one. Its
delete tests, on archived checks, the only ones with a delete icon, prove the confirmation and its
cancel, that the newest check left opens, that the last one leaves the empty state, and the refusal
during a reply. `App.test.tsx` proves the Hebrew right-to-left document, the sign-in screen,
entering the app and the fall back to sign-in on a 401. `money.test.ts` and `client.test.ts` cover
the amount formatting from decimal strings and the API client's errors. `demo/backend.test.tsx`
proves that the demo replays its recording into the page, lists the check with the loan and term
the replay has set so far, lists a recorded clone's source once the replay passes the clone and
streams its whole history, refuses a source that ends at an event the recording lacks, and refuses
a request the page is not known to make.

**By hand.** jsdom has no layout, so the three columns and the tabs are checked in a browser after
`./scripts/deploy.sh`, at laptop and at phone width.

**Not covered here.** A Hebrew conversation against a real model needs `LLM_MODEL`, `LLM_API_KEY`
and `GOOGLE_CLIENT_ID`; it is run by hand after `./scripts/deploy.sh`.
