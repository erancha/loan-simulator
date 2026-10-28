"""The chat model is built from a provider:model spec, with Anthropic requests marked for
prompt caching."""

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from loan_agent.adapters.chat_model import build_chat_model

MESSAGES = [SystemMessage("הנחיות"), HumanMessage("שלום")]


def test_anthropic_requests_cache_the_prompt_prefix() -> None:
    model = build_chat_model("anthropic:claude-sonnet-5-5", "test-key")

    assert isinstance(model, ChatAnthropic)
    payload = model._get_request_payload(MESSAGES)
    assert payload["cache_control"] == {"type": "ephemeral"}
    assert payload["system"] == "הנחיות"


def test_openai_model_uses_the_key_and_no_cache_marker() -> None:
    model = build_chat_model("openai:gpt-5.4", "test-key")

    assert isinstance(model, ChatOpenAI)
    assert model.openai_api_key is not None
    assert model.openai_api_key.get_secret_value() == "test-key"
    assert "cache_control" not in model._get_request_payload(MESSAGES)
