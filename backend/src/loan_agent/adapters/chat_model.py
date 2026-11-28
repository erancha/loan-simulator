"""Builds the agent's chat model from a provider:model spec and an API key."""

from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from loan_agent.adapters.model_call_log import ModelCallLog


def build_chat_model(
    spec: str, api_key: str, kind: str, reasoning_effort: str | None = None
) -> BaseChatModel:
    """spec: provider and model, e.g. anthropic:claude-haiku-5-5 or openai:gpt-5-mini, one whose
    prices model_costs.py lists; kind: what its calls are for, the group docker-helper.sh --costs
    sums them under; reasoning_effort: how long an OpenAI reasoning model thinks before it answers
    (minimal, low, medium or high), the provider's default when None.

    Anthropic requests carry a top-level cache_control, which marks the request's last block, so
    the tools, the system prompt and the conversation so far are cached together: all of them
    repeat on every model call of a turn and every turn of a check. OpenAI caches long prefixes
    without being asked.
    """
    options: dict[str, Any] = {"api_key": api_key, "callbacks": [ModelCallLog(spec, kind)]}
    if spec.startswith("anthropic:"):
        options["model_kwargs"] = {"cache_control": {"type": "ephemeral"}}
        if reasoning_effort is not None:
            raise ValueError(
                f"{spec!r} takes no reasoning effort; leave LLM_FOLLOW_UP_EFFORT blank"
            )
    elif reasoning_effort is not None:
        options["reasoning_effort"] = reasoning_effort
    return init_chat_model(spec, **options)
