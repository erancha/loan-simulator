# Workers' responsibilities and flows

This document details the work no request waits on, behind the parts that
[Architecture](architecture.md#the-parts) summarizes: the agent's conversation turns, the engine's
daily market-data refresh and the one-shot schema migration. The routes that start a turn are in
[API endpoints](api.md).

## `CheckRunner` turns

A turn is the agent's answer to one message, run by `CheckRunner` in
`platform/check_runner.py`. A person's message starts a turn:
`POST /api/checks/{check_id}/messages` stores the message and answers 202, and the turn runs as a
background task, so the reply arrives on the event stream. A check has at most one turn in flight
(a message during a turn answers 409); turns on different checks run concurrently. Turns live in
the process's memory, so the agent runs as one replica.

The messages a person may send, and the steps one turn may take, are in
[Turns and the turn cap](architecture/agent.md#turns-and-the-turn-cap); what a failed turn
leaves, and how startup ends the turns a stopped process left, in
[Failure and restart](architecture/agent.md#failure-and-restart).

## `_refresh_daily`

The engine's daily market-data refresh, `_refresh_daily` in `loan_engine/__main__.py`, runs
`refresh` ([Market data](market-data.md#refresh-and-fallback)). The service calls `refresh`
before it listens and then once a day, the server and the daily refresh running side by side;
the history the tools read is replaced after each daily refresh. A daily refresh that raises
ends the process, so the engine never goes on serving data it can no longer update.

## `migrate`

The Compose service `migrate` is a one-shot run of `alembic upgrade head` from the agent image,
after `db` is healthy; the agent starts once it has completed. Alembic migrates the agent's
tables, and the same run brings LangGraph's checkpoint tables to the installed library's version
([Data model](data-model.md#postgres)).
