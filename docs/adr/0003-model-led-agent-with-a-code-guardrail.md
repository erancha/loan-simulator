# 0003. A model-led LangGraph agent, with a guardrail in code

- Status: Superseded by 0010
- Date: 2026-10-28

## Context

The repo held the loan engine alone: a server that answered tool calls, with nothing to lead a
conversation over them. A hosted assistant (a custom GPT, a Claude project) could call the tools,
but a person saves several options, compares them, and pauses a check to collect offers from
banks and resumes it days later: state the app must own. A scripted question flow would be
cheaper per conversation but stiff for a person who brings an offer, a vague price or a
question of their own.

## Decision

- The agent is a FastAPI service in `backend/` (package `loan_agent`) that runs each check as
  one LangGraph thread: a model node and a tool node, with the engine's tools and the agent's own
  check tools.
- The model chooses what to ask and which tool to call; the Hebrew system prompt sets its manner
  and the arc of a check.
- The model never produces a figure. `present_recommendation` recomputes the engine's bounds and
  refuses an option that borrows less than the sized loan or whose worst-case payment is above
  the ceiling; the model reads the refusal and tries again.
- The thread is checkpointed after every step, so a check resumes after a restart, and a failed
  turn leaves the conversation where it was.
- Layers `platform → application → ports → domain`, with `adapters` implementing the ports; only
  `application/agent_graph.py` imports LangGraph.

## Consequences

- Each message costs several model calls, so a person's messages are capped per rolling window
  and one turn is bounded by a step limit.
- Turns in flight live in the process's memory, so the agent runs as one replica.
- The quality of a conversation depends on the model and the prompt, which unit tests cannot
  judge.
