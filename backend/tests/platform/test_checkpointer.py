from decimal import Decimal

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.base import empty_checkpoint

from loan_agent.domain.models import Profile
from loan_agent.platform import checkpointer
from loan_agent.platform.checkpointer import checkpoint_serde, libpq_dsn, open_checkpointer


def test_libpq_dsn_drops_driver_suffix() -> None:
    assert libpq_dsn("postgresql+psycopg://u:p@h:5434/d") == "postgresql://u:p@h:5434/d"


async def test_checkpoint_serde_restores_messages_and_decimals_through_postgres(
    pg_url: str,
) -> None:
    messages = [HumanMessage("שלום"), AIMessage("מה ההכנסה?")]
    checkpoint = empty_checkpoint()
    checkpoint["channel_values"] = {"messages": messages, "price": Decimal("150000.00")}
    versions = {"messages": "1", "price": "1"}
    checkpoint["channel_versions"] = versions
    config = {"configurable": {"thread_id": "t-serde", "checkpoint_ns": ""}}
    async with open_checkpointer(libpq_dsn(pg_url)) as saver:
        stored = await saver.aput(
            config, checkpoint, {"source": "input", "step": 0, "parents": {}}, versions
        )
        restored = await saver.aget_tuple(stored)
    assert restored is not None
    values = restored.checkpoint["channel_values"]
    assert values["messages"] == messages
    assert values["price"] == Decimal("150000.00")


def test_checkpoint_serde_blocks_unlisted_domain_types() -> None:
    serde = checkpoint_serde()
    restored = serde.loads_typed(serde.dumps_typed(Profile(savings=Decimal(5))))
    assert not isinstance(restored, Profile)


def test_checkpoint_serde_restores_listed_domain_types(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(checkpointer, "CHECKPOINTED_TYPES", (Profile,))
    serde = checkpoint_serde()
    profile = Profile(savings=Decimal("5.50"))
    assert serde.loads_typed(serde.dumps_typed(profile)) == profile
