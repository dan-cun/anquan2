from __future__ import annotations

import strawberry

from app.graphql.context import GraphQLContext, get_backend
from app.graphql.types import (
    AgentDelegation,
    Approval,
    Assistant,
    CreateAssistantInput,
    CreateFlowInput,
    CreatePromptVersionInput,
    DelegateAgentInput,
    Flow,
    MCPServer,
    PromptTemplate,
    PromptVersion,
    RegisterMCPServerInput,
    RevisePlanInput,
    SubmitFlowInput,
    Subtask,
    Task,
    UpdateMCPServerInput,
)


@strawberry.type
class Mutation:
    @strawberry.mutation
    async def create_flow(
        self,
        info: strawberry.Info[GraphQLContext, None],
        input: CreateFlowInput,
    ) -> Flow:
        return await get_backend(info).flows.create_flow(input)

    @strawberry.mutation
    async def submit_flow_input(
        self,
        info: strawberry.Info[GraphQLContext, None],
        flow_id: strawberry.ID,
        input: SubmitFlowInput,
    ) -> Flow:
        return await get_backend(info).flows.submit_flow_input(str(flow_id), input)

    @strawberry.mutation
    async def stop_flow(
        self,
        info: strawberry.Info[GraphQLContext, None],
        flow_id: strawberry.ID,
        reason: str | None = strawberry.UNSET,
    ) -> Flow:
        return await get_backend(info).flows.stop_flow(
            str(flow_id),
            None if reason is strawberry.UNSET else reason,
        )

    @strawberry.mutation
    async def finish_flow(
        self,
        info: strawberry.Info[GraphQLContext, None],
        flow_id: strawberry.ID,
    ) -> Flow:
        return await get_backend(info).flows.finish_flow(str(flow_id))

    @strawberry.mutation
    async def delete_flow(
        self,
        info: strawberry.Info[GraphQLContext, None],
        flow_id: strawberry.ID,
    ) -> bool:
        return await get_backend(info).flows.delete_flow(str(flow_id))

    @strawberry.mutation
    async def rename_flow(
        self,
        info: strawberry.Info[GraphQLContext, None],
        flow_id: strawberry.ID,
        title: str,
    ) -> Flow:
        return await get_backend(info).flows.rename_flow(str(flow_id), title)

    @strawberry.mutation
    async def create_assistant(
        self,
        info: strawberry.Info[GraphQLContext, None],
        flow_id: strawberry.ID,
        input: CreateAssistantInput,
    ) -> Assistant:
        return await get_backend(info).flows.create_assistant(str(flow_id), input)

    @strawberry.mutation
    async def call_assistant(
        self,
        info: strawberry.Info[GraphQLContext, None],
        flow_id: strawberry.ID,
        assistant_id: strawberry.ID,
        input: str,
        use_agents: bool | None = True,
    ) -> Assistant:
        return await get_backend(info).flows.call_assistant(
            str(flow_id),
            str(assistant_id),
            input,
            True if use_agents is None else use_agents,
        )

    @strawberry.mutation
    async def stop_assistant(
        self,
        info: strawberry.Info[GraphQLContext, None],
        flow_id: strawberry.ID,
        assistant_id: strawberry.ID,
    ) -> Assistant:
        return await get_backend(info).flows.stop_assistant(
            str(flow_id),
            str(assistant_id),
        )

    @strawberry.mutation
    async def delete_assistant(
        self,
        info: strawberry.Info[GraphQLContext, None],
        flow_id: strawberry.ID,
        assistant_id: strawberry.ID,
    ) -> bool:
        return await get_backend(info).flows.delete_assistant(
            str(flow_id),
            str(assistant_id),
        )

    @strawberry.mutation
    async def approve_action(
        self,
        info: strawberry.Info[GraphQLContext, None],
        run_id: strawberry.ID,
        request_id: strawberry.ID,
        reason: str | None = strawberry.UNSET,
    ) -> Approval:
        return await get_backend(info).audit.resolve_approval(
            str(run_id),
            str(request_id),
            True,
            None if reason is strawberry.UNSET else reason,
        )

    @strawberry.mutation
    async def reject_action(
        self,
        info: strawberry.Info[GraphQLContext, None],
        run_id: strawberry.ID,
        request_id: strawberry.ID,
        reason: str | None = strawberry.UNSET,
    ) -> Approval:
        return await get_backend(info).audit.resolve_approval(
            str(run_id),
            str(request_id),
            False,
            None if reason is strawberry.UNSET else reason,
        )

    @strawberry.mutation
    async def retry_subtask(
        self,
        info: strawberry.Info[GraphQLContext, None],
        subtask_id: strawberry.ID,
    ) -> Subtask:
        return await get_backend(info).flows.retry_subtask(str(subtask_id))

    @strawberry.mutation
    async def revise_plan(
        self,
        info: strawberry.Info[GraphQLContext, None],
        input: RevisePlanInput,
    ) -> Task:
        return await get_backend(info).flows.revise_plan(input)

    @strawberry.mutation
    async def delegate_agent(
        self,
        info: strawberry.Info[GraphQLContext, None],
        input: DelegateAgentInput,
    ) -> AgentDelegation:
        return await get_backend(info).agents.delegate(input)

    @strawberry.mutation(name="registerMCPServer")
    async def register_mcp_server(
        self,
        info: strawberry.Info[GraphQLContext, None],
        input: RegisterMCPServerInput,
    ) -> MCPServer:
        return await get_backend(info).mcp.register_server(input)

    @strawberry.mutation(name="updateMCPServer")
    async def update_mcp_server(
        self,
        info: strawberry.Info[GraphQLContext, None],
        server_id: strawberry.ID,
        input: UpdateMCPServerInput,
    ) -> MCPServer:
        return await get_backend(info).mcp.update_server(str(server_id), input)

    @strawberry.mutation(name="removeMCPServer")
    async def remove_mcp_server(
        self,
        info: strawberry.Info[GraphQLContext, None],
        server_id: strawberry.ID,
    ) -> bool:
        return await get_backend(info).mcp.remove_server(str(server_id))

    @strawberry.mutation(name="refreshMCPCapabilities")
    async def refresh_mcp_capabilities(
        self,
        info: strawberry.Info[GraphQLContext, None],
        server_id: strawberry.ID | None = strawberry.UNSET,
    ) -> list[MCPServer]:
        return list(
            await get_backend(info).mcp.refresh_capabilities(
                None if server_id is strawberry.UNSET or server_id is None else str(server_id)
            )
        )

    @strawberry.mutation
    async def create_prompt_version(
        self,
        info: strawberry.Info[GraphQLContext, None],
        input: CreatePromptVersionInput,
    ) -> PromptVersion:
        return await get_backend(info).prompts.create_version(input)

    @strawberry.mutation
    async def enable_prompt_version(
        self,
        info: strawberry.Info[GraphQLContext, None],
        prompt_key: strawberry.ID,
        version_id: strawberry.ID,
    ) -> PromptTemplate:
        return await get_backend(info).prompts.enable_version(
            str(prompt_key),
            str(version_id),
        )

    @strawberry.mutation
    async def import_prompts(
        self,
        info: strawberry.Info[GraphQLContext, None],
        workbook_ref: str,
    ) -> list[PromptTemplate]:
        return list(await get_backend(info).prompts.import_workbook(workbook_ref))
