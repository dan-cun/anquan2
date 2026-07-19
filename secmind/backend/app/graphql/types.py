from __future__ import annotations

from datetime import datetime

import strawberry
from strawberry.scalars import JSON

from app.schemas.agents import (
    AgentMessageKind as AgentMessageKindModel,
)
from app.schemas.agents import AgentRole as AgentRoleModel
from app.schemas.agents import AgentStatus as AgentStatusModel
from app.schemas.mcp import MCPServerStatus as MCPServerStatusModel
from app.schemas.mcp import MCPTransport as MCPTransportModel
from app.schemas.prompts import PromptMessageRole as PromptMessageRoleModel
from app.schemas.prompts import PromptVersionStatus as PromptVersionStatusModel
from app.schemas.tools import CapabilityKind as CapabilityKindModel
from app.schemas.tools import ToolExecutionStatus as ToolExecutionStatusModel
from app.schemas.tools import ToolOrigin as ToolOriginModel

AgentRole = strawberry.enum(AgentRoleModel, name="AgentRole")
AgentStatus = strawberry.enum(AgentStatusModel, name="AgentStatus")
AgentMessageKind = strawberry.enum(AgentMessageKindModel, name="AgentMessageKind")
MCPTransport = strawberry.enum(MCPTransportModel, name="MCPTransport")
MCPServerStatus = strawberry.enum(MCPServerStatusModel, name="MCPServerStatus")
CapabilityKind = strawberry.enum(CapabilityKindModel, name="CapabilityKind")
ToolOrigin = strawberry.enum(ToolOriginModel, name="ToolOrigin")
ToolExecutionStatus = strawberry.enum(ToolExecutionStatusModel, name="ToolExecutionStatus")
PromptMessageRole = strawberry.enum(PromptMessageRoleModel, name="PromptMessageRole")
PromptVersionStatus = strawberry.enum(PromptVersionStatusModel, name="PromptVersionStatus")


@strawberry.type
class Subtask:
    id: strawberry.ID
    task_id: strawberry.ID
    title: str
    description: str
    status: str
    agent_role: AgentRole | None = None
    result: JSON | None = None
    created_at: datetime = strawberry.field(default_factory=datetime.now)
    updated_at: datetime = strawberry.field(default_factory=datetime.now)


@strawberry.type
class Task:
    id: strawberry.ID
    flow_id: strawberry.ID
    title: str
    objective: str
    status: str
    result: JSON | None = None
    created_at: datetime = strawberry.field(default_factory=datetime.now)
    updated_at: datetime = strawberry.field(default_factory=datetime.now)
    subtasks: list[Subtask] = strawberry.field(default_factory=list)


@strawberry.type
class Flow:
    id: strawberry.ID
    title: str
    status: str
    created_at: datetime
    updated_at: datetime
    tasks: list[Task] = strawberry.field(default_factory=list)


@strawberry.type
class Assistant:
    id: strawberry.ID
    flow_id: strawberry.ID
    title: str
    status: str
    use_agents: bool
    model_provider: str | None = None
    created_at: datetime = strawberry.field(default_factory=datetime.now)
    updated_at: datetime = strawberry.field(default_factory=datetime.now)


@strawberry.type
class AgentDescriptor:
    role: AgentRole
    display_name: str
    description: str
    prompt_key: str
    model_profile: str
    capabilities: list[str]
    enabled: bool
    metadata: JSON


@strawberry.type
class AgentInstance:
    instance_id: strawberry.ID
    run_id: strawberry.ID
    flow_id: strawberry.ID
    role: AgentRole
    status: AgentStatus
    task_id: strawberry.ID | None = None
    parent_instance_id: strawberry.ID | None = None
    prompt_version_id: strawberry.ID | None = None
    model_profile: str = "worker"
    started_at: datetime | None = None
    updated_at: datetime = strawberry.field(default_factory=datetime.now)
    completed_at: datetime | None = None
    metadata: JSON = strawberry.field(default_factory=dict)


