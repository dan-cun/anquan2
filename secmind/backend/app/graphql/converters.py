from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from app.graphql import types
from app.schemas import agents as agent_models
from app.schemas import prompts as prompt_models
from app.schemas.flow import Flow as FlowModel
from app.schemas.mcp import MCPCapability as MCPCapabilityModel
from app.schemas.mcp import MCPServerSnapshot
from app.schemas.runtime import (
    AgentReport,
    ApprovalRequest,
    InputArtifact,
    LedgerEvent,
)
from app.schemas.runtime import (
    Evidence as EvidenceModel,
)
from app.schemas.runtime import (
    Finding as FindingModel,
)
from app.schemas.tools import UnifiedToolDefinition, UnifiedToolInvocation, UnifiedToolResult


def flow(model: FlowModel, *, tasks: Sequence[types.Task] = ()) -> types.Flow:
    return types.Flow(
        id=model.id,
        title=model.title,
        status=model.status.value,
        created_at=model.created_at,
        updated_at=model.updated_at,
        tasks=list(tasks),
    )


def agent_descriptor(model: agent_models.AgentDescriptor) -> types.AgentDescriptor:
    return types.AgentDescriptor(
        role=model.role,
        display_name=model.display_name,
        description=model.description,
        prompt_key=model.prompt_key,
        model_profile=model.model_profile,
        capabilities=model.capabilities,
        enabled=model.enabled,
        metadata=model.metadata,
    )


def agent_instance(model: agent_models.AgentInstance) -> types.AgentInstance:
    return types.AgentInstance(
        instance_id=model.instance_id,
        run_id=model.run_id,
        flow_id=model.flow_id,
        role=model.role,
        status=model.status,
        task_id=model.task_id,
        parent_instance_id=model.parent_instance_id,
        prompt_version_id=model.prompt_version_id,
        model_profile=model.model_profile,
        started_at=model.started_at,
        updated_at=model.updated_at,
        completed_at=model.completed_at,
        metadata=model.metadata,
    )


def agent_task(model: agent_models.AgentTask) -> types.AgentTask:
    return types.AgentTask(
        task_id=model.task_id,
        run_id=model.run_id,
        flow_id=model.flow_id,
        subtask_id=model.subtask_id,
        parent_agent_instance_id=model.parent_agent_instance_id,
        objective=model.objective,
        context_refs=model.context_refs,
        constraints=model.constraints,
        expected_outputs=model.expected_outputs,
        metadata=model.metadata,
    )


def agent_delegation(model: agent_models.AgentDelegation) -> types.AgentDelegation:
    return types.AgentDelegation(
        delegation_id=model.delegation_id,
        run_id=model.run_id,
        flow_id=model.flow_id,
        from_agent_instance_id=model.from_agent_instance_id,
        to_role=model.to_role,
        to_agent_instance_id=model.to_agent_instance_id,
        task=agent_task(model.task),
        status=model.status,
        result_summary=model.result_summary,
        created_at=model.created_at,
        completed_at=model.completed_at,
    )


def agent_message(model: agent_models.AgentMessage) -> types.AgentMessage:
    return types.AgentMessage(
        message_id=model.message_id,
        run_id=model.run_id,
        flow_id=model.flow_id,
        from_agent_instance_id=model.from_agent_instance_id,
        to_agent_instance_id=model.to_agent_instance_id,
        to_role=model.to_role,
        kind=model.kind,
        summary=model.summary,
        payload_ref=model.payload_ref,
        sequence=model.sequence,
        timestamp=model.timestamp,
        metadata=model.metadata,
    )


def agent_result(model: agent_models.AgentResult) -> types.AgentResult:
    return types.AgentResult(
        agent_instance_id=model.agent_instance_id,
        task_id=model.task_id,
        status=model.status,
        summary=model.summary,
        data=model.data,
        artifact_refs=model.artifact_refs,
        evidence_ids=model.evidence_ids,
        finding_ids=model.finding_ids,
        error_code=model.error_code,
        error_message=model.error_message,
        started_at=model.started_at,
        completed_at=model.completed_at,
    )


def mcp_capability(model: MCPCapabilityModel) -> types.MCPCapability:
    return types.MCPCapability(
        capability_id=model.capability_id,
        server_id=model.server_id,
        kind=model.kind,
        name=model.name,
        description=model.description,
        input_schema=model.input_schema,
        metadata=model.metadata,
    )


def mcp_server(model: MCPServerSnapshot) -> types.MCPServer:
    return types.MCPServer(
        server_id=model.config.server_id,
        name=model.config.name,
        transport=model.config.transport,
        enabled=model.config.enabled,
        status=model.status,
        protocol_version=model.protocol_version,
        error_message=model.error_message,
        metadata=model.config.metadata,
        capabilities=[mcp_capability(item) for item in model.capabilities],
    )


