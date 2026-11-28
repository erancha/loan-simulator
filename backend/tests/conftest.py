"""Fixtures every backend test shares: settings read from the test's environment alone, the test
key pair's public half as a file, and a Postgres container migrated to head, one per module."""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from testcontainers.community.postgres import PostgresContainer

from auth_keys import PUBLIC_PEM
from loan_agent.platform.config import Settings
from loan_agent.platform.logging import configure_logging

BACKEND_DIR = Path(__file__).resolve().parents[1]

# The app's own log setup, so a test that logs a failure renders a plain traceback rather than
# structlog's default rich one, which takes seconds per exception.
configure_logging("WARNING")


@pytest.fixture(autouse=True)
def no_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings read only the test's environment, never a developer's settings files."""
    monkeypatch.setitem(Settings.model_config, "env_file", None)


@pytest.fixture(scope="session")
def public_key(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The test key pair's public half, where AUTH_PUBLIC_KEY_FILE points."""
    pem = tmp_path_factory.mktemp("auth") / "public.pem"
    pem.write_bytes(PUBLIC_PEM)
    return pem


@pytest.fixture(scope="module")
def pg_url() -> Iterator[str]:
    with PostgresContainer("postgres:16", driver="psycopg") as container:
        url = container.get_connection_url()
        previous = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = url
        try:
            config = Config(str(BACKEND_DIR / "alembic.ini"))
            config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
            command.upgrade(config, "head")
        finally:
            if previous is None:
                del os.environ["DATABASE_URL"]
            else:
                os.environ["DATABASE_URL"] = previous
        yield url
