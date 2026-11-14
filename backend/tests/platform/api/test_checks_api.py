"""Checks over HTTP: a person creates, lists and reads only their own checks, sends messages
within the turn rules, and their ID token never reaches a checkpoint. Startup ends the turns a
stopped process left running; the health probe answers while the process runs and the readiness
probe needs the database."""

import asyncio
import threading
from collections.abc import Iterator
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from app_world import DANA, DANA_TOKEN, OMER, OMER_TOKEN, World, seed_recommended_check
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.checkpoint.memory import InMemorySaver

from fakes import NOW, PRIME_TRACK
from loan_agent.domain.models import Check, OptionSource
from loan_agent.platform.check_runner import FAILURE_MESSAGE

TIMEOUT_SECONDS = 5.0


def test_create_answers_201_with_a_new_check_of_the_signed_in_person(
    world: World, client: TestClient
) -> None:
    response = client.post("/api/checks")
    assert response.status_code == 201
    check_id = response.json()["id"]
    assert response.json() == {"id": check_id}
    assert world.checks.rows[check_id] == Check(check_id, DANA.id, NOW, None, None)


def test_list_shows_only_the_persons_checks_newest_first(world: World, client: TestClient) -> None:
    seed_recommended_check(world)
    world.checks.rows["c-new"] = Check("c-new", DANA.id, NOW + timedelta(days=1), None, None)
    world.checks.rows["c-omer"] = Check("c-omer", OMER.id, NOW, None, None)

    response = client.get("/api/checks")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": "c-new",
            "created_at": "2026-10-28T09:00:00Z",
            "goal": None,
            "recommendation": None,
            "recommends_examples_only": False,
            "profile_stale": False,
            "archived": False,
            "restorable": False,
        },
        {
            "id": "c-rec",
            "created_at": "2026-10-27T09:00:00Z",
            "goal": {"purpose": "רכב משפחתי", "price": "120000"},
            "recommendation": {
                "preferred_option_id": "o1",
                "alternative_option_id": None,
                "loan_amount": "80000.00",
                "payment_ceiling": "4700.00",
                "created_at": "2026-10-27T09:00:00Z",
            },
            "recommends_examples_only": False,
            "profile_stale": False,
            "archived": False,
            "restorable": False,
        },
    ]


@pytest.mark.parametrize(
    ("first", "second", "alternative", "examples_only"),
    [
        ("published_average", "published_average", None, True),
        ("published_average", "published_average", "o2", True),
        ("offer", "published_average", "o2", False),
        ("published_average", "offer", "o2", False),
        ("published_average", "offer", None, True),
        ("offer", "published_average", None, False),
    ],
)
def test_list_says_whether_the_recommendation_names_only_examples(
    world: World,
    client: TestClient,
    first: OptionSource,
    second: OptionSource,
    alternative: str | None,
    examples_only: bool,
) -> None:
    seed_recommended_check(world)
    seeded = world.options.rows["c-rec"][0]
    world.options.rows["c-rec"] = [
        replace(seeded, source=first),
        replace(seeded, id="o2", source=second),
    ]
    world.recommendations.rows["c-rec"] = replace(
        world.recommendations.rows["c-rec"], alternative_option_id=alternative
    )

    [listed] = client.get("/api/checks").json()

    assert listed["recommends_examples_only"] is examples_only


