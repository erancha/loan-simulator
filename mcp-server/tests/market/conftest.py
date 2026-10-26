from collections.abc import Callable
from pathlib import Path

import httpx2
import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_text() -> Callable[[str], str]:
    return lambda name: (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture
def requests_seen() -> list[httpx2.Request]:
    return []


@pytest.fixture
def make_client(requests_seen: list[httpx2.Request]) -> Callable[..., httpx2.AsyncClient]:
    """A client answering each request with handler(request), recording the requests."""

    def build(handler: Callable[[httpx2.Request], httpx2.Response]) -> httpx2.AsyncClient:
        def record(request: httpx2.Request) -> httpx2.Response:
            requests_seen.append(request)
            return handler(request)

        return httpx2.AsyncClient(transport=httpx2.MockTransport(record))

    return build
