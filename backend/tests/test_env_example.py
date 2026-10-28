"""Checks that .env.example documents exactly the keys the agent and its compose services read.

A key counts as documented when a line of the file assigns it, commented out or not
(KEY=value or # KEY=value). The one .env serves two services, so a key belongs to exactly one:
the engine owns the ENGINE_-prefixed keys (its own test checks them) except ENGINE_URL, which the
agent owns; the agent owns every other key, whether its Settings reads it or only
docker-compose.yml does. A copy of the file left unfilled must not start the agent, and
scripts/init-env.sh must fill in every agent key it owns, leaving only LLM_MODEL, LLM_API_KEY and
GOOGLE_CLIENT_ID for the person.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from loan_agent.platform.config import Settings

REPO = Path(__file__).resolve().parents[2]
ENV_EXAMPLE = REPO / ".env.example"
SCRIPTS = REPO / "scripts"

COMPOSE_ONLY_KEYS = {
    "AGENT_PORT",
    "AGENT_HOST_PORT",
    "DB_PORT",
    "DB_HOST_PORT",
    "POSTGRES_USER",
    "POSTGRES_DB",
    "POSTGRES_PASSWORD",
}
ENGINE_PREFIX = "ENGINE_"
AGENT_ENGINE_KEYS = {"ENGINE_URL"}

_ASSIGNMENT = re.compile(r"^(?:#\s*)?([A-Z][A-Z0-9_]*)=", re.MULTILINE)


def _owned_by_agent(key: str) -> bool:
    return not key.startswith(ENGINE_PREFIX) or key in AGENT_ENGINE_KEYS


def _documented_keys() -> set[str]:
    return set(_ASSIGNMENT.findall(ENV_EXAMPLE.read_text(encoding="utf-8")))


def _settings_keys() -> set[str]:
    return {name.upper() for name in Settings.model_fields if _owned_by_agent(name.upper())}


def _assignments(text: str) -> dict[str, str]:
    """The uncommented KEY=value lines of an env file."""
    lines = [line for line in text.splitlines() if _ASSIGNMENT.match(line) and line[0] != "#"]
    return dict(line.split("=", 1) for line in lines)


def test_every_settings_field_is_documented() -> None:
    missing = sorted(_settings_keys() - _documented_keys())
    assert not missing, f"Settings fields missing from .env.example: {missing}"


def test_every_compose_only_key_is_documented() -> None:
    assert COMPOSE_ONLY_KEYS <= _documented_keys()


def test_no_agent_key_is_unknown() -> None:
    unknown = sorted(
        key
        for key in _documented_keys() - _settings_keys() - COMPOSE_ONLY_KEYS
        if _owned_by_agent(key)
    )
    assert not unknown, f".env.example documents keys nothing reads: {unknown}"


def test_an_unfilled_copy_does_not_start(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in _assignments(ENV_EXAMPLE.read_text(encoding="utf-8")).items():
        monkeypatch.setenv(key, value)
    with pytest.raises(ValidationError) as error:
        Settings()  # type: ignore[call-arg]
    failed = {e["loc"][0] for e in error.value.errors()}
    assert failed == {
        "database_url",
        "llm_model",
        "llm_api_key",
        "google_client_id",
        "engine_url",
        "engine_bearer_token",
    }


def test_init_env_writes_the_agent_settings_it_owns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    for script in ("common.sh", "init-env.sh"):
        shutil.copy(SCRIPTS / script, root / "scripts" / script)
    shutil.copy(ENV_EXAMPLE, root / ".env.example")
    subprocess.run([str(root / "scripts" / "init-env.sh")], check=True, capture_output=True)
    env = _assignments((root / ".env").read_text(encoding="utf-8"))
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    # The keys init-env.sh leaves for the person to supply.
    for key, value in {
        "LLM_MODEL": "anthropic:claude-sonnet-5-5",
        "LLM_API_KEY": "sk-test",
        "GOOGLE_CLIENT_ID": "1-a.apps.googleusercontent.com",
    }.items():
        monkeypatch.setenv(key, value)
    settings = Settings()  # type: ignore[call-arg]
    password = env["POSTGRES_PASSWORD"]
    assert len(password) == 32
    assert settings.database_url.get_secret_value() == (
        f"postgresql+psycopg://{env['POSTGRES_USER']}:{password}"
        f"@127.0.0.1:{env['DB_HOST_PORT']}/{env['POSTGRES_DB']}"
    )
    assert settings.engine_url == f"http://localhost:{env['ENGINE_HOST_PORT']}/mcp"
