from __future__ import annotations

from typing import TypedDict

import pytest
from langgraph.graph import END, START, StateGraph

from ledger.checkpoints import (
    CheckpointerConfigurationError,
    CheckpointerFactory,
    checkpoint_config,
    postgres_connection_string,
    sqlite_connection_string,
)


class CounterState(TypedDict):
    count: int


def counter_graph(checkpointer):
    async def increment(state: CounterState) -> CounterState:
        return {"count": state["count"] + 1}

    builder = StateGraph(CounterState)
    builder.add_node("increment", increment)
    builder.add_edge(START, "increment")
    builder.add_edge("increment", END)
    return builder.compile(checkpointer=checkpointer)


@pytest.mark.asyncio
async def test_sqlite_checkpointer_survives_factory_restart(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'checkpoints.db'}"
    config = checkpoint_config("sqlite-restart", "tests")

    async with CheckpointerFactory("sqlite", database_url).open() as first:
        result = await counter_graph(first).ainvoke({"count": 4}, config)
        assert result["count"] == 5

    async with CheckpointerFactory("sqlite", database_url).open() as second:
        snapshot = await counter_graph(second).aget_state(config)
        assert snapshot.values["count"] == 5


@pytest.mark.asyncio
async def test_memory_checkpointer_is_available_without_database() -> None:
    async with CheckpointerFactory("memory").open() as saver:
        result = await counter_graph(saver).ainvoke(
            {"count": 0},
            checkpoint_config("memory-run"),
        )
    assert result["count"] == 1


def test_checkpoint_database_url_normalization() -> None:
    assert sqlite_connection_string("sqlite:///./data/checkpoint.db") == "./data/checkpoint.db"
    assert (
        sqlite_connection_string("sqlite+aiosqlite:///C:/data/checkpoint.db")
        == "C:/data/checkpoint.db"
    )
    assert (
        postgres_connection_string("postgresql+psycopg://user:pass@db/secmind")
        == "postgresql://user:pass@db/secmind"
    )
    with pytest.raises(CheckpointerConfigurationError):
        sqlite_connection_string("postgresql://db/secmind")
    with pytest.raises(CheckpointerConfigurationError):
        postgres_connection_string("sqlite:///checkpoint.db")
