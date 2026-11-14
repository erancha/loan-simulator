# 0006. The chat model is one setting, `provider:model`

- Status: Accepted
- Date: 2026-10-28

## Context

The agent leads every conversation with a chat model
([ADR 0003](0003-model-led-agent-with-a-code-guardrail.md)). Price and quality move between
providers month to month, and the owner's other repositories already name a model as
`provider:model` in one setting next to one key.

## Decision

`LLM_MODEL` names the model as `provider:model`, with `anthropic` and `openai` as the supported
providers, and `LLM_API_KEY` holds that provider's key. The agent builds the model through
LangChain's provider-neutral constructor, and refuses to start when the setting is blank or
names another provider.

## Consequences

- Switching provider is an edit to two settings and a restart, with no code change.
- The agent's image carries the LangChain package of each supported provider.
- The tests script the chat model, so no test reaches a provider; a real conversation is a
  manual check, since it needs a key.
