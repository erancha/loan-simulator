"""The built page is served at / when configured, behind the API routes."""

from pathlib import Path

import pytest
from app_world import World
from fastapi.testclient import TestClient


def test_frontend_is_served_when_configured(tmp_path: Path, public_key: Path) -> None:
    (tmp_path / "index.html").write_text("<h1>page</h1>")
    with World().client(public_key, token=None, agent_frontend_dist=tmp_path) as client:
        assert client.get("/").text == "<h1>page</h1>"
        assert client.get("/api/auth/me").status_code == 401
        assert client.get("/health").json() == {"status": "ok"}


def test_missing_index_fails_startup(tmp_path: Path, public_key: Path) -> None:
    with pytest.raises(FileNotFoundError, match="AGENT_FRONTEND_DIST"):
        World().app(public_key, agent_frontend_dist=tmp_path)


def test_no_frontend_by_default(public_key: Path) -> None:
    with TestClient(World().app(public_key)) as client:
        assert client.get("/").status_code == 404
