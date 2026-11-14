# 0001. The loan engine is a standalone MCP server

- Status: Accepted
- Date: 2026-10-26

## Context

The loan simulator is to be a Hebrew agent that advises a person on a consumer loan. A language
model can lead the conversation, but it cannot be trusted with arithmetic: a payment it writes
may be plausible and wrong. Every figure a person sees must come from code, priced on current
Bank of Israel and CBS data. No agent existed yet, and the agent framework was still open, so
the calculations had to be usable by whatever agent came next, and testable by hand before it.

## Decision

- The calculations live in their own Python service, `mcp-server/` (package `loan_engine`), an
  MCP server whose tools take a profile or a loan and return numbers and bounds.
- It serves MCP over Streamable HTTP at `/mcp`, stateless, with JSON responses, behind one fixed
  bearer token (`ENGINE_BEARER_TOKEN`) and a Host header allow-list.
- It knows nothing about people: it stores no profile and receives no sign-in credentials.
- Money is `Decimal` throughout; values are rounded to agorot only where they leave the server.
- Layers `service → market → domain`, with pure calculations in `domain`, enforced by
  import-linter.

## Consequences

- Any MCP client can call the tools, MCP Inspector included, which makes the engine testable by
  hand with no agent running.
- The agent reaches the engine over the network, with its own token, and keeps every personal
  record on its side.
- The engine's MCP SDK version is chosen independently of the agent's libraries, so the two never
  share a virtualenv.
- A tool's text result is read by a model, so `simulate_loan` sends a short summary as text and
  the full schedule only as structured content.
