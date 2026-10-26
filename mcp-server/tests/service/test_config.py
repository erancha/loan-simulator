from pathlib import Path

import pytest
from pydantic import ValidationError

from loan_engine.service.config import Settings

REQUIRED = ("ENGINE_BEARER_TOKEN", "ENGINE_ALLOWED_HOSTS", "ENGINE_PUBLIC_URL", "ENGINE_PORT")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (*REQUIRED, "ENGINE_DATA_DIR"):
        monkeypatch.delenv(name, raising=False)


def test_settings_require_token_hosts_url_and_port() -> None:
    with pytest.raises(ValidationError) as error:
        Settings()  # type: ignore[call-arg]
    missing = {e["loc"][0] for e in error.value.errors() if e["type"] == "missing"}
    assert missing == {"bearer_token", "allowed_hosts", "public_url", "port"}


def test_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENGINE_BEARER_TOKEN", "x" * 32)
    monkeypatch.setenv("ENGINE_ALLOWED_HOSTS", "engine:8020, localhost:8020")
    monkeypatch.setenv("ENGINE_PUBLIC_URL", "http://engine:8020")
    monkeypatch.setenv("ENGINE_PORT", "8020")
    settings = Settings()  # type: ignore[call-arg]
    assert settings.bearer_token.get_secret_value() == "x" * 32
    assert settings.allowed_hosts == ["engine:8020", "localhost:8020"]
    assert settings.public_url == "http://engine:8020"
    assert (settings.data_dir, settings.port) == (Path("/data"), 8020)


def test_short_token_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENGINE_BEARER_TOKEN", "x" * 31)
    monkeypatch.setenv("ENGINE_ALLOWED_HOSTS", "engine:8020")
    monkeypatch.setenv("ENGINE_PUBLIC_URL", "http://engine:8020")
    with pytest.raises(ValidationError, match="bearer_token"):
        Settings()  # type: ignore[call-arg]


def required_env(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> None:
    values = {
        "ENGINE_BEARER_TOKEN": "x" * 32,
        "ENGINE_ALLOWED_HOSTS": "engine:8020",
        "ENGINE_PUBLIC_URL": "http://engine:8020",
        "ENGINE_PORT": "8020",
        **overrides,
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)


@pytest.mark.parametrize("hosts", ["engine:8020,,localhost:8020", "engine:8020,", ""])
def test_empty_allowed_host_is_rejected(monkeypatch: pytest.MonkeyPatch, hosts: str) -> None:
    required_env(monkeypatch, ENGINE_ALLOWED_HOSTS=hosts)
    with pytest.raises(ValidationError, match="ENGINE_ALLOWED_HOSTS has an empty entry"):
        Settings()  # type: ignore[call-arg]


@pytest.mark.parametrize(
    ("url", "message"),
    [
        ("engine:8020", "must be an http"),
        ("ftp://engine", "must be an http"),
        ("http://", "must be an http"),
        ("http://engine:8020/", "must not end with '/'"),
    ],
)
def test_malformed_public_url_is_rejected(
    monkeypatch: pytest.MonkeyPatch, url: str, message: str
) -> None:
    required_env(monkeypatch, ENGINE_PUBLIC_URL=url)
    with pytest.raises(ValidationError, match=f"ENGINE_PUBLIC_URL {message}"):
        Settings()  # type: ignore[call-arg]