def test_get_shows_the_goal_options_with_figures_and_the_recommendation(
    world: World, client: TestClient
) -> None:
    seed_recommended_check(world)

    response = client.get("/api/checks/c-rec")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "c-rec"
    assert body["goal"] == {"purpose": "רכב משפחתי", "price": "120000"}
    assert body["options"] == [
        {
            "id": "o1",
            "source": "offer",
            "lender": "בנק הפועלים",
            "offer_date": "2026-10-27",
            "loan": {"tracks": [PRIME_TRACK]},
            "figures": {
                "first_payment": "1887.99",
                "peak_payment": "1887.99",
                "worst_peak_payment": "2038.63",
                "worst_start": "2022-04-01",
                "worst_end": "2026-03-01",
                "balloon_due": None,
                "total_paid": "90623.31",
                "rate_as_of": "2026-10-26",
                "cpi_as_of": "2026-09-01",
            },
            "created_at": "2026-10-27T09:00:00Z",
        }
    ]
    assert body["recommendation"] == {
        "preferred_option_id": "o1",
        "alternative_option_id": None,
        "reasoning": "ההחזר החודשי נמוך מהתקרה",
        "loan_amount": "80000.00",
        "payment_ceiling": "4700.00",
        "min_cushion": "18000.00",
        "cushion_kept": "30000.00",
        "created_at": "2026-10-27T09:00:00Z",
    }
    assert body["profile_stale"] is False
    assert body["archived"] is False


def test_a_new_check_has_no_goal_options_or_recommendation(client: TestClient) -> None:
    check_id = client.post("/api/checks").json()["id"]
    body = client.get(f"/api/checks/{check_id}").json()
    assert body["goal"] is None
    assert body["options"] == []
    assert body["recommendation"] is None
    assert body["profile_stale"] is False
    assert body["archived"] is False


def test_another_persons_check_is_404_like_an_unknown_one(world: World, public_key: Path) -> None:
    with world.client(public_key, token=OMER_TOKEN) as omer:
        omers = omer.post("/api/checks").json()["id"]
    with world.client(public_key, token=DANA_TOKEN) as dana:
        for check_id in (omers, "no-such-check"):
            assert dana.get(f"/api/checks/{check_id}").status_code == 404
            sent = dana.post(f"/api/checks/{check_id}/messages", json={"text": "שלום"})
            assert sent.status_code == 404
            assert dana.get(f"/api/checks/{check_id}/events").status_code == 404
    assert world.events.rows == {}


def test_a_message_is_accepted_with_202_and_runs_a_turn(world: World, client: TestClient) -> None:
    world.replies(AIMessage("שלום, מה ההכנסה החודשית שלך?"))
    check_id = client.post("/api/checks").json()["id"]

    response = client.post(f"/api/checks/{check_id}/messages", json={"text": "אני רוצה רכב"})
    world.drain(client)

    assert response.status_code == 202
    assert [event.type for event in world.events.rows[check_id]] == [
        "message.user",
        "turn.status",
        "message.assistant",
        "turn.status",
    ]


def test_an_empty_message_is_422(client: TestClient) -> None:
    check_id = client.post("/api/checks").json()["id"]
    for text in ("", "   "):
        response = client.post(f"/api/checks/{check_id}/messages", json={"text": text})
        assert response.status_code == 422


class Gate:
    """An engine tool that waits until opened, so a turn stays running."""

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.opened = threading.Event()

    def tool(self) -> BaseTool:
        async def size_loan(goal_price: str) -> str:
            self.entered.set()
            await asyncio.to_thread(self.opened.wait, TIMEOUT_SECONDS)
            return "loan_amount: 80000"

        return StructuredTool.from_function(
            coroutine=size_loan, name="size_loan", description="Size the loan"
        )


@pytest.fixture
def gate(world: World) -> Iterator[Gate]:
    opened = Gate()
    world.engine_tools.append(opened.tool())
    yield opened
    opened.opened.set()


def calls_size_loan() -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {"name": "size_loan", "args": {"goal_price": "1"}, "id": "call-1", "type": "tool_call"}
        ],
    )


def test_a_message_while_a_turn_runs_is_409_naming_the_check(
    world: World, gate: Gate, client: TestClient
) -> None:
    """gate comes before client, so the app is built with the gated tool."""
    world.replies(calls_size_loan(), AIMessage("הלוואה של 80,000"), AIMessage("בבקשה"))
    check_id = client.post("/api/checks").json()["id"]
    assert client.post(f"/api/checks/{check_id}/messages", json={"text": "א"}).status_code == 202
    assert gate.entered.wait(TIMEOUT_SECONDS)

    response = client.post(f"/api/checks/{check_id}/messages", json={"text": "ב"})

    assert response.status_code == 409
    assert response.json() == {
        "detail": f"check {check_id!r} is still answering",
        "check_id": check_id,
    }
    gate.opened.set()
    world.drain(client)
    assert client.post(f"/api/checks/{check_id}/messages", json={"text": "ג"}).status_code == 202


