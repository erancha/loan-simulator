"""Checks how docker-compose.yml exposes the engine.

The agent will reach the engine over the Compose network. The one published port is for MCP
Inspector during development and binds to the loopback interface, since Docker otherwise
publishes on every host interface and exposes the port to the whole network.
"""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))


def test_the_engine_publishes_only_on_loopback() -> None:
    (mapping,) = COMPOSE["services"]["engine"]["ports"]
    assert re.fullmatch(
        r"127\.0\.0\.1:\$\{ENGINE_HOST_PORT[^}]*\}:\$\{ENGINE_PORT[^}]*\}", str(mapping)
    ), mapping


def test_no_other_service_publishes_a_port() -> None:
    others = {
        name: spec["ports"]
        for name, spec in COMPOSE["services"].items()
        if name != "engine" and "ports" in spec
    }
    assert not others, others


def test_the_market_data_volume_is_mounted_at_the_data_directory() -> None:
    assert COMPOSE["services"]["engine"]["volumes"] == ["engine-data:/data"]
    assert "engine-data" in COMPOSE["volumes"]


def test_the_image_builds_from_the_repo_root() -> None:
    build = COMPOSE["services"]["engine"]["build"]
    assert build == {"context": ".", "dockerfile": "mcp-server/Dockerfile"}
