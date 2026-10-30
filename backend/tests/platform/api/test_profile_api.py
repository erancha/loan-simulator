"""The person's profile over HTTP: read with what is missing, partially updated with money as
decimal strings, refused naming the field at fault, and an edit marks recommended checks stale."""

from datetime import timedelta
from decimal import Decimal

import pytest
from app_world import DANA, OMER, World, seed_recommended_check
from fastapi.testclient import TestClient

from fakes import NOW
from loan_agent.domain.models import Profile

ALL_FIELDS = [
    "savings",
    "net_fixed_income",
    "variable_income",
    "variable_income_minimum",
    "fixed_expenses",
    "existing_loan_payments",
]


def test_a_person_without_a_profile_is_missing_every_field(client: TestClient) -> None:
    response = client.get("/api/profile")
    assert response.status_code == 200
    assert response.json() == {
        "profile": dict.fromkeys(ALL_FIELDS),
        "missing": ALL_FIELDS,
    }


def test_put_updates_only_the_fields_sent(world: World, client: TestClient) -> None:
    world.profiles.rows[DANA.id] = (Profile(savings=Decimal(70000)), NOW)
    world.profiles.rows[OMER.id] = (Profile(savings=Decimal(1)), NOW)

    response = client.put(
        "/api/profile",
        json={"net_fixed_income": "14000.50", "variable_income_minimum": "500"},
    )

    assert response.status_code == 200
    expected = {
        "profile": {
            "net_fixed_income": "14000.50",
            "variable_income": None,
            "variable_income_minimum": "500",
            "fixed_expenses": None,
            "existing_loan_payments": None,
            "savings": "70000",
        },
        "missing": ["variable_income", "fixed_expenses", "existing_loan_payments"],
    }
    assert response.json() == expected
    assert client.get("/api/profile").json() == expected
    assert world.profiles.rows[OMER.id] == (Profile(savings=Decimal(1)), NOW)


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"savings": "-1"}, "savings"),
        ({"fixed_expenses": "abc"}, "fixed_expenses"),
        ({"net_fixed_income": None}, "net_fixed_income"),
        ({"net_fixed_income": 14000.5}, "net_fixed_income"),
        ({"variable_income_minimum": "-1"}, "variable_income_minimum"),
        ({"salary": "1"}, "salary"),
    ],
)
def test_an_invalid_field_is_422_naming_it(
    world: World, client: TestClient, body: dict[str, object], field: str
) -> None:
    response = client.put("/api/profile", json=body)
    assert response.status_code == 422
    assert field in str(response.json()["detail"])
    assert DANA.id not in world.profiles.rows


def test_a_profile_edit_makes_a_recommended_check_stale(world: World, client: TestClient) -> None:
    seed_recommended_check(world)
    assert client.get("/api/checks/c-rec").json()["profile_stale"] is False

    world.clock.value = NOW + timedelta(minutes=5)
    assert client.put("/api/profile", json={"savings": "60000"}).status_code == 200

    assert client.get("/api/checks/c-rec").json()["profile_stale"] is True
    assert [check["profile_stale"] for check in client.get("/api/checks").json()] == [True]


def test_saving_the_same_figures_keeps_a_recommended_check_fresh(
    world: World, client: TestClient
) -> None:
    seed_recommended_check(world)
    saved = client.get("/api/profile").json()["profile"]["savings"]

    world.clock.value = NOW + timedelta(minutes=5)
    assert client.put("/api/profile", json={"savings": saved}).status_code == 200

    assert client.get("/api/checks/c-rec").json()["profile_stale"] is False
