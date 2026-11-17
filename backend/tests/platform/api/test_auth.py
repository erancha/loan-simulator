"""Sign-in: the posted Google credential becomes a cookie that lasts as long as the token,
protected routes need it, and signing out drops it."""

import time
from http.cookies import SimpleCookie
from pathlib import Path

import httpx
import pytest
from app_world import DANA, DANA_TOKEN, World
from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth_keys import CLIENT_ID, OTHER_KEY, sign
from loan_agent.adapters.google_tokens import CLOCK_SKEW
from loan_agent.platform.api.auth import COOKIE

# Every other route of the app needs a signed-in person.
PUBLIC = {
    ("GET", "/api/auth/config"),
    ("POST", "/api/auth/session"),
    ("DELETE", "/api/auth/session"),
    ("GET", "/health"),
    ("GET", "/ready"),
}


def protected_routes(app: FastAPI) -> list[tuple[str, str]]:
    """Each method and path the app's OpenAPI schema lists outside PUBLIC, with a check id and an
    awaiting offer id filled in."""
    routes = sorted(
        (method.upper(), path.replace("{check_id}", "c1").replace("{awaiting_id}", "a1"))
        for path, operations in app.openapi()["paths"].items()
        for method in operations
        if (method.upper(), path) not in PUBLIC
    )
    unfilled = [path for _, path in routes if "{" in path]
    assert not unfilled, f"fill in these path parameters: {unfilled}"
    return routes


def set_cookie(response: httpx.Response) -> SimpleCookie:
    jar = SimpleCookie()
    jar.load(response.headers["set-cookie"])
    return jar


def test_the_client_id_is_public(world: World, public_key: Path) -> None:
    with world.client(public_key, token=None) as client:
        assert client.get("/api/auth/config").json() == {"clientId": CLIENT_ID}


def test_sign_in_sets_a_cookie_that_lasts_as_long_as_the_token(
    world: World, public_key: Path
) -> None:
    token = sign(exp=int(time.time()) + 50 * 60)
    with world.client(public_key, token=None) as client:
        response = client.post("/api/auth/session", json={"credential": token})
        assert response.status_code == 200
        assert response.json() == {"id": DANA.id, "email": DANA.email, "name": DANA.name}
        cookie = set_cookie(response)[COOKIE]
        assert cookie.value == token
        assert cookie["httponly"]
        assert cookie["samesite"].lower() == "strict"
        assert cookie["path"] == "/"
        assert not cookie["secure"], "the test client speaks plain http"
        assert 49 * 60 < int(cookie["max-age"]) <= 50 * 60

        assert client.get("/api/auth/me").json()["id"] == DANA.id
        assert client.get("/api/checks").status_code == 200


def test_the_cookie_is_secure_over_https(world: World, public_key: Path) -> None:
    with TestClient(world.app(public_key), base_url="https://agent.test") as client:
        response = client.post("/api/auth/session", json={"credential": DANA_TOKEN})
        assert set_cookie(response)[COOKIE]["secure"]


def test_the_cookie_is_secure_behind_https_that_ends_before_the_agent(
    world: World, public_key: Path
) -> None:
    app = world.app(public_key, agent_https_only=True)
    with TestClient(app, base_url="http://agent.test") as client:
        response = client.post("/api/auth/session", json={"credential": DANA_TOKEN})
        assert set_cookie(response)[COOKIE]["secure"]


@pytest.mark.parametrize(
    ("credential", "reason"),
    [
        (sign(exp=int(time.time()) - 2 * int(CLOCK_SKEW.total_seconds())), "expired"),
        (sign(aud="other-client"), "another application"),
        (sign(key=OTHER_KEY), "not valid"),
        ("forged", "not valid"),
    ],
)
def test_a_bad_credential_is_401_with_the_reason_and_sets_no_cookie(
    world: World, public_key: Path, credential: str, reason: str
) -> None:
    with world.client(public_key, token=None) as client:
        response = client.post("/api/auth/session", json={"credential": credential})
        assert response.status_code == 401
        assert response.headers["WWW-Authenticate"] == "Bearer"
        assert reason in response.json()["detail"]
        assert "set-cookie" not in response.headers


def test_protected_routes_are_401_without_a_cookie(world: World, public_key: Path) -> None:
    with world.client(public_key, token=None) as client:
        assert isinstance(client.app, FastAPI)
        protected = protected_routes(client.app)
        assert ("GET", "/api/checks/c1/events") in protected
        for method, path in protected:
            response = client.request(method, path)
            assert response.status_code == 401, path
            assert response.json() == {"detail": "sign in to continue"}
            assert response.headers["WWW-Authenticate"] == "Bearer"
        assert client.get("/health").status_code == 200


@pytest.mark.parametrize(
    ("token", "reason"),
    [
        (sign(exp=int(time.time()) - 2 * int(CLOCK_SKEW.total_seconds())), "expired"),
        (sign(aud="other-client"), "another application"),
    ],
)
def test_protected_routes_are_401_with_a_bad_cookie(
    world: World, public_key: Path, token: str, reason: str
) -> None:
    with world.client(public_key, token=token) as client:
        response = client.get("/api/checks")
        assert response.status_code == 401
        assert response.headers["WWW-Authenticate"] == "Bearer"
        assert reason in response.json()["detail"]


def test_sign_out_drops_the_cookie(world: World, public_key: Path) -> None:
    with world.client(public_key, token=None) as client:
        client.post("/api/auth/session", json={"credential": DANA_TOKEN})
        response = client.delete("/api/auth/session")
        assert response.status_code == 204
        assert set_cookie(response)[COOKIE]["max-age"] == "0"
        assert client.get("/api/auth/me").status_code == 401
