"""Server configuration read from ENGINE_-prefixed environment variables."""

from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ENGINE_")

    bearer_token: SecretStr = Field(min_length=32)
    allowed_hosts: Annotated[list[str], NoDecode] = Field(
        min_length=1, description="Host header values the server answers, e.g. engine:8020"
    )
    public_url: str = Field(
        description="Base URL callers reach the server at, without /mcp or a trailing slash"
    )
    data_dir: Path = Path("/data")
    port: int = Field(description="Port the engine listens on inside its container")

    @field_validator("allowed_hosts", mode="before")
    @classmethod
    def _split_hosts(cls, value: str | list[str]) -> list[str]:
        hosts = [host.strip() for host in value.split(",")] if isinstance(value, str) else value
        if "" in hosts:
            raise ValueError(f"ENGINE_ALLOWED_HOSTS has an empty entry: {value!r}")
        return hosts

    @field_validator("public_url")
    @classmethod
    def _check_public_url(cls, value: str) -> str:
        parts = urlsplit(value)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise ValueError(f"ENGINE_PUBLIC_URL must be an http(s) URL with a host: {value!r}")
        if value.endswith("/"):
            raise ValueError(f"ENGINE_PUBLIC_URL must not end with '/': {value!r}")
        return value
