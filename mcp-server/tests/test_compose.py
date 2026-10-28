"""Checks how docker-compose.yml runs the engine.

The agent reaches the engine over the Compose network. The engine's published port is for MCP
Inspector during development and binds to the loopback interface (the rationale is in the compose
file's header). The engine receives only its own .env keys, never the agent's secrets. The other
services' ports are checked by backend/tests/test_compose.py.
"""

import re
from pathlib import Path

import yaml

from loan_engine.service.config import Settings

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))


def test_the_engine_publishes_only_on_loopback() -> None:
    (mapping,) = COMPOSE["services"]["engine"]["ports"]
    assert re.fullmatch(
        r"127\.0\.0\.1:\$\{ENGINE_HOST_PORT[^}]*\}:\$\{ENGINE_PORT[^}]*\}", str(mapping)
    ), mapping


def test_the_market_data_volume_is_mounted_at_the_data_directory() -> None:
    assert COMPOSE["services"]["engine"]["volumes"] == ["engine-data:/data"]
    assert "engine-data" in COMPOSE["volumes"]


def test_the_image_builds_from_the_repo_root() -> None:
    build = COMPOSE["services"]["engine"]["build"]
    assert build == {"context": ".", "dockerfile": "mcp-server/Dockerfile"}


def test_the_engine_receives_only_its_own_keys_from_env() -> None:
    prefix = Settings.model_config["env_prefix"]
    environment = COMPOSE["services"]["engine"]["environment"]
    assert set(environment) == {f"{prefix}{name.upper()}" for name in Settings.model_fields}
    assert all(value is None for value in environment.values()), environment
    assert "env_file" not in COMPOSE["services"]["engine"]