@strawberry.type
class AgentTask:
    task_id: strawberry.ID
    run_id: strawberry.ID
    flow_id: strawberry.ID
    objective: str
    subtask_id: strawberry.ID | None = None
    parent_agent_instance_id: strawberry.ID | None = None
    context_refs: list[str] = strawberry.field(default_factory=list)
    constraints: list[str] = strawberry.field(default_factory=list)
    expected_outputs: list[str] = strawberry.field(default_factory=list)
    metadata: JSON = strawberry.field(default_factory=dict)


@strawberry.type
class AgentDelegation:
    delegation_id: strawberry.ID
    run_id: strawberry.ID
    flow_id: strawberry.ID
    from_agent_instance_id: strawberry.ID
    to_role: AgentRole
    task: AgentTask
    status: AgentStatus
    to_agent_instance_id: strawberry.ID | None = None
    result_summary: str | None = None
    created_at: datetime = strawberry.field(default_factory=datetime.now)
    completed_at: datetime | None = None


@strawberry.type
class AgentMessage:
    message_id: strawberry.ID
    run_id: strawberry.ID
    flow_id: strawberry.ID
    from_agent_instance_id: strawberry.ID
    kind: AgentMessageKind
    summary: str
    timestamp: datetime
    to_agent_instance_id: strawberry.ID | None = None
    to_role: AgentRole | None = None
    payload_ref: str | None = None
    sequence: int | None = None
    metadata: JSON = strawberry.field(default_factory=dict)


@strawberry.type
class AgentResult:
    agent_instance_id: strawberry.ID
    task_id: strawberry.ID
    status: AgentStatus
    summary: str
    data: JSON
    artifact_refs: list[str]
    evidence_ids: list[strawberry.ID]
    finding_ids: list[strawberry.ID]
    completed_at: datetime
    error_code: str | None = None
    error_message: str | None = None
    started_at: datetime | None = None


@strawberry.type
class MCPCapability:
    capability_id: strawberry.ID
    server_id: strawberry.ID
    kind: CapabilityKind
    name: str
    description: str
    input_schema: JSON
    metadata: JSON


@strawberry.type
class MCPServer:
    server_id: strawberry.ID
    name: str
    transport: MCPTransport
    enabled: bool
    status: MCPServerStatus
    metadata: JSON
    capabilities: list[MCPCapability]
    protocol_version: str | None = None
    error_message: str | None = None


@strawberry.type
class UnifiedTool:
    tool_id: strawberry.ID
    name: str
    description: str
    origin: ToolOrigin
    input_schema: JSON
    output_schema: JSON
    annotations: JSON
    server_id: strawberry.ID | None = None


@strawberry.type
class ToolCall:
    invocation_id: strawberry.ID
    run_id: strawberry.ID
    flow_id: strawberry.ID
    agent_instance_id: strawberry.ID
    tool_id: strawberry.ID
    arguments: JSON
    status: ToolExecutionStatus
    text: str
    data: JSON
    artifact_refs: list[str]
    evidence_ids: list[strawberry.ID]
    duration_ms: int
    task_id: strawberry.ID | None = None
    subtask_id: strawberry.ID | None = None
    error_code: str | None = None
    error_message: str | None = None


@strawberry.type
class MessageEntry:
    entry_id: strawberry.ID
    chain_id: strawberry.ID
    role: str
    content: str
    sequence: int
    created_at: datetime
    content_data: JSON | None = None
    tool_call_id: strawberry.ID | None = None


@strawberry.type
class MessageChain:
    chain_id: strawberry.ID
    run_id: strawberry.ID
    flow_id: strawberry.ID
    agent_instance_id: strawberry.ID
    agent_role: AgentRole
    model_provider: str
    model: str
    created_at: datetime
    updated_at: datetime
    entries: list[MessageEntry]
    task_id: strawberry.ID | None = None
    subtask_id: strawberry.ID | None = None
    summary: str | None = None


@strawberry.type
class PromptVersion:
    version_id: strawberry.ID
    prompt_key: strawberry.ID
    version: int
    content: str
    variables: list[str]
    checksum: str
    status: PromptVersionStatus
    source: str
    created_at: datetime
    activated_at: datetime | None = None


@strawberry.type
class PromptTemplate:
    prompt_key: strawberry.ID
    name: str
    category: str
    message_role: PromptMessageRole
    variables: list[str]
    metadata: JSON
    versions: list[PromptVersion]
    agent_role: AgentRole | None = None
    source_path: str | None = None
    active_version_id: strawberry.ID | None = None


