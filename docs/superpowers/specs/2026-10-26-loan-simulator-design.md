# Loan simulator: design

A Hebrew-only AI agent that will help a person decide on a short- or medium-term loan (a car, a
renovation, a consumer purchase): how much to borrow, how much savings to keep, for how long, and
on which track. The model will lead the conversation and decide what to ask; code will compute
every number and set the bounds the recommendation must respect. Each track will be shown with
what it costs today and what it would have cost had interest rates or inflation moved as they did
in the worst comparable period on record.

Status: the loan-engine MCP server (section 4) exists in `mcp-server/`; the agent, the page,
sign-in and the evals are OPEN, not yet implemented. Statements about them below use "will" or
"should".

Product name in the UI: "סימולטור הלוואות". It will give a concrete recommendation; the name
reflects that it simulates rather than sells or brokers loans. A legal check of the credit-advice
regulation in Israel is OPEN and must come before the agent is opened to the public; phase 1 will
serve the family.

Repo: `~/projects/python/loan-simulator` (the designer's name; the user may rename).

## 1. Why this exists

The reference user is a young adult buying a car. She has a trade-in car worth about 20,000 ₪,
15,000 ₪ in savings, a car budget of 50,000-60,000 ₪, rent of 3,000 ₪, about 10,000 ₪ gross from
a salaried job and about 5,000 ₪ from waitressing that varies every month. She needs someone to ask
the right questions, tell her how much she can safely commit to each month, how much savings to
keep, how big the loan should be, and what the risk is on each track, in numbers she understands.

A Custom GPT or Claude Project does not fit: the person must be able to keep several options,
compare them, and stop a check and resume it days later with the same figures. That needs owned,
structured state.

A controlled workflow like home-finance-agent (code decides every step, the model only narrates)
does not fit either. The interview differs from person to person: unstable income, a second loan,
"I hate surprises" all change what to ask next and which track fits. A fixed question list is
either too long or too short. The model will decide the path; code will keep the numbers and the
bounds. The agent will also be a portfolio piece: the user's first project where the model chooses
and calls tools, and the first standalone MCP server.

## 2. Goals, non-goals, anti-goals

Goals (phase 1):
- A guided conversation in natural Hebrew that builds a financial profile, takes a goal ("a car of
  55,000 ₪"), and ends with a concrete recommendation (section 6).
- Several checks per person (a car, a renovation), each holding its own options; a check can be
  paused and resumed at any later time.
- Real market data: Bank of Israel interest rate and the consumer price index, current and
  historical.
- Every number on screen computed in code. The model should ask, interpret, weigh and explain; it
  should never produce a figure.

Non-goals (phase 1):
- Mortgages. The loan model (section 7) is a list of tracks, so a mortgage would later add tracks
  and conversation, not a rewrite.
- Connections to lenders or comparison sites. Rates on offers will come from the person.
- Any integration with ChatGPT, Claude or other assistant hosts. The MCP server will be consumed
  only by this agent.
- Any link to home-finance-agent.
- Phone access from outside the machine. Phase 1 will run on localhost like home-finance-agent;
  the page should still be built for phone and laptop widths so that nothing changes when it is
  hosted.
- Horizontal scaling (replicas, Redis). One agent container.
- A local LLM. The provider will be configurable (section 8), so a local model could be tried later
  against the evals; it is not planned.

Anti-goals: the user named all of these as failures even when the numbers are right.
- Interrogating: a long run of questions before the first useful output.
- Evasive: "it depends, consult a professional" instead of a recommendation.
- Alarming: every variable track presented as dangerous, leaving the person confused.
- Condescending or technical: terms such as שפיצר, מרווח, הצמדה used without a plain explanation.
- Hebrew that reads as a translation.

## 3. The agent

### The loop

A LangGraph agent loop: model, tools, model again, until the model has something to say to the
person. There will be no fixed stage graph. The model will decide what to ask, when it knows
enough to give a first rough range, which tool to call and what to do with the result. Each check
will have one LangGraph thread (the conversation state LangGraph saves after every step), stored
in Postgres, so pausing and resuming come from that saved state.

The loop will run on the agent's own model through LangChain; MCP tools will be loaded into it
with `langchain-mcp-adapters` (the designer's call).

### Two kinds of tools

**MCP server tools, for numbers and bounds** (section 4). Policy comes back as bounds with reason
codes: a monthly payment ceiling and a minimum savings cushion. It is not a verdict; the model
should decide within the bounds and explain why.

**Agent-local tools, for the person's data** (the designer's call: personal data stays with the
agent): `update_profile`, `set_goal`, `save_option`, `present_recommendation`. Code will validate
every argument against the domain model and reject bad input with a message the model can act on.

### Guardrails in code, not in the prompt

- `present_recommendation` will take the chosen option ids and the model's reasoning. Code will
  reject it when an option's worst-case payment exceeds the ceiling or the cushion left is below
  the minimum; the model will receive the rejection and reconsider. This is how "the model decides
  within bounds" will be enforced.
- The recommendation card (section 6) will be built from stored tool results. The model's
  reasoning will appear as text next to it; its numbers will never be copied into the card.
- A figure the person types ("בערך 10 אלף ברוטו") will be extracted by the model into
  `update_profile` and shown in an editable profile panel on the page, so she can see and correct
  what was understood. A number the person stated is not a number the model produced.
- Per-person rationing of model spend, like home-finance-agent's per-person limit on starting
  reviews: a configured cap on conversation turns per period, with a clear Hebrew message when it
  is reached. The exact cap is the builder's call.

### Where the model's judgment shows

The model should interpret vague income ("sometimes 2,000, sometimes 7,000": unstable, maybe
seasonal); catch contradictions ("rent is 3,000 but fixed expenses total 2,500?"); weigh
preferences with no formula ("I hate surprises" favours a fixed track); give a rough range as soon
as income and expenses are known, before the profile is complete; and explain a term in plain
Hebrew only when she needs it.

### What the model is told

The system prompt will state the role (a simulator that gives a concrete recommendation), the
anti-goals as behaviour rules, the tool contract (numbers only from tools), and the conversation
arc (section 5) as guidance, not as a script. Before offers exist, it will tell her a fixed
CPI-linked track is a type worth asking the bank about, without quoting a rate, since no published
series prices it. Prompt text is the builder's; the evals will judge it.

## 4. Loan-engine MCP server

A standalone Python project in `mcp-server/`: its own `pyproject.toml`, Dockerfile and tests. It
will share no code with `backend/`; the contract between them is only the MCP tools and resources.
Moving it to its own repo later would be moving a folder.

It knows nothing about people and stores nothing personal. It takes a profile and loans, and
returns results.

- **Tools** (coarse, task-shaped; names are the builder's):
  - assess affordability: profile → payment ceiling, minimum cushion, reason codes.
  - size the loan: goal price, trade-in, savings, cushion → loan amount.
  - simulate a loan: loan → today's payment, total repayment, worst historical window and the
    range across windows (section 5), plus the full schedule as structured content for the page.
  - suggest tracks: loan amount and term → a fixed and a prime track priced from the published
    average bank rate.
  The simulation's text content is a short summary sized for the model; the agent will pass the
  schedule to the page without putting it in the model's context.
- **Resources:** rate and CPI history and current values, for example `rates://boi/history`.
- **Policy** (ceiling as a share of fixed net income, how variable income counts, cushion size)
  lives here as code with tests. The specific numbers are the builder's to propose and the user's
  to approve; each is documented with its reasoning in `docs/calculations.md`. Which tracks suit
  which stated preference is OPEN: the engine has no rule for it yet.
- **Typical tracks** come from the Bank of Israel's published monthly average rate on new
  unindexed household consumer loans (series `BNK_99010_LR_BIR_1893`, 7.9% for 2026-08): a fixed
  track at that rate and a prime track at that rate minus the month's prime. No published series
  covers CPI-linked consumer loans, so a linked track enters only as a real offer. Nothing is
  estimated.
- **Transport:** Streamable HTTP, reachable inside the Compose network and on one port published
  on the machine's loopback interface for MCP Inspector. Every call presents a static bearer token
  from configuration; the agent will present the same token.
- **Tests:** unit tests of calculations and policy, plus protocol-level tests through an MCP
  client.

### Market data

Both sources were checked on 2026-10-26; neither needs a key:
- Bank of Israel rate, daily, from 1994-01-27:
  `https://edge.boi.gov.il/FusionEdgeServer/sdmx/v2/data/dataflow/BOI.STATISTICS/BR/1.0/MNT_RIB_BOI_D?startperiod=YYYY-MM-DD&format=csv`.
  The server rejects a default library User-Agent; send a browser-like one. Latest value 3.25
  (2026-10-26). Prime = Bank of Israel rate + 1.5.
- CPI general index (code 120010), monthly:
  `https://api.cbs.gov.il/index/data/price?id=120010&format=json&download=false&startPeriod=MM-YYYY&endPeriod=MM-YYYY`
  (also `last=N`). Values sit on a base that changes every two years (`currBase`); each month also
  carries `percent`, the monthly change, which chains across bases. Latest: September 2026.

The server fetches on start and refreshes daily, keeping the series in a JSON file on a Docker
volume (`docs/market-data.md`). If a source is unreachable the last stored series is used and
every result carries its data date; with no stored series at all the server fails loudly instead
of computing on missing data.

## 5. Conversation arc and risk from history

### Arc (guidance for the model, not a script)

1. **Profile.** Net fixed income (the agent will ask for the net figure from the payslip and work
   only in net; there will be no gross-to-net estimate), variable income and its stability, rent
   and fixed expenses, savings, existing loans, trade-in value.
2. **Goal.** "A car of 55,000 ₪". The goal is the price; the loan amount is derived.
3. **First recommendation.** Ceiling, cushion, loan amount, and two or three track types priced
   with the published average bank rate, labelled on screen as such.
4. **Pause.** The person will collect offers from banks, card companies or the importer.
5. **Resume.** She will enter real offers. An offer will hold: nominal rate or prime plus spread,
   CPI linkage, term, repayment method, one-time and monthly fees, balloon amount, lender and date.
   Each will become an option, with its true cost computed by the engine.
6. **Compare.** The card will be recomputed on the real offers: a preferred option and an
   alternative. The preferred option should be the cheapest in total cost among those whose
   worst-case payment stays under the ceiling; the model may argue for another on stated
   preferences, within the bounds.

The person will be able to edit the profile or the goal at any point.

### Risk from history

For each variable track (prime-based, CPI-linked, or both) the server replays every historical
window as long as the loan term:
- It applies the **changes** from the window, not its levels: if the rate rose 4.65 points over
  2022-2023, the replay raises today's rate by the same amounts on the same schedule. For CPI it
  applies the window's actual monthly inflation. This keeps 1990s rate levels from distorting the
  result.
- The **worst window** is the one with the highest monthly payment, since that is what she must be
  able to pay. Total cost per window will be shown in the card's folded explanation (section 6).
- On a track with both prime and CPI exposure, both series move together as they did in the
  window.
- The card will show the worst window as one number with its period: "עד ~640 ₪ אם הריבית תעלה
  כמו ב-2022". Its folded explanation will show the range across all windows.
- Rate kinds in phase 1: fixed, prime plus spread; each CPI-linked or not. A variable rate on
  another index is not modelled.
- History windows start within the last ten years of the series (a rolling 120 months), though
  both series reach back to 1994; `docs/calculations.md` states the reason.

## 6. The recommendation card (the layout the user chose)

The page will work on a phone and on a laptop: chat and cards side by side on a laptop, cards
below or in a tab on a phone. Right-to-left throughout. Beside the chat: the editable profile
panel and the list of the person's checks.

- **Top:** the decision in one sentence: loan amount, term, monthly payment, savings left.
- **Middle:** one or two options as cards. Each will have today's payment and a coloured chip:
  green when the payment cannot change, amber with the worst-case number when it can.
- **Bottom, folded:** why this cushion, why this ceiling, the assumptions (current rate and CPI with
  their dates, the published average bank rate used when no offer is entered yet), total cost per
  option.

## 7. Domain model

Profile, Check and Option will live in the agent. Loan and Track exist in the engine
(`domain/models.py`).

- **Profile** (one per person, shared by all checks): incomes (fixed, variable with a stability
  note), expenses, savings, existing loans, assets such as a trade-in car. When the profile
  changes, other checks will be marked as computed on an older profile and offer a recompute.
- **Check** (per person, many): a goal (purpose and price), the profile snapshot it was computed
  on, its options, the latest recommendation, and the conversation thread.
- **Option** (per check, many): a loan with its source (the published average bank rate, or an
  offer).
- **Loan:** a list of tracks whose principal sums to 10,000-100,000 ₪. Phase 1 loans will have one
  track; the engine accepts several.
- **Track:** principal, term in months, rate kind (fixed, prime + spread), CPI linkage, repayment
  method (equal payments known as שפיצר, equal principal, balloon), fees.

## 8. Architecture

```
browser ──► agent (FastAPI + LangGraph loop) ──MCP over Streamable HTTP──► loan-engine MCP server
                 │                                                             │
                 ▼                                                             ▼
            Postgres: agent schema                         Bank of Israel SDMX API, CBS price API
```

### Agent (`backend/`)

Python 3.12, LangGraph, FastAPI, React front end. It will mirror home-finance-agent's structure:
- Layers `platform → application → ports → domain`; `adapters` import only `ports` and `domain`;
  `lint-imports` will enforce it. The MCP client and the chat model will be adapters behind ports,
  so the loop can be tested with a scripted fake model and without the server.
- It will own everything about the person: sign-in, profile, checks, options, saved conversation
  state, the REST and streaming API for the page.
- The model provider will be configurable, OpenAI or Claude, as a `provider:model` string with no
  default in code. A strong model is required for natural Hebrew and sound judgment. Prompt
  caching is required for cost: stable system prompt and tool list first, the growing history
  after.

### Sign-in

Google sign-in only, from day one, in a Google Cloud project of its own that the user creates.
Same mechanism as home-finance-agent: the page will get a Google ID token and the agent will
verify it (signature against Google's keys, issuer, expiry, audience); the account's `sub` will be
the user id; the token will never enter the saved conversation state, and a test should search
every saved state for it; tests will sign their own tokens. Who may sign in will be the closed
list of test users on the OAuth app, which stays in testing mode, as in home-finance-agent. The
MCP server will never see the person's token.

## 9. Testing

- **Unit and protocol tests:** the MCP server's calculations, policy and tools (these exist); the
  agent's local tools and validation (OPEN).
- **Loop tests with a scripted fake model** (OPEN): tool wiring, guardrail rejection and the
  model's retry, resuming saved conversation state, the token never reaching that state.
- **Evals** (OPEN): recorded personas, starting with the reference user, played by a
  simulated-user model against the real agent. A judge model will score each conversation against
  the anti-goals: questions before the first useful output, a clear recommendation, a calm tone,
  plain terms, natural Hebrew. A code check will verify that every number in a reply appears in
  some tool result. Evals will run on demand (they cost money), not in `./scripts/test.sh`;
  `docs/testing.md` should state the cost per run.

## 10. Scripts and documentation

Same set and style as home-finance-agent:
- Scripts: `init-env.sh`, `start.sh`, `docker-helper.sh`, `lock.sh` and `test.sh` exist for the
  engine. `sql-helper.sh`, a `lock.sh` per further Python project, and `test.sh` targets for the
  backend, frontend and evals should follow with the agent.
- Docs in English, present tense, mermaid diagrams. These exist: `README.md` leading with the
  design, `CLAUDE.md` with "Facts that bite", `docs/architecture.md` as a map, `docs/testing.md`,
  `docs/calculations.md` (formulas, policy numbers with reasons, the historical replay) and
  `docs/market-data.md` (what is fetched, from where, how often, what happens when a source is
  down). OPEN: `docs/sign-in.md`, and sub-pages of `docs/architecture.md` for storage,
  configuration, codebase structure, and the agent loop and its guardrails.

## 11. Left to the builder

- Tool names and schemas (decided for the engine); the system prompt; the profile panel's fields.
- Policy numbers (decided, `docs/calculations.md`) and the turn cap, proposed with reasons for the
  user to approve.
- History span (decided: a rolling ten years).
- Where the MCP server keeps market data (decided: a JSON file on a Docker volume).
- Page layout details within the layout of section 6.
- The eval harness: persona format, judge rubric, cost reporting.
