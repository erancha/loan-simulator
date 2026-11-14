# 0008. A React page, built into the agent's image and served by it

- Status: Accepted
- Date: 2026-10-30

## Context

The agent answered over its HTTP API and an event stream, with no page in front of it. The page
must show a Hebrew, right-to-left conversation beside a profile panel and a recommendation card,
and sign-in rests on a `SameSite=Strict` cookie
([ADR 0005](0005-google-id-token-sign-in.md)), which a page on another origin could not send.

## Decision

- The page is a React and TypeScript app in `frontend/`, built with Vite.
- A Node stage of `backend/Dockerfile` builds it into the agent's image, and the agent serves the
  build at `/` from `AGENT_FRONTEND_DIST`, after its API routes, so page and API share one
  origin.
- The page holds no data the agent does not hold: one event stream per open check feeds a
  reducer, and every figure on the card comes from stored engine results.
- Money is formatted from decimal strings, never through a JavaScript number.

## Consequences

- One image and one port deliver the whole app, and the cookie needs no cross-origin setup.
- A change to the page needs a rebuild of the agent's image; `npm run dev` serves the page alone
  and proxies `/api` to the running agent.
- The page has its own gate in `scripts/test.sh`: oxlint, the TypeScript check, Vitest and the
  build.
