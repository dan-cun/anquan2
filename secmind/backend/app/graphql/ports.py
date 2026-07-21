from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from app.graphql.types import (
    AgentDelegation,
    AgentDescriptor,
    AgentInstance,
    AgentMessage,
    Approval,
    Artifact,
    Assistant,
    CapabilityKind,
    ContextSnapshot,
    CreateAgentInput,
    CreateAssistantInput,
    CreateFlowInput,
    CreatePromptVersionInput,
    CreateTodoInput,
    DelegateAgentInput,
    Evidence,
    Finding,
    Flow,
    LoadSkillInput,
    MCPCapability,
    MCPServer,
    MessageChain,
    Note,
    PromptTemplate,
    PromptVersion,
    RecordNoteInput,
    RegisterMCPServerInput,
    RegisterSkillInput,
    Report,
    RevisePlanInput,
    RuntimeEvent,
    SendAgentMessageInput,
    Skill,
    SkillLoad,
    SubmitFlowInput,
    Subtask,
    Task,
    Todo,
    ToolCall,
    UnifiedTool,
    UpdateMCPServerInput,
    UpdateTodoInput,
    UsageStats,
)


class FlowGraphQLPort(Protocol):
    async def list_flows(self) -> Sequence[Flow]: ...

    async def get_flow(self, flow_id: str) -> Flow | None: ...

    async def list_tasks(self, flow_id: str) -> Sequence[Task]: ...

    async def list_subtasks(self, task_id: str) -> Sequence[Subtask]: ...

    async def list_assistants(self, flow_id: str) -> Sequence[Assistant]: ...

    async def create_flow(self, input: CreateFlowInput) -> Flow: ...

    async def submit_flow_input(self, flow_id: str, input: SubmitFlowInput) -> Flow: ...

    async def stop_flow(self, flow_id: str, reason: str | None) -> Flow: ...

    async def finish_flow(self, flow_id: str) -> Flow: ...

    async def delete_flow(self, flow_id: str) -> bool: ...

    async def rename_flow(self, flow_id: str, title: str) -> Flow: ...

    async def create_assistant(
        self,
        flow_id: str,
        input: CreateAssistantInput,
    ) -> Assistant: ...

    async def call_assistant(
        self,
        flow_id: str,
        assistant_id: str,
        input: str,
        use_agents: bool,
    ) -> Assistant: ...

    async def stop_assistant(self, flow_id: str, assistant_id: str) -> Assistant: ...

    async def delete_assistant(self, flow_id: str, assistant_id: str) -> bool: ...

    async def retry_subtask(self, subtask_id: str) -> Subtask: ...

    async def revise_plan(self, input: RevisePlanInput) -> Task: ...


class AgentGraphQLPort(Protocol):
    async def list_descriptors(self) -> Sequence[AgentDescriptor]: ...

    async def list_instances(
        self,
        flow_id: str,
        run_id: str | None,
    ) -> Sequence[AgentInstance]: ...

    async def list_delegations(
        self,
        flow_id: str,
        run_id: str | None,
    ) -> Sequence[AgentDelegation]: ...

    async def list_messages(
        self,
        flow_id: str,
        after_sequence: int,
    ) -> Sequence[AgentMessage]: ...

    async def delegate(self, input: DelegateAgentInput) -> AgentDelegation: ...

    async def create(self, input: CreateAgentInput) -> AgentInstance: ...

    async def send_message(self, input: SendAgentMessageInput) -> AgentMessage: ...

    async def wait_agent(
        self,
        agent_instance_id: str,
        timeout_seconds: int,
    ) -> AgentInstance: ...

    async def stop_agent(self, agent_instance_id: str, reason: str) -> AgentInstance: ...


class ToolGraphQLPort(Protocol):
    async def list_tools(self) -> Sequence[UnifiedTool]: ...

    async def list_tool_calls(
        self,
        flow_id: str,
        agent_instance_id: str | None,
    ) -> Sequence[ToolCall]: ...

    async def list_message_chains(
        self,
        flow_id: str,
        agent_instance_id: str | None,
    ) -> Sequence[MessageChain]: ...


