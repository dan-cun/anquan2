from __future__ import annotations

import asyncio
from typing import Any

import pytest

from agents.dispatcher import AgentDispatcher
from agents.native import AgentRunContext, NativeAgent
from agents.registry import NativeAgentRegistry
from app.database import create_native_repositories
from app.schemas.agents import (
    AgentDescriptor,
    AgentMessageKind,
    AgentResult,
    AgentRole,
    AgentStatus,
    AgentTask,
)
from app.schemas.runtime import EventContext
from app.services.collaboration import NativeCollaborationService
from app.services.runtime import RuntimeEventHub
from ledger.runtime_store import Base, RuntimeLedgerStore


class EventRecorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any], str, EventContext | None]] = []

    async def publish(
        self,
        event_type: str,
        payload: dict[str, Any],
        actor: str,
        context: EventContext | None = None,
    ) -> None:
        self.events.append((event_type, payload, actor, context))


class WaitingAgent(NativeAgent):
    def __init__(self, descriptor: AgentDescriptor, started: asyncio.Event) -> None:
        super().__init__(descriptor)
        self.started = started

    async def run(self, context: AgentRunContext) -> AgentResult:
        self.started.set()
        message = await context.wait_for_message(
            reason="等待协作消息",
            timeout_seconds=5,
        )
        if context.stop_requested():
            return AgentResult(
                agent_instance_id=context.instance.instance_id,
                task_id=context.task.task_id,
                status=AgentStatus.CANCELLED,
                summary="Agent stopped while waiting",
            )
        return AgentResult(
            agent_instance_id=context.instance.instance_id,
            task_id=context.task.task_id,
            status=AgentStatus.COMPLETED,
            summary="No message" if message is None else message.summary,
        )


class ParentAgent(NativeAgent):
    async def run(self, context: AgentRunContext) -> AgentResult:
        child = await context.delegate(
            AgentRole.PENTESTER,
            objective="等待验证指令",
        )
        return AgentResult(
            agent_instance_id=context.instance.instance_id,
            task_id=context.task.task_id,
            status=AgentStatus.COMPLETED,
            summary=f"Child ended as {child.status.value}",
        )


def descriptor(role: AgentRole) -> AgentDescriptor:
    return AgentDescriptor(
        role=role,
        display_name=role.value,
        prompt_key=role.value,
    )


async def wait_for_status(
    dispatcher: AgentDispatcher,
    instance_id: str,
    status: AgentStatus,
) -> None:
    async with asyncio.timeout(2):
        while True:
            instance = next(
                item for item in dispatcher.instances() if item.instance_id == instance_id
            )
            if instance.status == status:
                return
            await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_background_create_message_wait_and_stop_are_correlated() -> None:
    source_started = asyncio.Event()
    target_started = asyncio.Event()
    registry = NativeAgentRegistry()
    source_descriptor = descriptor(AgentRole.SEARCHER)
    target_descriptor = descriptor(AgentRole.PENTESTER)
    registry.register(source_descriptor, lambda item: WaitingAgent(item, source_started))
    registry.register(target_descriptor, lambda item: WaitingAgent(item, target_started))
    events = EventRecorder()
    dispatcher = AgentDispatcher(registry=registry, publisher=events.publish)

    source = await dispatcher.start_root(
        AgentRole.SEARCHER,
        AgentTask(run_id="run-graph", flow_id="flow-graph", objective="等待来源消息"),
    )
    target = await dispatcher.start_root(
        AgentRole.PENTESTER,
        AgentTask(run_id="run-graph", flow_id="flow-graph", objective="等待验证消息"),
    )
    await source_started.wait()
    await target_started.wait()
    await wait_for_status(dispatcher, source.instance_id, AgentStatus.WAITING)
    await wait_for_status(dispatcher, target.instance_id, AgentStatus.WAITING)

    message = await dispatcher.send_message(
        from_agent_instance_id=source.instance_id,
        to_agent_instance_id=target.instance_id,
        summary="请验证 evidence-1",
        kind=AgentMessageKind.REQUEST,
        metadata={"evidence_ids": ["evidence-1"]},
    )
    target_result = await dispatcher.wait_for_agent(target.instance_id, timeout_seconds=2)

    assert message.sequence == 1
    assert target_result is not None
    assert target_result.status == AgentStatus.COMPLETED
    assert target_result.summary == "请验证 evidence-1"
    target_chain = await dispatcher.chain_store.for_instance(target.instance_id)
    assert target_chain.messages[-1].metadata["graph_message_id"] == message.message_id

    await dispatcher.stop_agent(source.instance_id, reason="测试完成，停止等待")
    source_result = await dispatcher.wait_for_agent(source.instance_id, timeout_seconds=2)
    assert source_result is not None
    assert source_result.status == AgentStatus.CANCELLED

    event_types = [item[0] for item in events.events]
    assert "agent.waiting" in event_types
    assert "agent.resumed" in event_types
    assert "agent.message" in event_types
    assert "agent.stop_requested" in event_types
    assert event_types[-1] == "agent.cancelled"

    stop_index = event_types.index("agent.stop_requested")
    decision = events.events[stop_index - 1]
    stopped = events.events[stop_index]
    assert decision[0] == "decision.recorded"
    assert decision[3] is not None and stopped[3] is not None
    assert decision[3].decision_id == stopped[3].decision_id
    assert decision[3].correlation_id == stopped[3].correlation_id


