"""Checks how docker-compose.yml wires the agent, its database and the migration.

Every published port binds to the loopback interface through its .env variable (the rationale is
in the compose file's header). The agent starts only on a migrated database and an engine that
accepts connections, and learns the in-network addresses of both from compose rather than from
the host-form values in .env. The agent and the migration receive only the .env keys they read;
the engine's keys are checked by mcp-server/tests/test_compose.py.
"""

import re
from pathlib import Path

import yaml

from loan_agent.platform.config import Settings

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
SERVICES = COMPOSE["services"]
# Read by the image's command rather than by Settings: the port it serves on.
AGENT_IMAGE_KEYS = {"AGENT_PORT"}


def test_every_published_port_binds_to_loopback_through_variables() -> None:
    published = {name: spec["ports"] for name, spec in SERVICES.items() if "ports" in spec}
    assert set(published) == {"engine", "db", "agent"}
    for name, (mapping,) in published.items():
        assert re.fullmatch(r"127\.0\.0\.1:\$\{\w+_HOST_PORT:\?[^}]*\}:.+", str(mapping)), (
            name,
            mapping,
        )


def test_the_agent_and_database_publish_on_their_own_variables() -> None:
    assert SERVICES["agent"]["ports"] == [
        "127.0.0.1:${AGENT_HOST_PORT:?set in .env}:${AGENT_PORT:?set in .env}"
    ]
    assert SERVICES["db"]["ports"] == [
        "127.0.0.1:${DB_HOST_PORT:?set in .env}:${DB_PORT:?set in .env}"
    ]


def test_the_agent_waits_for_the_database_the_migration_and_the_engine() -> None:
    assert SERVICES["agent"]["depends_on"] == {
        "db": {"condition": "service_healthy"},
        "migrate": {"condition": "service_completed_successfully"},
        "engine": {"condition": "service_healthy"},
    }


def test_the_migration_runs_once_from_the_agent_image_after_the_database() -> None:
    migrate = SERVICES["migrate"]
    assert migrate["command"] == "alembic upgrade head"
    assert migrate["image"] == SERVICES["agent"]["image"]
    assert migrate["depends_on"] == {"db": {"condition": "service_healthy"}}
    assert "restart" not in migrate


def test_the_database_keeps_its_data_in_a_named_volume_and_reports_health() -> None:
    db = SERVICES["db"]
    assert db["image"] == "postgres:16"
    (volume,) = db["volumes"]
    assert volume.split(":")[0] in COMPOSE["volumes"]
    assert "pg_isready" in str(db["healthcheck"]["test"])


def test_the_engine_is_healthy_once_it_accepts_connections() -> None:
    check = str(SERVICES["engine"]["healthcheck"]["test"])
    assert "socket" in check and "${ENGINE_PORT" in check


def test_the_database_user_and_name_come_from_env_in_every_use() -> None:
    values = yaml.dump({**COMPOSE, "name": None, "x-agent-image": None})
    assert "loan" not in values.replace("loan-agent", "")


def test_the_agent_reports_health_on_its_probe() -> None:
    assert "/health" in str(SERVICES["agent"]["healthcheck"]["test"])


def test_the_network_addresses_override_the_host_forms_in_env() -> None:
    for name in ("agent", "migrate"):
        environment = SERVICES[name]["environment"]
        assert "@db:${DB_PORT" in environment["DATABASE_URL"], name
    assert SERVICES["agent"]["environment"]["ENGINE_URL"].startswith("http://engine:")


def test_each_container_receives_only_the_keys_it_reads() -> None:
    assert not [name for name, spec in SERVICES.items() if "env_file" in spec]
    agent_keys = {name.upper() for name in Settings.model_fields} | AGENT_IMAGE_KEYS
    assert set(SERVICES["agent"]["environment"]) == agent_keys
    assert set(SERVICES["migrate"]["environment"]) == {"DATABASE_URL"}


def test_the_bearer_token_is_defined_once() -> None:
    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert text.count("ENGINE_BEARER_TOKEN") == 1
    for name in ("engine", "agent"):
        assert SERVICES[name]["environment"]["ENGINE_BEARER_TOKEN"] is None, name
