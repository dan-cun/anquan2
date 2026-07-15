from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Literal

from langgraph.checkpoint.memory import MemorySaver

CheckpointBackend = Literal["memory", "sqlite", "postgres"]


class CheckpointerConfigurationError(ValueError):
    """Raised when a checkpoint backend and database URL do not match."""


@dataclass(frozen=True, slots=True)
class CheckpointerFactory:
    """Create a LangGraph checkpointer with an explicit connection lifecycle."""

    backend: CheckpointBackend = "memory"
    database_url: str | None = None

    @asynccontextmanager
    async def open(self) -> AsyncIterator[Any]:
        if self.backend == "memory":
            yield MemorySaver()
            return

        if not self.database_url:
            raise CheckpointerConfigurationError(
                f"checkpoint_database_url is required for {self.backend}"
            )

        if self.backend == "sqlite":
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

            connection_string = sqlite_connection_string(self.database_url)
            async with AsyncSqliteSaver.from_conn_string(connection_string) as saver:
                await saver.setup()
                yield saver
            return

        if self.backend == "postgres":
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

            connection_string = postgres_connection_string(self.database_url)
            async with AsyncPostgresSaver.from_conn_string(connection_string) as saver:
                # LangGraph owns its checkpoint schema. setup() is idempotent and applies
                # the package's checkpoint migrations on first startup.
                await saver.setup()
                yield saver
            return

        raise CheckpointerConfigurationError(f"unsupported checkpoint backend: {self.backend}")


def checkpoint_config(thread_id: str, namespace: str = "") -> dict[str, Any]:
    if not thread_id.strip():
        raise CheckpointerConfigurationError("thread_id must not be empty")
    normalized_namespace = namespace.strip()
    effective_thread_id = (
        f"{normalized_namespace}:{thread_id}" if normalized_namespace else thread_id
    )
    # checkpoint_ns is reserved by LangGraph for nested subgraphs. Application-level
    # namespacing belongs in the durable thread identifier.
    return {"configurable": {"thread_id": effective_thread_id}}


def sqlite_connection_string(database_url: str) -> str:
    if database_url == ":memory:":
        return database_url
    for prefix in ("sqlite+aiosqlite:///", "sqlite:///"):
        if database_url.startswith(prefix):
            path = database_url.removeprefix(prefix)
            if not path:
                break
            return path
    raise CheckpointerConfigurationError(
        "SQLite checkpointer requires sqlite:/// or sqlite+aiosqlite:/// URL"
    )


def postgres_connection_string(database_url: str) -> str:
    if database_url.startswith("postgresql+psycopg://"):
        return "postgresql://" + database_url.removeprefix("postgresql+psycopg://")
    if database_url.startswith("postgres://"):
        return "postgresql://" + database_url.removeprefix("postgres://")
    if database_url.startswith("postgresql://"):
        return database_url
    raise CheckpointerConfigurationError(
        "PostgreSQL checkpointer requires postgresql:// or postgresql+psycopg:// URL"
    )
