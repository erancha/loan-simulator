"""Process settings read from the environment and .env, validated at startup."""

from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from loan_agent.adapters.google_tokens import GOOGLE_ISSUER, GOOGLE_JWKS_URL

SUPPORTED_PROVIDERS = ("anthropic", "openai")


class Settings(BaseSettings):
    """A blank variable counts as unset, so a blank required key fails and a blank optional key
    keeps its default. The .env file is read from the working directory, so the agent started
    from the repo root reads the one .env it shares with the engine; the engine's own keys are
    ignored here."""

    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", frozen=True, env_ignore_empty=True
    )

    database_url: SecretStr
    """SQLAlchemy form: postgresql+psycopg://user:password@host:port/database."""
    llm_model: str
    """provider:model, for a provider in SUPPORTED_PROVIDERS."""
    llm_api_key: SecretStr
    google_client_id: str
    """The OAuth client of the page's Sign in with Google button; the audience every token must
    name."""
    auth_issuer: str = GOOGLE_ISSUER
    auth_jwks_url: str = GOOGLE_JWKS_URL
    auth_public_key_file: Path | None = None
    """Test only: a PEM public key that verifies tokens instead of the issuer's published keys,
    so a test signs its own tokens and never reaches Google."""
    engine_url: str
    """The engine's MCP endpoint, path included (e.g. http://engine:8020/mcp)."""
    engine_bearer_token: SecretStr
    """The engine's own ENGINE_BEARER_TOKEN, presented on every engine call."""
    agent_turn_limit: int = Field(default=50, gt=0)
    """Messages a person may send, across all their checks, in any rolling window of
    agent_turn_window_hours."""
    agent_turn_window_hours: int = Field(default=24, gt=0)
    agent_log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "WARNING"

    @model_validator(mode="after")
    def _require_supported_model(self) -> Self:
        provider, separator, model = self.llm_model.partition(":")
        if not separator or not model:
            raise ValueError(f"LLM_MODEL={self.llm_model!r} must be provider:model")
        if provider not in SUPPORTED_PROVIDERS:
            raise ValueError(
                f"LLM_MODEL provider {provider!r} is not one of {', '.join(SUPPORTED_PROVIDERS)}"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    # Required fields come from the environment, which mypy cannot see.
    return Settings()  # type: ignore[call-arg]