@strawberry.type
class Approval:
    request_id: strawberry.ID
    run_id: strawberry.ID
    step_id: strawberry.ID
    status: str
    reason: str
    requested_at: datetime
    decision: str | None = None
    actor: str | None = None
    resolved_at: datetime | None = None


@strawberry.type
class RuntimeEvent:
    event_id: strawberry.ID
    run_id: strawberry.ID
    sequence: int
    event_type: str
    actor: str
    payload: JSON
    timestamp: datetime
    prev_hash: str
    hash: str


@strawberry.type
class Report:
    run_id: strawberry.ID
    status: str
    executive_summary: str
    findings: JSON
    evidence: JSON
    limitations: list[str]
    generated_at: datetime


@strawberry.type
class Artifact:
    artifact_id: strawberry.ID
    run_id: strawberry.ID
    flow_id: strawberry.ID
    name: str
    media_type: str
    uri: str
    metadata: JSON
    created_at: datetime
    sha256: str | None = None
    size_bytes: int | None = None


@strawberry.type
class Evidence:
    evidence_id: strawberry.ID
    run_id: strawberry.ID
    source: str
    summary: str
    metadata: JSON
    created_at: datetime
    artifact_ref: strawberry.ID | None = None
    sha256: str | None = None


@strawberry.type
class Finding:
    finding_id: strawberry.ID
    run_id: strawberry.ID
    rule_id: str
    severity: str
    confidence: str
    path: str
    title: str
    description: str
    evidence_ids: list[strawberry.ID]
    raw: JSON
    created_at: datetime
    subtask_id: strawberry.ID | None = None
    line: int | None = None
    remediation: str | None = None


@strawberry.type
class UsageStats:
    request_count: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost: float | None = None


@strawberry.input
class CreateFlowInput:
    input: str
    title: str | None = strawberry.UNSET
    model_provider: str | None = strawberry.UNSET
    resource_ids: list[strawberry.ID] | None = strawberry.UNSET


@strawberry.input
class SubmitFlowInput:
    content: str
    metadata: JSON | None = strawberry.UNSET


@strawberry.input
class CreateAssistantInput:
    input: str
    use_agents: bool | None = True
    title: str | None = strawberry.UNSET
    model_provider: str | None = strawberry.UNSET
    resource_ids: list[strawberry.ID] | None = strawberry.UNSET


@strawberry.input
class RegisterMCPServerInput:
    server_id: strawberry.ID
    name: str
    transport: MCPTransport
    command: str | None = strawberry.UNSET
    args: list[str] | None = strawberry.UNSET
    cwd: str | None = strawberry.UNSET
    env_refs: JSON | None = strawberry.UNSET
    url: str | None = strawberry.UNSET
    header_refs: JSON | None = strawberry.UNSET
    enabled: bool | None = True
    metadata: JSON | None = strawberry.UNSET


@strawberry.input
class UpdateMCPServerInput:
    name: str | None = strawberry.UNSET
    command: str | None = strawberry.UNSET
    args: list[str] | None = strawberry.UNSET
    cwd: str | None = strawberry.UNSET
    env_refs: JSON | None = strawberry.UNSET
    url: str | None = strawberry.UNSET
    header_refs: JSON | None = strawberry.UNSET
    enabled: bool | None = strawberry.UNSET
    metadata: JSON | None = strawberry.UNSET


@strawberry.input
class CreatePromptVersionInput:
    prompt_key: strawberry.ID
    content: str
    source: str | None = "graphql"


@strawberry.input
class DelegateAgentInput:
    flow_id: strawberry.ID
    run_id: strawberry.ID
    from_agent_instance_id: strawberry.ID
    to_role: AgentRole
    objective: str
    subtask_id: strawberry.ID | None = strawberry.UNSET
    context_refs: list[str] | None = strawberry.UNSET
    constraints: list[str] | None = strawberry.UNSET
    expected_outputs: list[str] | None = strawberry.UNSET
    metadata: JSON | None = strawberry.UNSET


@strawberry.input
class RevisePlanInput:
    run_id: strawberry.ID
    task_id: strawberry.ID
    revision: JSON
    reason: str
