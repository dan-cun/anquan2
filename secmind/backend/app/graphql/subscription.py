from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import strawberry
from graphql import GraphQLError

from app.graphql.context import GraphQLContext, get_backend
from app.graphql.types import (
    AgentDelegation,
    AgentInstance,
    AgentMessage,
    AgentResult,
    Approval,
    Assistant,
    Flow,
    MCPCapability,
    MCPServer,
    Report,
    RuntimeEvent,
    Subtask,
    Task,
    ToolCall,
)


async def _events(
    info: strawberry.Info[GraphQLContext, None],
    topic: str,
    **filters: Any,
) -> AsyncIterator[Any]:
    async for event in get_backend(info).events.subscribe(topic, **filters):
        yield event


@strawberry.type
class Subscription:
    @strawberry.subscription
    async def flow_updated(
        self,
        info: strawberry.Info[GraphQLContext, None],
        flow_id: strawberry.ID | None = strawberry.UNSET,
    ) -> AsyncIterator[Flow]:
        async for event in _events(
            info,
            "flow.updated",
            flow_id=None if flow_id is strawberry.UNSET or flow_id is None else str(flow_id),
        ):
            yield event

    @strawberry.subscription
    async def task_updated(
        self,
        info: strawberry.Info[GraphQLContext, None],
        flow_id: strawberry.ID,
    ) -> AsyncIterator[Task]:
        async for event in _events(info, "task.updated", flow_id=str(flow_id)):
            yield event

    @strawberry.subscription
    async def subtask_updated(
        self,
        info: strawberry.Info[GraphQLContext, None],
        flow_id: strawberry.ID,
    ) -> AsyncIterator[Subtask]:
        async for event in _events(info, "subtask.updated", flow_id=str(flow_id)):
            yield event

    @strawberry.subscription
    async def assistant_created(
        self,
        info: strawberry.Info[GraphQLContext, None],
        flow_id: strawberry.ID,
    ) -> AsyncIterator[Assistant]:
        async for event in _events(info, "assistant.created", flow_id=str(flow_id)):
            yield event

    @strawberry.subscription
    async def assistant_updated(
        self,
        info: strawberry.Info[GraphQLContext, None],
        flow_id: strawberry.ID,
    ) -> AsyncIterator[Assistant]:
        async for event in _events(info, "assistant.updated", flow_id=str(flow_id)):
            yield event

    @strawberry.subscription
    async def assistant_deleted(
        self,
        info: strawberry.Info[GraphQLContext, None],
        flow_id: strawberry.ID,
    ) -> AsyncIterator[Assistant]:
        async for event in _events(info, "assistant.deleted", flow_id=str(flow_id)):
            yield event

    @strawberry.subscription
    async def agent_started(
        self,
        info: strawberry.Info[GraphQLContext, None],
        flow_id: strawberry.ID,
    ) -> AsyncIterator[AgentInstance]:
        async for event in _events(info, "agent.started", flow_id=str(flow_id)):
            yield event

    @strawberry.subscription
    async def agent_delegated(
        self,
        info: strawberry.Info[GraphQLContext, None],
        flow_id: strawberry.ID,
    ) -> AsyncIterator[AgentDelegation]:
        async for event in _events(info, "agent.delegated", flow_id=str(flow_id)):
            yield event

    @strawberry.subscription
    async def agent_message_added(
        self,
        info: strawberry.Info[GraphQLContext, None],
        flow_id: strawberry.ID,
    ) -> AsyncIterator[AgentMessage]:
        async for event in _events(info, "agent.message", flow_id=str(flow_id)):
            yield event

    @strawberry.subscription
    async def agent_completed(
        self,
        info: strawberry.Info[GraphQLContext, None],
        flow_id: strawberry.ID,
    ) -> AsyncIterator[AgentResult]:
        async for event in _events(info, "agent.completed", flow_id=str(flow_id)):
            yield event

    @strawberry.subscription
    async def agent_failed(
        self,
        info: strawberry.Info[GraphQLContext, None],
        flow_id: strawberry.ID,
    ) -> AsyncIterator[AgentResult]:
        async for event in _events(info, "agent.failed", flow_id=str(flow_id)):
            yield event

    @strawberry.subscription
    async def tool_call_started(
        self,
        info: strawberry.Info[GraphQLContext, None],
        flow_id: strawberry.ID,
    ) -> AsyncIterator[ToolCall]:
        async for event in _events(info, "tool.started", flow_id=str(flow_id)):
            yield event

    @strawberry.subscription
    async def tool_call_updated(
        self,
        info: strawberry.Info[GraphQLContext, None],
        flow_id: strawberry.ID,
    ) -> AsyncIterator[ToolCall]:
        async for event in _events(info, "tool.updated", flow_id=str(flow_id)):
            yield event

    @strawberry.subscription(name="mcpServerUpdated")
    async def mcp_server_updated(
        self,
        info: strawberry.Info[GraphQLContext, None],
        server_id: strawberry.ID | None = strawberry.UNSET,
    ) -> AsyncIterator[MCPServer]:
        async for event in _events(
            info,
            "mcp.server_updated",
            server_id=None
            if server_id is strawberry.UNSET or server_id is None
            else str(server_id),
        ):
            yield event

    @strawberry.subscription(name="mcpCapabilityUpdated")
    async def mcp_capability_updated(
        self,
        info: strawberry.Info[GraphQLContext, None],
        server_id: strawberry.ID | None = strawberry.UNSET,
    ) -> AsyncIterator[MCPCapability]:
        async for event in _events(
            info,
            "mcp.capabilities_updated",
            server_id=None
            if server_id is strawberry.UNSET or server_id is None
            else str(server_id),
        ):
            yield event

    @strawberry.subscription
    async def approval_requested(
        self,
        info: strawberry.Info[GraphQLContext, None],
        run_id: strawberry.ID,
    ) -> AsyncIterator[Approval]:
        async for event in _events(info, "approval.requested", run_id=str(run_id)):
            yield event

    @strawberry.subscription
    async def runtime_event_added(
        self,
        info: strawberry.Info[GraphQLContext, None],
        run_id: strawberry.ID,
        after_sequence: int | None = 0,
    ) -> AsyncIterator[RuntimeEvent]:
        if after_sequence is None:
            after_sequence = 0
        if after_sequence < 0:
            raise GraphQLError("afterSequence must not be negative")
        async for event in _events(
            info,
            "runtime.event",
            run_id=str(run_id),
            after_sequence=after_sequence,
        ):
            yield event

    @strawberry.subscription
    async def report_updated(
        self,
        info: strawberry.Info[GraphQLContext, None],
        run_id: strawberry.ID,
    ) -> AsyncIterator[Report]:
        async for event in _events(info, "report.generated", run_id=str(run_id)):
            yield event
