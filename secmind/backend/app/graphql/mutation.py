from __future__ import annotations

import strawberry

from app.graphql.context import GraphQLContext, get_backend
from app.graphql.types import (
    AgentDelegation,
    AgentInstance,
    AgentMessage,
    Approval,
    Assistant,
    ContextSnapshot,
    CreateAgentInput,
    CreateAssistantInput,
    CreateFlowInput,
    CreatePromptVersionInput,
    CreateTodoInput,
    DelegateAgentInput,
    Flow,
    LoadSkillInput,
    MCPServer,
    Note,
    PromptTemplate,
    PromptVersion,
    RecordNoteInput,
    RegisterMCPServerInput,
    RegisterSkillInput,
    RevisePlanInput,
    SendAgentMessageInput,
    Skill,
    SkillLoad,
    SubmitFlowInput,
    Subtask,
    Task,
    Todo,
    UpdateMCPServerInput,
    UpdateTodoInput,
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

    @strawberry.mutation
    async def create_agent(
        self,
        info: strawberry.Info[GraphQLContext, None],
        input: CreateAgentInput,
    ) -> AgentInstance:
        return await get_backend(info).agents.create(input)

    @strawberry.mutation
    async def send_agent_message(
        self,
        info: strawberry.Info[GraphQLContext, None],
        input: SendAgentMessageInput,
    ) -> AgentMessage:
        return await get_backend(info).agents.send_message(input)

    @strawberry.mutation
    async def wait_agent(
        self,
        info: strawberry.Info[GraphQLContext, None],
        agent_instance_id: strawberry.ID,
        timeout_seconds: int = 30,
    ) -> AgentInstance:
        return await get_backend(info).agents.wait_agent(
            str(agent_instance_id),
            timeout_seconds,
        )

    @strawberry.mutation
    async def stop_agent(
        self,
        info: strawberry.Info[GraphQLContext, None],
        agent_instance_id: strawberry.ID,
        reason: str = "Operator requested stop",
    ) -> AgentInstance:
        return await get_backend(info).agents.stop_agent(str(agent_instance_id), reason)

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

    @strawberry.mutation
    async def register_skill(
        self,
        info: strawberry.Info[GraphQLContext, None],
        input: RegisterSkillInput,
    ) -> Skill:
        return await get_backend(info).long_term.register_skill(input)

    @strawberry.mutation
    async def load_skill(
        self,
        info: strawberry.Info[GraphQLContext, None],
        input: LoadSkillInput,
    ) -> SkillLoad:
        return await get_backend(info).long_term.load_skill(input)

    @strawberry.mutation
    async def unload_skill(
        self,
        info: strawberry.Info[GraphQLContext, None],
        load_id: strawberry.ID,
    ) -> SkillLoad:
        return await get_backend(info).long_term.unload_skill(str(load_id))

    @strawberry.mutation
    async def create_todo(
        self,
        info: strawberry.Info[GraphQLContext, None],
        input: CreateTodoInput,
    ) -> Todo:
        return await get_backend(info).long_term.create_todo(input)

    @strawberry.mutation
    async def update_todo(
        self,
        info: strawberry.Info[GraphQLContext, None],
        todo_id: strawberry.ID,
        input: UpdateTodoInput,
    ) -> Todo:
        return await get_backend(info).long_term.update_todo(str(todo_id), input)

    @strawberry.mutation
    async def record_note(
        self,
        info: strawberry.Info[GraphQLContext, None],
        input: RecordNoteInput,
    ) -> Note:
        return await get_backend(info).long_term.record_note(input)

    @strawberry.mutation
    async def archive_note(
        self,
        info: strawberry.Info[GraphQLContext, None],
        note_id: strawberry.ID,
    ) -> Note:
        return await get_backend(info).long_term.archive_note(str(note_id))

    @strawberry.mutation
    async def compress_context(
        self,
        info: strawberry.Info[GraphQLContext, None],
        run_id: strawberry.ID,
        flow_id: strawberry.ID,
        agent_instance_id: strawberry.ID | None = strawberry.UNSET,
    ) -> ContextSnapshot:
        return await get_backend(info).long_term.compress_context(
            str(run_id),
            str(flow_id),
            None
            if agent_instance_id is strawberry.UNSET or agent_instance_id is None
            else str(agent_instance_id),
        )