@pytest.mark.asyncio
async def test_stopping_child_does_not_cancel_parent_agent() -> None:
    child_started = asyncio.Event()
    registry = NativeAgentRegistry()
    primary_descriptor = descriptor(AgentRole.PRIMARY_AGENT)
    child_descriptor = descriptor(AgentRole.PENTESTER)
    registry.register(primary_descriptor, ParentAgent)
    registry.register(child_descriptor, lambda item: WaitingAgent(item, child_started))
    dispatcher = AgentDispatcher(registry=registry)

    parent = await dispatcher.start_root(
        AgentRole.PRIMARY_AGENT,
        AgentTask(run_id="run-subtree", flow_id="flow-subtree", objective="协调子任务"),
    )
    await child_started.wait()
    child = next(
        item
        for item in dispatcher.instances("run-subtree")
        if item.parent_instance_id == parent.instance_id
    )
    await wait_for_status(dispatcher, child.instance_id, AgentStatus.WAITING)

    await dispatcher.stop_agent(child.instance_id, reason="该验证分支不再需要")
    child_result = await dispatcher.wait_for_agent(child.instance_id, timeout_seconds=2)
    parent_result = await dispatcher.wait_for_agent(parent.instance_id, timeout_seconds=2)

    assert child_result is not None and child_result.status == AgentStatus.CANCELLED
    assert parent_result is not None and parent_result.status == AgentStatus.COMPLETED
    assert parent_result.summary == "Child ended as cancelled"


@pytest.mark.asyncio
async def test_agent_graph_state_messages_and_event_context_are_persisted(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'agent-graph.db'}"
    repositories = create_native_repositories(database_url)
    Base.metadata.create_all(repositories.engine)
    flow = repositories.flows.create_flow(title="Agent Graph")
    ledger = RuntimeLedgerStore(database_url)
    event_hub = RuntimeEventHub()
    source_started = asyncio.Event()
    target_started = asyncio.Event()
    registry = NativeAgentRegistry()
    registry.register(
        descriptor(AgentRole.SEARCHER),
        lambda item: WaitingAgent(item, source_started),
    )
    registry.register(
        descriptor(AgentRole.PENTESTER),
        lambda item: WaitingAgent(item, target_started),
    )
    service: NativeCollaborationService | None = None

    async def publish(
        event_type: str,
        payload: dict[str, Any],
        actor: str,
        context: EventContext | None = None,
    ) -> None:
        assert service is not None
        await service.publish_agent_event(event_type, payload, actor, context)

    dispatcher = AgentDispatcher(registry=registry, publisher=publish)
    service = NativeCollaborationService(
        dispatcher=dispatcher,
        repositories=repositories,
        ledger=ledger,
        event_hub=event_hub,
    )
    source = await service.start(
        flow_id=flow.id,
        run_id="run-persisted",
        role=AgentRole.SEARCHER,
        objective="等待协作方",
    )
    target = await service.start(
        flow_id=flow.id,
        run_id="run-persisted",
        role=AgentRole.PENTESTER,
        objective="等待验证请求",
    )
    await source_started.wait()
    await target_started.wait()
    await wait_for_status(dispatcher, source.instance_id, AgentStatus.WAITING)
    await wait_for_status(dispatcher, target.instance_id, AgentStatus.WAITING)

    message = await service.send_message(
        from_agent_instance_id=source.instance_id,
        to_agent_instance_id=target.instance_id,
        summary="验证 evidence-persisted",
        kind=AgentMessageKind.REQUEST,
    )
    await dispatcher.wait_for_agent(target.instance_id, timeout_seconds=2)
    await service.stop_agent(source.instance_id, reason="持久化测试结束")
    await dispatcher.wait_for_agent(source.instance_id, timeout_seconds=2)

    stored_messages = repositories.agents.list_messages("run-persisted")
    assert [item.message_id for item in stored_messages] == [message.message_id]
    assert repositories.agents.get_instance(target.instance_id).status == AgentStatus.COMPLETED
    assert repositories.agents.get_instance(source.instance_id).status == AgentStatus.CANCELLED

    events = ledger.events("run-persisted", limit=100)
    stop_event = next(item for item in events if item.event_type == "agent.stop_requested")
    stop_decision = next(
        item
        for item in events
        if item.event_type == "decision.recorded"
        and item.context.decision_id == stop_event.context.decision_id
    )
    assert stop_decision.sequence < stop_event.sequence
    assert stop_decision.context.correlation_id == stop_event.context.correlation_id
    assert stop_event.context.agent_instance_id == source.instance_id
    assert ledger.verify("run-persisted") is True