class MCPGraphQLPort(Protocol):
    async def list_servers(self) -> Sequence[MCPServer]: ...

    async def list_capabilities(
        self,
        server_id: str | None,
        kind: CapabilityKind | None,
    ) -> Sequence[MCPCapability]: ...

    async def register_server(self, input: RegisterMCPServerInput) -> MCPServer: ...

    async def update_server(
        self,
        server_id: str,
        input: UpdateMCPServerInput,
    ) -> MCPServer: ...

    async def remove_server(self, server_id: str) -> bool: ...

    async def refresh_capabilities(self, server_id: str | None) -> Sequence[MCPServer]: ...


class PromptGraphQLPort(Protocol):
    async def list_prompts(self) -> Sequence[PromptTemplate]: ...

    async def get_prompt(self, prompt_key: str) -> PromptTemplate | None: ...

    async def create_version(self, input: CreatePromptVersionInput) -> PromptVersion: ...

    async def enable_version(self, prompt_key: str, version_id: str) -> PromptTemplate: ...

    async def import_workbook(self, workbook_ref: str) -> Sequence[PromptTemplate]: ...


class LongTermGraphQLPort(Protocol):
    async def list_skills(self, enabled: bool | None) -> Sequence[Skill]: ...
    async def list_skill_loads(
        self, run_id: str, agent_instance_id: str | None
    ) -> Sequence[SkillLoad]: ...
    async def list_todos(self, run_id: str) -> Sequence[Todo]: ...
    async def list_notes(self, run_id: str, active_only: bool) -> Sequence[Note]: ...
    async def list_context_snapshots(self, run_id: str) -> Sequence[ContextSnapshot]: ...
    async def register_skill(self, input: RegisterSkillInput) -> Skill: ...
    async def load_skill(self, input: LoadSkillInput) -> SkillLoad: ...
    async def unload_skill(self, load_id: str) -> SkillLoad: ...
    async def create_todo(self, input: CreateTodoInput) -> Todo: ...
    async def update_todo(self, todo_id: str, input: UpdateTodoInput) -> Todo: ...
    async def record_note(self, input: RecordNoteInput) -> Note: ...
    async def archive_note(self, note_id: str) -> Note: ...
    async def compress_context(
        self, run_id: str, flow_id: str, agent_instance_id: str | None
    ) -> ContextSnapshot: ...


class AuditGraphQLPort(Protocol):
    async def list_approvals(self, run_id: str) -> Sequence[Approval]: ...

    async def resolve_approval(
        self,
        run_id: str,
        request_id: str,
        approved: bool,
        reason: str | None,
    ) -> Approval: ...

    async def list_runtime_events(
        self,
        run_id: str,
        after_sequence: int,
    ) -> Sequence[RuntimeEvent]: ...

    async def get_report(self, run_id: str) -> Report | None: ...

    async def list_artifacts(self, run_id: str) -> Sequence[Artifact]: ...

    async def list_evidence(self, run_id: str) -> Sequence[Evidence]: ...

    async def list_findings(self, run_id: str) -> Sequence[Finding]: ...


class AnalyticsGraphQLPort(Protocol):
    async def usage_by_flow(self, flow_id: str) -> UsageStats: ...

    async def usage_by_agent(self, flow_id: str) -> Any: ...

    async def usage_by_model(self, flow_id: str | None) -> Any: ...

    async def usage_by_tool(self, flow_id: str | None) -> Any: ...


class EventGraphQLPort(Protocol):
    def subscribe(
        self,
        topic: str,
        **filters: Any,
    ) -> AsyncIterator[Any]: ...


@dataclass(frozen=True, slots=True)
class GraphQLBackend:
    flows: FlowGraphQLPort
    agents: AgentGraphQLPort
    tools: ToolGraphQLPort
    mcp: MCPGraphQLPort
    prompts: PromptGraphQLPort
    audit: AuditGraphQLPort
    analytics: AnalyticsGraphQLPort
    events: EventGraphQLPort
    long_term: LongTermGraphQLPort | None = None
