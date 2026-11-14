# 0007. The stack runs under Docker Compose on one machine

- Status: Accepted
- Date: 2026-10-26

## Context

The first part of the simulator was the loan engine alone, with an agent, a database and a page
to follow. It had to run the same way on a developer machine and on a single small host, keep
its market data across restarts, and be reachable by MCP Inspector during development without
being exposed to the network.

## Decision

- `docker-compose.yml` defines every service, built from the repo root; settings come from files
  under `scripts/lib/`: the committed `stack-params.sh`, and the gitignored `params.sh` and
  `secrets.sh`, each documented key by key in its `.example.sh`.
- Compose hands each container only the keys it reads, so no service receives another's secret.
- The engine's market data lives in a named volume, `engine-data`.
- Every published port binds to `127.0.0.1` only.
- The scripts under `scripts/` create the gitignored settings files, start the stack and wait
  until it answers.

## Consequences

- One machine runs the whole simulator, so there is no failover, and the agent does not scale
  out beyond that machine.
- The services reach each other by name inside the Compose network, while the settings files hold
  the host forms of the addresses for processes run on the host.
- Tests check the Compose file without Docker: the loopback bindings, the volume and each
  container's keys.