def test_delete_answers_204_and_removes_the_check_and_its_conversation(
    world: World, client: TestClient
) -> None:
    world.replies(AIMessage("שלום"))
    check_id = client.post("/api/checks").json()["id"]
    assert client.post(f"/api/checks/{check_id}/messages", json={"text": "א"}).status_code == 202
    world.drain(client)
    assert check_id in world.saver.storage

    assert client.delete(f"/api/checks/{check_id}").status_code == 204

    assert client.get(f"/api/checks/{check_id}").status_code == 404
    assert client.get("/api/checks").json() == []
    assert check_id not in world.saver.storage
    assert client.delete(f"/api/checks/{check_id}").status_code == 404


def test_delete_of_another_persons_check_is_404_and_keeps_it(
    world: World, public_key: Path
) -> None:
    with world.client(public_key, token=OMER_TOKEN) as omer:
        omers = omer.post("/api/checks").json()["id"]
    with world.client(public_key, token=DANA_TOKEN) as dana:
        assert dana.delete(f"/api/checks/{omers}").status_code == 404
    assert omers in world.checks.rows


def test_delete_while_a_turn_runs_is_409_and_keeps_the_check(
    world: World, gate: Gate, client: TestClient
) -> None:
    """gate comes before client, so the app is built with the gated tool."""
    world.replies(calls_size_loan(), AIMessage("בבקשה"))
    check_id = client.post("/api/checks").json()["id"]
    assert client.post(f"/api/checks/{check_id}/messages", json={"text": "א"}).status_code == 202
    assert gate.entered.wait(TIMEOUT_SECONDS)

    response = client.delete(f"/api/checks/{check_id}")

    assert response.status_code == 409
    assert response.json()["check_id"] == check_id
    gate.opened.set()
    world.drain(client)
    assert client.delete(f"/api/checks/{check_id}").status_code == 204


def test_a_message_over_the_cap_is_429_with_retry_after_rounded_up(
    world: World, public_key: Path
) -> None:
    world.replies(AIMessage("שלום"))
    with world.client(public_key, agent_turn_limit=1, agent_turn_window_hours=24) as client:
        check_id = client.post("/api/checks").json()["id"]
        first = client.post(f"/api/checks/{check_id}/messages", json={"text": "א"})
        assert first.status_code == 202
        world.drain(client)
        world.clock.value = NOW + timedelta(seconds=30, microseconds=500_000)

        response = client.post(f"/api/checks/{check_id}/messages", json={"text": "ב"})

    assert response.status_code == 429
    assert response.headers["Retry-After"] == str(24 * 3600 - 30)
    body = response.json()
    assert datetime.fromisoformat(body["next_allowed"]) == NOW + timedelta(hours=24)
    assert "limit of 1" in body["detail"]


def stored_bytes(saver: InMemorySaver) -> list[bytes]:
    """Every serialized value the saver holds: each checkpoint and its metadata, the values nodes
    wrote since the last checkpoint, and the state values the checkpoints point at."""
    found: list[bytes] = []

    def walk(value: Any) -> None:
        if isinstance(value, bytes):
            found.append(value)
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, tuple | list):
            for item in value:
                walk(item)

    walk(saver.storage)
    walk(saver.writes)
    walk(saver.blobs)
    return found


