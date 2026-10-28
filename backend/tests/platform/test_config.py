"""Settings come from the environment, require every key without a default, and refuse values the
agent cannot run with."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from loan_agent.platform.config import Settings

REQUIRED = {
    "DATABASE_URL": "postgresql+psycopg://u:p@h:8102/d",
    "LLM_MODEL": "anthropic:claude-sonnet-5-5",
    "LLM_API_KEY": "sk-test",
    "GOOGLE_CLIENT_ID": "123-abc.apps.googleusercontent.com",
    "ENGINE_URL": "http://engine:8020/mcp",
    "ENGINE_BEARER_TOKEN": "0123456789abcdef" * 3,
}
OPTIONAL = (
    "AUTH_ISSUER",
    "AUTH_JWKS_URL",
    "AUTH_PUBLIC_KEY_FILE",
    "AGENT_TURN_LIMIT",
    "AGENT_TURN_WINDOW_HOURS",
    "AGENT_LOG_LEVEL",
)


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for key in OPTIONAL:
        monkeypatch.delenv(key, raising=False)
    for key, value in REQUIRED.items():
        monkeypatch.setenv(key, value)
    return monkeypatch


def test_defaults_apply_to_the_optional_keys(env: pytest.MonkeyPatch) -> None:
    settings = Settings()
    assert settings.agent_turn_limit == 50
    assert settings.agent_turn_window_hours == 24
    assert settings.agent_log_level == "WARNING"
    assert settings.auth_issuer == "https://accounts.google.com"
    assert settings.auth_jwks_url == "https://www.googleapis.com/oauth2/v3/certs"
    assert settings.auth_public_key_file is None
    assert settings.llm_model == "anthropic:claude-sonnet-5-5"
    assert settings.engine_url == "http://engine:8020/mcp"


def test_secrets_stay_out_of_the_repr(env: pytest.MonkeyPatch) -> None:
    settings = Settings()
    for key in ("DATABASE_URL", "LLM_API_KEY", "ENGINE_BEARER_TOKEN"):
        assert REQUIRED[key] not in repr(settings)
    assert settings.llm_api_key.get_secret_value() == "sk-test"
    assert settings.engine_bearer_token.get_secret_value() == REQUIRED["ENGINE_BEARER_TOKEN"]
    assert settings.database_url.get_secret_value() == REQUIRED["DATABASE_URL"]


@pytest.mark.parametrize("key", sorted(REQUIRED))
def test_every_required_key_is_required(env: pytest.MonkeyPatch, key: str) -> None:
    env.delenv(key)
    with pytest.raises(ValidationError, match=key.lower()):
        Settings()


@pytest.mark.parametrize("key", sorted(REQUIRED))
def test_a_blank_required_key_counts_as_missing(env: pytest.MonkeyPatch, key: str) -> None:
    env.setenv(key, "")
    with pytest.raises(ValidationError, match=key.lower()):
        Settings()


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        ("claude-sonnet-5-5", "provider:model"),
        ("anthropic:", "provider:model"),
        ("gemini:pro", "gemini"),
    ],
)
def test_the_model_names_a_supported_provider(
    env: pytest.MonkeyPatch, value: str, reason: str
) -> None:
    env.setenv("LLM_MODEL", value)
    with pytest.raises(ValidationError, match=reason):
        Settings()


def test_openai_is_a_supported_provider(env: pytest.MonkeyPatch) -> None:
    env.setenv("LLM_MODEL", "openai:gpt-5.4")
    assert Settings().llm_model == "openai:gpt-5.4"


@pytest.mark.parametrize("key", ["AGENT_TURN_LIMIT", "AGENT_TURN_WINDOW_HOURS"])
@pytest.mark.parametrize("value", ["0", "-1"])
def test_the_turn_cap_is_positive(env: pytest.MonkeyPatch, key: str, value: str) -> None:
    env.setenv(key, value)
    with pytest.raises(ValidationError, match=key.lower()):
        Settings()


def test_the_turn_cap_is_configurable(env: pytest.MonkeyPatch) -> None:
    env.setenv("AGENT_TURN_LIMIT", "7")
    env.setenv("AGENT_TURN_WINDOW_HOURS", "12")
    settings = Settings()
    assert (settings.agent_turn_limit, settings.agent_turn_window_hours) == (7, 12)


def test_an_unknown_log_level_is_refused(env: pytest.MonkeyPatch) -> None:
    env.setenv("AGENT_LOG_LEVEL", "LOUD")
    with pytest.raises(ValidationError, match="agent_log_level"):
        Settings()


def test_the_engine_keys_of_the_shared_env_file_are_ignored(env: pytest.MonkeyPatch) -> None:
    env.setenv("ENGINE_PORT", "8020")
    env.setenv("ENGINE_ALLOWED_HOSTS", "engine:8020")
    assert not hasattr(Settings(), "engine_port")


def test_a_test_issuer_and_key_file_replace_google(env: pytest.MonkeyPatch) -> None:
    env.setenv("AUTH_ISSUER", "loan-e2e")
    env.setenv("AUTH_PUBLIC_KEY_FILE", "/e2e/public.pem")
    settings = Settings()
    assert settings.auth_issuer == "loan-e2e"
    assert settings.auth_public_key_file == Path("/e2e/public.pem")


def test_the_env_file_is_read_from_the_working_directory(
    env: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """One .env at the repo root serves the engine and the agent; scripts run from there."""
    env.delenv("LLM_MODEL")
    (tmp_path / ".env").write_text("LLM_MODEL=openai:gpt-5.4\nENGINE_PORT=8020\n")
    env.chdir(tmp_path)
    env.setitem(Settings.model_config, "env_file", ".env")
    assert Settings().llm_model == "openai:gpt-5.4"