def unified_tool(model: UnifiedToolDefinition) -> types.UnifiedTool:
    return types.UnifiedTool(
        tool_id=model.tool_id,
        name=model.name,
        description=model.description,
        origin=model.origin,
        input_schema=model.input_schema,
        output_schema=model.output_schema,
        server_id=model.server_id,
        annotations=model.annotations,
    )


def tool_call(
    invocation: UnifiedToolInvocation,
    result: UnifiedToolResult,
) -> types.ToolCall:
    if invocation.invocation_id != result.invocation_id:
        raise ValueError("tool invocation/result identifiers do not match")
    return types.ToolCall(
        invocation_id=invocation.invocation_id,
        run_id=invocation.run_id,
        flow_id=invocation.flow_id,
        agent_instance_id=invocation.agent_instance_id,
        task_id=invocation.task_id,
        subtask_id=invocation.subtask_id,
        tool_id=invocation.tool_id,
        arguments=invocation.arguments,
        status=result.status,
        text=result.text,
        data=result.data,
        artifact_refs=result.artifact_refs,
        evidence_ids=result.evidence_ids,
        error_code=result.error_code,
        error_message=result.error_message,
        duration_ms=result.duration_ms,
    )


def prompt_version(model: prompt_models.PromptVersionRecord) -> types.PromptVersion:
    return types.PromptVersion(
        version_id=model.version_id,
        prompt_key=model.prompt_key,
        version=model.version,
        content=model.content,
        variables=model.variables,
        checksum=model.checksum,
        status=model.status,
        source=model.source,
        created_at=model.created_at,
        activated_at=model.activated_at,
    )


def prompt_template(
    model: prompt_models.PromptTemplateRecord,
    *,
    versions: Sequence[prompt_models.PromptVersionRecord] = (),
) -> types.PromptTemplate:
    return types.PromptTemplate(
        prompt_key=model.prompt_key,
        name=model.name,
        category=model.category,
        message_role=model.message_role,
        agent_role=model.agent_role,
        source_path=model.source_path,
        variables=model.variables,
        active_version_id=model.active_version_id,
        metadata=model.metadata,
        versions=[prompt_version(item) for item in versions],
    )


def runtime_event(model: LedgerEvent) -> types.RuntimeEvent:
    return types.RuntimeEvent(
        event_id=model.event_id,
        run_id=model.run_id,
        sequence=model.sequence,
        event_type=model.event_type,
        actor=model.actor,
        payload=model.payload,
        timestamp=model.timestamp,
        prev_hash=model.prev_hash,
        hash=model.hash,
    )


def report(model: AgentReport) -> types.Report:
    return types.Report(
        run_id=model.run_id,
        status=model.status.value,
        executive_summary=model.executive_summary,
        findings=[item.model_dump(mode="json") for item in model.findings],
        evidence=[item.model_dump(mode="json") for item in model.evidence],
        limitations=model.limitations,
        generated_at=model.generated_at,
    )


def approval(
    model: ApprovalRequest,
    *,
    status: str = "requested",
    decision: str | None = None,
    actor: str | None = None,
    requested_at: datetime | None = None,
    resolved_at: datetime | None = None,
) -> types.Approval:
    return types.Approval(
        request_id=model.request_id,
        run_id=model.run_id,
        step_id=model.step_id,
        status=status,
        reason=model.reason,
        decision=decision,
        actor=actor,
        requested_at=requested_at or datetime.now(UTC),
        resolved_at=resolved_at,
    )


def artifact(
    model: InputArtifact,
    *,
    run_id: str,
    flow_id: str,
    uri: str,
    created_at: datetime,
    metadata: dict[str, object] | None = None,
) -> types.Artifact:
    return types.Artifact(
        artifact_id=model.artifact_id,
        run_id=run_id,
        flow_id=flow_id,
        name=model.original_name,
        media_type=model.media_type,
        uri=uri,
        sha256=model.sha256,
        size_bytes=model.size_bytes,
        metadata=metadata or {},
        created_at=created_at,
    )


def evidence(
    model: EvidenceModel,
    *,
    run_id: str,
    created_at: datetime,
) -> types.Evidence:
    return types.Evidence(
        evidence_id=model.evidence_id,
        run_id=run_id,
        source=model.source,
        summary=model.summary,
        artifact_ref=model.artifact_ref,
        sha256=model.sha256,
        metadata=model.metadata,
        created_at=created_at,
    )


def finding(
    model: FindingModel,
    *,
    run_id: str,
    subtask_id: str | None,
    created_at: datetime,
) -> types.Finding:
    return types.Finding(
        finding_id=model.finding_id,
        run_id=run_id,
        subtask_id=subtask_id,
        rule_id=model.rule_id,
        severity=model.severity,
        confidence=model.confidence,
        path=model.path,
        line=model.line,
        title=model.title,
        description=model.description,
        remediation=model.remediation,
        evidence_ids=model.evidence_ids,
        raw=model.raw,
        created_at=created_at,
    )
