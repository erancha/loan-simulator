# 0005. Sign-in is a Google ID token, checked on every request

- Status: Accepted
- Date: 2026-10-28

## Context

The agent holds a person's income, expenses and savings, so every record must belong to a
signed-in person. The app has a handful of invited users and no wish to store passwords, run a
session store or pass a person's credentials on to the loan engine.

## Decision

- People sign in with a Google account only. The page obtains a Google ID token and posts it to
  the agent, which verifies it locally: Google's published keys, the issuer, the expiry, and an
  audience equal to `GOOGLE_CLIENT_ID`.
- The agent returns the token as an HttpOnly, `SameSite=Strict` cookie that lasts until the
  token expires; there is no server-side session, and every protected route verifies the cookie
  again.
- The account's `sub` claim is the user id; another person's check answers 404.
- The token goes no further than the verifier: it never enters a checkpoint, and the engine
  receives only its own bearer token.
- The Google client stays in testing mode, so its list of test users is the access list; the
  agent's code has no allow-list.

## Consequences

- Adding or removing a person is done in the Google Cloud console, and Google limits a testing
  app to 100 test users.
- A person signs in again when the token expires, after about an hour.
- Google accepts only `localhost` or a public hostname as an origin, so the app is reachable
  for sign-in only through one of those.
