"""Fixtures of the API tests: a World per test, and a client of its app signed in as Dana."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from app_world import World
from fastapi.testclient import TestClient


@pytest.fixture
def world() -> World:
    return World()


@pytest.fixture
def client(world: World, public_key: Path) -> Iterator[TestClient]:
    """Dana, signed in."""
    with world.client(public_key) as entered:
        yield entered
