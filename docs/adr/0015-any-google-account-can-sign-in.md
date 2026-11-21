# 0015. Any Google account can sign in

- Status: Accepted
- Date: 2026-11-20

## Context

[ADR 0005](0005-google-id-token-sign-in.md) kept the Google client in testing mode and took its
test users as the access list, expecting Google to refuse any other account. On 2026-11-20 two
accounts outside the test users signed in to the deployment on EC2: Google showed them its
consent screen and returned an ID token. The page asks only for the name and email (`openid email
profile`), and for that Google does not hold a testing app to its test users. The owner has no
domain of their own yet, so the app cannot be published, and wants people to try it.

## Decision

- Any Google account may sign in. The agent adds no allow-list of its own.
- The message cap (`AGENT_TURN_LIMIT` a day, with per-person overrides) is what bounds a person's
  cost; every check stays visible only to the account that made it.

## Consequences

- Sharing the address is enough to bring someone in; the Google console's test users play no part.
- Model spend grows with whoever signs in, up to the cap times the number of people.
- Restricting access later means adding an email allow-list to the agent's sign-in check; Google's
  testing mode will not do it.
