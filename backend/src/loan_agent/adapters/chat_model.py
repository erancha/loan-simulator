"""Builds the agent's chat model from a provider:model spec and an API key."""

from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel


def build_chat_model(spec: str, api_key: str) -> BaseChatModel:
    """spec: provider and model, e.g. anthropic:claude-sonnet-5-5 or openai:gpt-5.4.

    Anthropic requests carry a top-level cache_control, which marks the request's last block, so
    the tools, the system prompt and the conversation so far are cached together: all of them
    repeat on every model call of a turn and every turn of a check. OpenAI caches long prefixes
    without being asked.
    """
    options: dict[str, Any] = {"api_key": api_key}
    if spec.startswith("anthropic:"):
        options["model_kwargs"] = {"cache_control": {"type": "ephemeral"}}
    return init_chat_model(spec, **options)