def test_no_checkpoint_blob_holds_the_id_token(world: World, client: TestClient) -> None:
    world.replies(
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "update_profile",
                    "args": {"savings": "70000"},
                    "id": "call-profile",
                    "type": "tool_call",
                }
            ],
        ),
        AIMessage("שמרתי את החסכונות"),
    )
    check_id = client.post("/api/checks").json()["id"]
    sent = client.post(f"/api/checks/{check_id}/messages", json={"text": "יש לי 70,000 ₪"})
    assert sent.status_code == 202
    world.drain(client)

    blobs = stored_bytes(world.saver)
    assert [event.type for event in world.events.rows[check_id]][-2:] == [
        "message.assistant",
        "turn.status",
    ]
    assert not [blob for blob in blobs if DANA_TOKEN.encode() in blob]
    assert [blob for blob in blobs if DANA.id.encode() in blob], "the scan sees the person"
    assert [blob for blob in blobs if b"70,000" in blob], "the scan sees the turn"


def test_startup_ends_turns_a_stopped_process_left_running(world: World, public_key: Path) -> None:
    world.checks.rows["c1"] = Check("c1", DANA.id, NOW, None, None)
    asyncio.run(world.events.append("c1", "message.user", {"text": "שלום"}))
    asyncio.run(world.events.append("c1", "turn.status", {"status": "running"}))

    with world.client(public_key):
        pass

    assert [(event.type, event.data) for event in world.events.rows["c1"]][2:] == [
        ("turn.failed", {"message": FAILURE_MESSAGE}),
        ("turn.status", {"status": "idle"}),
    ]


def test_health_answers_while_the_process_runs(world: World, client: TestClient) -> None:
    world.database_error = ConnectionError("database down")
    assert client.get("/health").json() == {"status": "ok"}


def test_ready_needs_the_database(world: World, client: TestClient) -> None:
    assert client.get("/ready").json() == {"status": "ok"}
    world.database_error = ConnectionError("database down")
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "not ready"}


def test_clone_answers_201_with_a_copy_of_the_check_and_its_conversation(
    world: World, client: TestClient
) -> None:
    seed_recommended_check(world)
    world.replies(AIMessage("שלום"))
    assert client.post("/api/checks/c-rec/messages", json={"text": "א"}).status_code == 202
    world.drain(client)

    response = client.post("/api/checks/c-rec/clone")

    assert response.status_code == 201
    clone_id = response.json()["id"]
    original = client.get("/api/checks/c-rec").json()
    clone = client.get(f"/api/checks/{clone_id}").json()
    assert {**clone, "id": "c-rec"} == original
    assert clone_id in world.saver.storage
    assert client.post("/api/checks/no-such-check/clone").status_code == 404


def test_a_message_to_an_archived_check_is_409(world: World, client: TestClient) -> None:
    seed_recommended_check(world)
    world.checks.rows["c-rec"] = replace(world.checks.rows["c-rec"], archived_at=NOW)

    response = client.post("/api/checks/c-rec/messages", json={"text": "א"})

    assert response.status_code == 409
    assert client.get("/api/checks/c-rec").json()["archived"] is True


def test_archive_and_restore_answer_204_and_the_list_says_what_can_be_restored(
    world: World, client: TestClient
) -> None:
    seed_recommended_check(world)

    assert client.post("/api/checks/c-rec/archive").status_code == 204
    (listed,) = client.get("/api/checks").json()
    assert (listed["archived"], listed["restorable"]) == (True, True)
    assert client.post("/api/checks/c-rec/archive").status_code == 409

    assert client.post("/api/checks/c-rec/restore").status_code == 204
    (listed,) = client.get("/api/checks").json()
    assert (listed["archived"], listed["restorable"]) == (False, False)
    assert client.post("/api/checks/c-rec/restore").status_code == 409


def test_a_check_archived_by_a_profile_edit_is_not_restorable(
    world: World, client: TestClient
) -> None:
    seed_recommended_check(world)
    world.clock.value = NOW + timedelta(minutes=5)
    assert client.put("/api/profile", json={"savings": "60000"}).status_code == 200

    (listed,) = client.get("/api/checks").json()
    assert (listed["archived"], listed["restorable"]) == (True, False)
    assert client.post("/api/checks/c-rec/restore").status_code == 409
