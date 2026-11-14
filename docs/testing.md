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

**Domain and application** tests run on plain values and fakes: the profile's missing fields and
staleness, with the variable income minimum not missing while variable income is 0 and refused above
variable income, the option figures' JSON encoding, the check tools, and the guardrail's refusals
(no loan needed, principal below the sized loan, a sized loan beyond the engine's maximum,
worst-case payment above the ceiling), each with the message the model reads. The ask tool's tests
prove the emitted question and its fixed result, and its refusals: a profile field already stored,
named with its value, the variable income minimum while variable income is 0, and a clone offer in
a check with no recommendation. The profile save's tests prove that a changed figure archives the
checks recommended from the replaced figures, with the whole replaced profile and the change in
the event, and that a collecting check, a stale one and a save of the same figures archive none.

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
and that the minimum reads "not needed" while variable income is 0.

**Adapters** tests cover the engine client against a stub MCP server, Google token verification
against tokens signed in the tests, and the Postgres repositories on a real database, a check's
delete and a save that changes nothing, which keeps its save time, among them.

**Platform** tests drive the HTTP API through the real app with fake infrastructure: sign-in and the
401 answer on every route outside a short public list and the 404 answers, profile and check routes,
the event stream's replay, each stored frame's time, Last-Event-ID resume and its dropping of
fragments the replay already sent complete, the turn cap with its per-person overrides, the conflict
answers, deleting a check with its conversation, which gives no messages back under the cap, cloning
a check with its log and conversation, whose copied messages use none of the cap, the refusal of a
message to an archived check, archiving by the person and restoring only a check whose figures still
match the profile, a profile change in a recommended check that goes on in a new check, the runner's
streaming and failure events, a turn after a model failure, the turn step limit, restart recovery,
settings validation, and that the migration builds the tables, matches the ORM and downgrades.

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
after a recommendation are tracked until the next recommendation, and a turn end is counted only
when a running turn goes idle. Its liveness tests prove that a question becomes an entry that is
live once the turn is idle, that no question is live while a turn runs, and that status and profile
events leave it open while a person's message closes it.

**Card.** `card.test.ts` maps stored results to what the card shows: the decision sentence, the
green and amber chips for each kind of track (prime, linked, balloon), the spare savings, the offer
sources, the three group titles, and the errors for a reason code without a sentence or a
recommended option that is not saved. `RecommendationCard.test.tsx` renders the model: the labelled
options, the chip that marks an example and not a real offer, the open and closable fold, and the
empty states.

**Event stream hook.** `useCheckEvents.test.ts` runs the hook against a fake `EventSource`:
frames reduce into state, a fragment carries no sequence number, a malformed frame is reported
and skipped, switching checks closes the old stream, and a closed stream signals sign-out.

**Profile panel.** `ProfilePanel.test.tsx` proves that a field saves on blur and sends only what
was edited, that typed money is normalised and an unchanged value sends nothing, that a refused
value keeps the text and shows its message, that a live profile replaces the values, and that
responses arriving out of order end on the later save.

**Profile store.** `profileStore.test.ts` proves that a save from the chat marks the field and
leaves the panel folded while a save from the panel marks nothing, and that a refused save
rejects with the server's reason and keeps the shown profile.

**Chat.** `Chat.test.tsx` proves the bubbles, the thinking bubble, the input locked while a turn
runs, Enter against Shift+Enter, the text kept when a send is refused, and that the log follows
new and streamed text and content that grows by itself until the reader scrolls up. It also proves
that a question is its own turn with a control only while live, that a question ending the
conversation is announced with its lead-in and label, and that a panel note follows the entry it
was made after, or the opening line in an empty chat.

**Question bubble.** `QuestionBubble.test.tsx` proves each control and the line it sends: a money
answer saved and sent, the variable income minimum answered or skipped as 0, purpose choices with
no text box, a price, free questions with and without choices, and the skip line. It also proves
that a refused save or a non-number keeps the question open with its reason, and that a closed
bubble shows only the question.

**Check page.** `CheckPage.test.tsx` replays a recorded conversation into all three panes and
proves sending, the cap notice with the local time on a 429, the silent 409, the stale banner and
its fixed recompute message, the clone offer's two choices, opening the check a conversation went
on in only after this page's own send, and when the checks list changes: once when a turn this
page started ends, on a profile save, and not for replayed turns. For questions it proves that a
tapped answer is saved and then sent as a line, that a capped send after a saved answer keeps the
bubble, that a skip sends its line without a save and a failed skip keeps the bubble, and that a
typed message closes the live question. For panel edits it proves that an edit of the asked
field answers the question, that any other edit shows as a note, that an answer that is not
accepted is noted instead, and that a note made while a reply streams outlives the reply being
dropped.

**Shell and sign-in.** `Shell.test.tsx` proves the header and sign-out, the empty state and creating
a check, the list's markers, the archived checks folded in their own group (unfolded on load when
every check is archived), cloning from the list, the archive icon of a live check and the restore
icon of a restorable one, selection by hash and the fallback to the newest check, the tab bar, and
that a late list answer does not overwrite a newer one. Its delete tests, on archived checks, the
only ones with a delete icon, prove the confirmation and its cancel, that the newest check left
opens, that the last one leaves the empty state, and the refusal during a reply. `App.test.tsx`
proves the Hebrew right-to-left document, the sign-in screen, entering the app and the fall back
to sign-in on a 401. `money.test.ts` and `client.test.ts` cover the amount formatting from decimal
strings and the API client's errors.

**By hand.** jsdom has no layout, so the three columns and the tabs are checked in a browser after
`./scripts/deploy.sh`, at laptop and at phone width.

**Not covered here.** A Hebrew conversation against a real model needs `LLM_MODEL`, `LLM_API_KEY`
and `GOOGLE_CLIENT_ID`; it is run by hand after `./scripts/deploy.sh`.
