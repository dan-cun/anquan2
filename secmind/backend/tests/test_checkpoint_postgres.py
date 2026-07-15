from __future__ import annotations

import os
from typing import Any, TypedDict
from uuid import uuid4

import pytest
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from ledger.checkpoints import CheckpointerFactory, checkpoint_config


class ApprovalState(TypedDict, total=False):
    request: str
    approved: bool


def approval_graph(checkpointer: Any):
    async def approval(state: ApprovalState) -> ApprovalState:
        response = interrupt({"request": state["request"]})
        return {"approved": bool(response.get("approved"))}

    builder = StateGraph(ApprovalState)
    builder.add_node("approval", approval)
    builder.add_edge(START, "approval")
    builder.add_edge("approval", END)
    return builder.compile(checkpointer=checkpointer)


@pytest.mark.asyncio
async def test_postgres_interrupt_resumes_after_process_restart() -> None:
    database_url = os.getenv("SECMIND_TEST_POSTGRES_URL")
    if not database_url:
        pytest.skip("SECMIND_TEST_POSTGRES_URL is not configured")

    thread_id = f"postgres-restart-{uuid4()}"
    config = checkpoint_config(thread_id, "integration-tests")
    factory = CheckpointerFactory("postgres", database_url)

    async with factory.open() as first:
        waiting = await approval_graph(first).ainvoke({"request": "approve scan"}, config)
        assert waiting["request"] == "approve scan"

    # A new saver and graph model a new application process using the same PostgreSQL DB.
    async with factory.open() as second:
        completed = await approval_graph(second).ainvoke(
            Command(resume={"approved": True}),
            config,
        )
        assert completed["approved"] is True
        await second.adelete_thread(config["configurable"]["thread_id"])
