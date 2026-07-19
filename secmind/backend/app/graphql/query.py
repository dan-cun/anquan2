from __future__ import annotations

import asyncio

import strawberry
from graphql import GraphQLError
from strawberry.scalars import JSON

from app.graphql.context import GraphQLContext, get_backend
from app.graphql.types import (
    AgentDelegation,
    AgentDescriptor,
    AgentInstance,
    AgentMessage,
    Approval,
    Artifact,
    Assistant,
    CapabilityKind,
    Evidence,
    Finding,
    Flow,
    MCPCapability,
    MCPServer,
    MessageChain,
    PromptTemplate,
    Report,
    RuntimeEvent,
    Subtask,
    Task,
    ToolCall,
    UnifiedTool,
    UsageStats,
)


def _cursor(value: int | None) -> int:
    if value is None:
        return 0
    if value < 0:
        raise GraphQLError("afterSequence must not be negative")
    return value


async def _hydrate_task(info: strawberry.Info[GraphQLContext, None], task: Task) -> Task:
    task.subtasks = await info.context.loaders.subtasks_by_task.load(str(task.id))
    return task


async def _hydrate_flow(info: strawberry.Info[GraphQLContext, None], flow: Flow) -> Flow:
    tasks = await info.context.loaders.tasks_by_flow.load(str(flow.id))
    flow.tasks = list(await asyncio.gather(*(_hydrate_task(info, task) for task in tasks)))
    return flow


@strawberry.type
class Query:
    @strawberry.field
    async def flows(self, info: strawberry.Info[GraphQLContext, None]) -> list[Flow]:
        flows = list(await get_backend(info).flows.list_flows())
        return list(await asyncio.gather(*(_hydrate_flow(info, flow) for flow in flows)))

    @strawberry.field
    async def flow(
        self,
        info: strawberry.Info[GraphQLContext, None],
        flow_id: strawberry.ID,
    ) -> Flow:
        flow = await get_backend(info).flows.get_flow(str(flow_id))
        if flow is None:
            raise GraphQLError("flow not found", extensions={"code": "NOT_FOUND"})
        return await _hydrate_flow(info, flow)

    @strawberry.field
    async def tasks(
        self,
        info: strawberry.Info[GraphQLContext, None],
        flow_id: strawberry.ID,
    ) -> list[Task]:
        tasks = await info.context.loaders.tasks_by_flow.load(str(flow_id))
        return list(await asyncio.gather(*(_hydrate_task(info, task) for task in tasks)))

    @strawberry.field
    async def subtasks(
        self,
        info: strawberry.Info[GraphQLContext, None],
        task_id: strawberry.ID,
    ) -> list[Subtask]:
        return await info.context.loaders.subtasks_by_task.load(str(task_id))

    @strawberry.field
    async def assistants(
        self,
        info: strawberry.Info[GraphQLContext, None],
        flow_id: strawberry.ID,
    ) -> list[Assistant]:
        return list(await get_backend(info).flows.list_assistants(str(flow_id)))

    @strawberry.field
    async def agent_descriptors(
        self,
        info: strawberry.Info[GraphQLContext, None],
    ) -> list[AgentDescriptor]:
        return list(await get_backend(info).agents.list_descriptors())

    @strawberry.field
    async def agent_instances(
        self,
        info: strawberry.Info[GraphQLContext, None],
        flow_id: strawberry.ID,
        run_id: strawberry.ID | None = strawberry.UNSET,
    ) -> list[AgentInstance]:
        return list(
            await get_backend(info).agents.list_instances(
                str(flow_id),
                None if run_id is strawberry.UNSET or run_id is None else str(run_id),
            )
        )

    @strawberry.field
    async def agent_delegations(
        self,
        info: strawberry.Info[GraphQLContext, None],
        flow_id: strawberry.ID,
        run_id: strawberry.ID | None = strawberry.UNSET,
    ) -> list[AgentDelegation]:
        return list(
            await get_backend(info).agents.list_delegations(
                str(flow_id),
                None if run_id is strawberry.UNSET or run_id is None else str(run_id),
            )
        )

    @strawberry.field
    async def agent_messages(
        self,
        info: strawberry.Info[GraphQLContext, None],
        flow_id: strawberry.ID,
        after_sequence: int | None = 0,
    ) -> list[AgentMessage]:
        cursor = _cursor(after_sequence)
        return list(
            await get_backend(info).agents.list_messages(
                str(flow_id),
                cursor,
            )
        )

    @strawberry.field
    async def tools(self, info: strawberry.Info[GraphQLContext, None]) -> list[UnifiedTool]:
        return list(await get_backend(info).tools.list_tools())

    @strawberry.field
    async def tool_calls(
        self,
        info: strawberry.Info[GraphQLContext, None],
        flow_id: strawberry.ID,
        agent_instance_id: strawberry.ID | None = strawberry.UNSET,
    ) -> list[ToolCall]:
        return list(
            await get_backend(info).tools.list_tool_calls(
                str(flow_id),
                None
                if agent_instance_id is strawberry.UNSET or agent_instance_id is None
                else str(agent_instance_id),
            )
        )

    @strawberry.field
    async def message_chains(
        self,
        info: strawberry.Info[GraphQLContext, None],
        flow_id: strawberry.ID,
        agent_instance_id: strawberry.ID | None = strawberry.UNSET,
    ) -> list[MessageChain]:
        return list(
            await get_backend(info).tools.list_message_chains(
                str(flow_id),
                None
                if agent_instance_id is strawberry.UNSET or agent_instance_id is None
                else str(agent_instance_id),
            )
        )

    @strawberry.field(name="mcpServers")
    async def mcp_servers(
        self,
        info: strawberry.Info[GraphQLContext, None],
    ) -> list[MCPServer]:
        return list(await get_backend(info).mcp.list_servers())

    @strawberry.field(name="mcpCapabilities")
    async def mcp_capabilities(
        self,
        info: strawberry.Info[GraphQLContext, None],
        server_id: strawberry.ID | None = strawberry.UNSET,
        kind: CapabilityKind | None = strawberry.UNSET,
    ) -> list[MCPCapability]:
        return list(
            await get_backend(info).mcp.list_capabilities(
                None if server_id is strawberry.UNSET or server_id is None else str(server_id),
                None if kind is strawberry.UNSET else kind,
            )
        )

    @strawberry.field
    async def prompts(
        self,
        info: strawberry.Info[GraphQLContext, None],
    ) -> list[PromptTemplate]:
        return list(await get_backend(info).prompts.list_prompts())

    @strawberry.field
    async def prompt(
        self,
        info: strawberry.Info[GraphQLContext, None],
        prompt_key: strawberry.ID,
    ) -> PromptTemplate:
        prompt = await get_backend(info).prompts.get_prompt(str(prompt_key))
        if prompt is None:
            raise GraphQLError("prompt not found", extensions={"code": "NOT_FOUND"})
        return prompt

    @strawberry.field
    async def approvals(
        self,
        info: strawberry.Info[GraphQLContext, None],
        run_id: strawberry.ID,
    ) -> list[Approval]:
        return list(await get_backend(info).audit.list_approvals(str(run_id)))

    @strawberry.field
    async def runtime_events(
        self,
        info: strawberry.Info[GraphQLContext, None],
        run_id: strawberry.ID,
        after_sequence: int | None = 0,
    ) -> list[RuntimeEvent]:
        cursor = _cursor(after_sequence)
        return list(
            await get_backend(info).audit.list_runtime_events(
                str(run_id),
                cursor,
            )
        )

    @strawberry.field
    async def report(
        self,
        info: strawberry.Info[GraphQLContext, None],
        run_id: strawberry.ID,
    ) -> Report | None:
        return await get_backend(info).audit.get_report(str(run_id))

    @strawberry.field
    async def artifacts(
        self,
        info: strawberry.Info[GraphQLContext, None],
        run_id: strawberry.ID,
    ) -> list[Artifact]:
        return list(await get_backend(info).audit.list_artifacts(str(run_id)))

    @strawberry.field
    async def evidence(
        self,
        info: strawberry.Info[GraphQLContext, None],
        run_id: strawberry.ID,
    ) -> list[Evidence]:
        return list(await get_backend(info).audit.list_evidence(str(run_id)))

    @strawberry.field
    async def findings(
        self,
        info: strawberry.Info[GraphQLContext, None],
        run_id: strawberry.ID,
    ) -> list[Finding]:
        return list(await get_backend(info).audit.list_findings(str(run_id)))

    @strawberry.field
    async def usage_by_flow(
        self,
        info: strawberry.Info[GraphQLContext, None],
        flow_id: strawberry.ID,
    ) -> UsageStats:
        return await get_backend(info).analytics.usage_by_flow(str(flow_id))

    @strawberry.field
    async def usage_by_agent(
        self,
        info: strawberry.Info[GraphQLContext, None],
        flow_id: strawberry.ID,
    ) -> JSON:
        return await get_backend(info).analytics.usage_by_agent(str(flow_id))

    @strawberry.field
    async def usage_by_model(
        self,
        info: strawberry.Info[GraphQLContext, None],
        flow_id: strawberry.ID | None = strawberry.UNSET,
    ) -> JSON:
        return await get_backend(info).analytics.usage_by_model(
            None if flow_id is strawberry.UNSET or flow_id is None else str(flow_id)
        )

    @strawberry.field
    async def usage_by_tool(
        self,
        info: strawberry.Info[GraphQLContext, None],
        flow_id: strawberry.ID | None = strawberry.UNSET,
    ) -> JSON:
        return await get_backend(info).analytics.usage_by_tool(
            None if flow_id is strawberry.UNSET or flow_id is None else str(flow_id)
        )
