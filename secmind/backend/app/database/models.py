from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from ledger.runtime_store import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


JSON = sa.JSON
TZDateTime = sa.DateTime(timezone=True)


class FlowRow(Base):
    __tablename__ = "flows"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    title: Mapped[str] = mapped_column(sa.String(200))
    status: Mapped[str] = mapped_column(sa.String(30), index=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=utc_now)
    deleted_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True, index=True)


class TaskRow(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    flow_id: Mapped[str] = mapped_column(sa.ForeignKey("flows.id", ondelete="RESTRICT"), index=True)
    title: Mapped[str] = mapped_column(sa.String(200))
    objective: Mapped[str] = mapped_column(sa.Text)
    status: Mapped[str] = mapped_column(sa.String(30), index=True)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=utc_now)


class SubtaskRow(Base):
    __tablename__ = "subtasks"
    __table_args__ = (sa.UniqueConstraint("task_id", "position", name="uq_subtasks_task_position"),)

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(sa.ForeignKey("tasks.id", ondelete="RESTRICT"), index=True)
    title: Mapped[str] = mapped_column(sa.String(200))
    description: Mapped[str] = mapped_column(sa.Text)
    status: Mapped[str] = mapped_column(sa.String(30), index=True)
    agent_role: Mapped[str | None] = mapped_column(sa.String(100), nullable=True, index=True)
    position: Mapped[int] = mapped_column(sa.Integer)
    dependencies_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=utc_now)


class PromptRow(Base):
    __tablename__ = "prompts"

    prompt_key: Mapped[str] = mapped_column(sa.String(120), primary_key=True)
    name: Mapped[str] = mapped_column(sa.String(200))
    category: Mapped[str] = mapped_column(sa.String(120), index=True)
    message_role: Mapped[str] = mapped_column(sa.String(30), index=True)
    agent_role: Mapped[str | None] = mapped_column(sa.String(100), nullable=True, index=True)
    source_path: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    variables_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    active_version_id: Mapped[str | None] = mapped_column(sa.String(36), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class PromptVersionRow(Base):
    __tablename__ = "prompt_versions"
    __table_args__ = (
        sa.UniqueConstraint("prompt_key", "version", name="uq_prompt_versions_key_version"),
        sa.Index(
            "uq_prompt_versions_one_active",
            "prompt_key",
            unique=True,
            postgresql_where=sa.text("status = 'active'"),
            sqlite_where=sa.text("status = 'active'"),
        ),
    )

    version_id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    prompt_key: Mapped[str] = mapped_column(
        sa.ForeignKey("prompts.prompt_key", ondelete="RESTRICT"), index=True
    )
    version: Mapped[int] = mapped_column(sa.Integer)
    content: Mapped[str] = mapped_column(sa.Text)
    variables_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    checksum: Mapped[str] = mapped_column(sa.String(128), index=True)
    status: Mapped[str] = mapped_column(sa.String(30), index=True)
    source: Mapped[str] = mapped_column(sa.String(80))
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utc_now)
    activated_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)


class AgentInstanceRow(Base):
    __tablename__ = "agent_instances"

    instance_id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(sa.String(36), index=True)
    flow_id: Mapped[str] = mapped_column(sa.ForeignKey("flows.id", ondelete="RESTRICT"), index=True)
    role: Mapped[str] = mapped_column(sa.String(100), index=True)
    status: Mapped[str] = mapped_column(sa.String(30), index=True)
    task_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("tasks.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    parent_instance_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("agent_instances.instance_id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    prompt_version_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("prompt_versions.version_id", ondelete="RESTRICT"), nullable=True
    )
    model_profile: Mapped[str] = mapped_column(sa.String(120))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)


class AgentDelegationRow(Base):
    __tablename__ = "agent_delegations"

    delegation_id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(sa.String(36), index=True)
    flow_id: Mapped[str] = mapped_column(sa.ForeignKey("flows.id", ondelete="RESTRICT"), index=True)
    from_agent_instance_id: Mapped[str] = mapped_column(
        sa.ForeignKey("agent_instances.instance_id", ondelete="RESTRICT"), index=True
    )
    to_role: Mapped[str] = mapped_column(sa.String(100), index=True)
    to_agent_instance_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("agent_instances.instance_id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    agent_task_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(sa.String(30), index=True)
    result_summary: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)


class AgentMessageRow(Base):
    __tablename__ = "agent_messages"
    __table_args__ = (
        sa.UniqueConstraint("run_id", "sequence", name="uq_agent_messages_run_sequence"),
    )

    message_id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(sa.String(36), index=True)
    flow_id: Mapped[str] = mapped_column(sa.ForeignKey("flows.id", ondelete="RESTRICT"), index=True)
    from_agent_instance_id: Mapped[str] = mapped_column(
        sa.ForeignKey("agent_instances.instance_id", ondelete="RESTRICT"), index=True
    )
    to_agent_instance_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("agent_instances.instance_id", ondelete="RESTRICT"), nullable=True
    )
    to_role: Mapped[str | None] = mapped_column(sa.String(100), nullable=True)
    kind: Mapped[str] = mapped_column(sa.String(30), index=True)
    summary: Mapped[str] = mapped_column(sa.Text)
    payload_ref: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    sequence: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(TZDateTime, default=utc_now)


class MessageChainRow(Base):
    __tablename__ = "message_chains"

    chain_id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(sa.String(36), index=True)
    flow_id: Mapped[str] = mapped_column(sa.ForeignKey("flows.id", ondelete="RESTRICT"), index=True)
    task_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("tasks.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    subtask_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("subtasks.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    agent_instance_id: Mapped[str] = mapped_column(
        sa.ForeignKey("agent_instances.instance_id", ondelete="RESTRICT"),
        unique=True,
    )
    agent_role: Mapped[str] = mapped_column(sa.String(100), index=True)
    model_provider: Mapped[str] = mapped_column(sa.String(80), index=True)
    model: Mapped[str] = mapped_column(sa.String(120), index=True)
    summary: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=utc_now)


class MessageEntryRow(Base):
    __tablename__ = "message_entries"
    __table_args__ = (
        sa.UniqueConstraint("chain_id", "sequence", name="uq_message_entries_chain_sequence"),
    )

    entry_id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    chain_id: Mapped[str] = mapped_column(
        sa.ForeignKey("message_chains.chain_id", ondelete="RESTRICT"), index=True
    )
    role: Mapped[str] = mapped_column(sa.String(30), index=True)
    content: Mapped[str] = mapped_column(sa.Text)
    content_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    tool_call_id: Mapped[str | None] = mapped_column(sa.String(36), nullable=True, index=True)
    sequence: Mapped[int] = mapped_column(sa.Integer)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utc_now)


class MCPServerRow(Base):
    __tablename__ = "mcp_servers"

    server_id: Mapped[str] = mapped_column(sa.String(120), primary_key=True)
    name: Mapped[str] = mapped_column(sa.String(120), unique=True)
    transport: Mapped[str] = mapped_column(sa.String(30), index=True)
    command: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    args_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    cwd: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    env_refs_json: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    url: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    header_refs_json: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(sa.Boolean, default=True, index=True)
    status: Mapped[str] = mapped_column(sa.String(30), index=True)
    protocol_version: Mapped[str | None] = mapped_column(sa.String(50), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    last_error: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=utc_now)


class MCPCapabilityRow(Base):
    __tablename__ = "mcp_capabilities"
    __table_args__ = (
        sa.UniqueConstraint(
            "server_id", "kind", "name", name="uq_mcp_capabilities_server_kind_name"
        ),
    )

    capability_id: Mapped[str] = mapped_column(sa.String(320), primary_key=True)
    server_id: Mapped[str] = mapped_column(
        sa.ForeignKey("mcp_servers.server_id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(sa.String(30), index=True)
    name: Mapped[str] = mapped_column(sa.String(240), index=True)
    description: Mapped[str] = mapped_column(sa.Text, default="")
    input_schema_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    discovered_at: Mapped[datetime] = mapped_column(TZDateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=utc_now)


class ToolCallRow(Base):
    __tablename__ = "tool_calls"

    invocation_id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(sa.String(36), index=True)
    flow_id: Mapped[str] = mapped_column(sa.ForeignKey("flows.id", ondelete="RESTRICT"), index=True)
    task_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("tasks.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    subtask_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("subtasks.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    agent_instance_id: Mapped[str] = mapped_column(
        sa.ForeignKey("agent_instances.instance_id", ondelete="RESTRICT"), index=True
    )
    tool_id: Mapped[str] = mapped_column(sa.String(240), index=True)
    origin: Mapped[str] = mapped_column(sa.String(30), index=True)
    server_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("mcp_servers.server_id", ondelete="RESTRICT"), nullable=True, index=True
    )
    arguments_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(sa.String(30), index=True)
    text_result: Mapped[str] = mapped_column(sa.Text, default="")
    data_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    artifact_refs_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    evidence_ids_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    error_code: Mapped[str | None] = mapped_column(sa.String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    duration_ms: Mapped[int] = mapped_column(sa.Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)


class ArtifactRow(Base):
    __tablename__ = "artifacts"

    artifact_id: Mapped[str] = mapped_column(sa.String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(sa.String(36), index=True)
    flow_id: Mapped[str] = mapped_column(sa.ForeignKey("flows.id", ondelete="RESTRICT"), index=True)
    name: Mapped[str] = mapped_column(sa.String(255))
    media_type: Mapped[str] = mapped_column(sa.String(150))
    uri: Mapped[str] = mapped_column(sa.Text)
    sha256: Mapped[str | None] = mapped_column(sa.String(64), nullable=True, index=True)
    size_bytes: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utc_now)


class EvidenceRow(Base):
    __tablename__ = "evidence"

    evidence_id: Mapped[str] = mapped_column(sa.String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(sa.String(36), index=True)
    source: Mapped[str] = mapped_column(sa.String(200), index=True)
    summary: Mapped[str] = mapped_column(sa.Text)
    artifact_ref: Mapped[str | None] = mapped_column(
        sa.ForeignKey("artifacts.artifact_id", ondelete="RESTRICT"), nullable=True, index=True
    )
    sha256: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utc_now)


class FindingRow(Base):
    __tablename__ = "findings"

    finding_id: Mapped[str] = mapped_column(sa.String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(sa.String(36), index=True)
    subtask_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("subtasks.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    rule_id: Mapped[str] = mapped_column(sa.String(150), index=True)
    severity: Mapped[str] = mapped_column(sa.String(20), index=True)
    confidence: Mapped[str] = mapped_column(sa.String(20), index=True)
    path: Mapped[str] = mapped_column(sa.Text)
    line: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    title: Mapped[str] = mapped_column(sa.Text)
    description: Mapped[str] = mapped_column(sa.Text)
    remediation: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    evidence_ids_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    raw_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utc_now)


class ReportRow(Base):
    __tablename__ = "reports"
    __table_args__ = (sa.UniqueConstraint("run_id", "version", name="uq_reports_run_version"),)

    report_id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(sa.String(36), index=True)
    version: Mapped[int] = mapped_column(sa.Integer)
    status: Mapped[str] = mapped_column(sa.String(30), index=True)
    executive_summary: Mapped[str] = mapped_column(sa.Text)
    findings_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    evidence_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    limitations_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    generated_at: Mapped[datetime] = mapped_column(TZDateTime, default=utc_now)


class ApprovalRow(Base):
    __tablename__ = "approvals"

    request_id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(sa.String(36), index=True)
    step_id: Mapped[str] = mapped_column(sa.String(100), index=True)
    tool_name: Mapped[str | None] = mapped_column(sa.String(240), nullable=True)
    status: Mapped[str] = mapped_column(sa.String(30), index=True)
    reason: Mapped[str] = mapped_column(sa.Text)
    decision: Mapped[str | None] = mapped_column(sa.String(30), nullable=True)
    actor: Mapped[str | None] = mapped_column(sa.String(100), nullable=True)
    response_reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    request_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    response_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(TZDateTime, default=utc_now)
    resolved_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)


class LLMCallRow(Base):
    __tablename__ = "llm_calls"

    call_id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(sa.String(36), index=True)
    flow_id: Mapped[str] = mapped_column(sa.ForeignKey("flows.id", ondelete="RESTRICT"), index=True)
    agent_instance_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("agent_instances.instance_id", ondelete="RESTRICT"), nullable=True
    )
    chain_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("message_chains.chain_id", ondelete="RESTRICT"), nullable=True
    )
    provider: Mapped[str] = mapped_column(sa.String(80), index=True)
    model: Mapped[str] = mapped_column(sa.String(120), index=True)
    stage: Mapped[str] = mapped_column(sa.String(100), index=True)
    status: Mapped[str] = mapped_column(sa.String(30), index=True)
    request_ref: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    response_ref: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    duration_ms: Mapped[int] = mapped_column(sa.Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)


class LLMUsageRow(Base):
    __tablename__ = "llm_usage"

    usage_id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    call_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("llm_calls.call_id", ondelete="RESTRICT"), nullable=True, unique=True
    )
    run_id: Mapped[str] = mapped_column(sa.String(36), index=True)
    flow_id: Mapped[str] = mapped_column(sa.ForeignKey("flows.id", ondelete="RESTRICT"), index=True)
    agent_instance_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("agent_instances.instance_id", ondelete="RESTRICT"), nullable=True
    )
    agent_role: Mapped[str | None] = mapped_column(sa.String(100), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(sa.String(80), index=True)
    model: Mapped[str] = mapped_column(sa.String(120), index=True)
    prompt_tokens: Mapped[int] = mapped_column(sa.Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(sa.Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(sa.Integer, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(sa.Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(sa.Integer, default=0)
    estimated_cost: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    duration_ms: Mapped[int] = mapped_column(sa.Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utc_now)


class SkillRow(Base):
    __tablename__ = "skills"

    skill_id: Mapped[str] = mapped_column(sa.String(120), primary_key=True)
    name: Mapped[str] = mapped_column(sa.String(200))
    description: Mapped[str] = mapped_column(sa.Text, default="")
    version: Mapped[str] = mapped_column(sa.String(80))
    content: Mapped[str] = mapped_column(sa.Text)
    checksum: Mapped[str] = mapped_column(sa.String(128), index=True)
    tags_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    compatible_roles_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(sa.String(200), index=True)
    enabled: Mapped[bool] = mapped_column(sa.Boolean, default=True, index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=utc_now)


class SkillLoadRow(Base):
    __tablename__ = "skill_loads"

    load_id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    skill_id: Mapped[str] = mapped_column(
        sa.ForeignKey("skills.skill_id", ondelete="RESTRICT"), index=True
    )
    run_id: Mapped[str] = mapped_column(sa.String(36), index=True)
    flow_id: Mapped[str] = mapped_column(sa.ForeignKey("flows.id", ondelete="RESTRICT"), index=True)
    agent_instance_id: Mapped[str | None] = mapped_column(sa.String(36), nullable=True, index=True)
    reason: Mapped[str] = mapped_column(sa.Text, default="")
    loaded_at: Mapped[datetime] = mapped_column(TZDateTime, default=utc_now)
    unloaded_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True, index=True)


class TodoRow(Base):
    __tablename__ = "task_todos"

    todo_id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(sa.String(36), index=True)
    flow_id: Mapped[str] = mapped_column(sa.ForeignKey("flows.id", ondelete="RESTRICT"), index=True)
    task_id: Mapped[str | None] = mapped_column(sa.String(36), nullable=True, index=True)
    agent_instance_id: Mapped[str | None] = mapped_column(sa.String(36), nullable=True, index=True)
    title: Mapped[str] = mapped_column(sa.String(500))
    description: Mapped[str] = mapped_column(sa.Text, default="")
    status: Mapped[str] = mapped_column(sa.String(30), index=True)
    priority: Mapped[int] = mapped_column(sa.Integer, index=True)
    position: Mapped[int] = mapped_column(sa.Integer, default=0)
    depends_on_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    evidence_ids_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(TZDateTime, nullable=True)


class NoteRow(Base):
    __tablename__ = "task_notes"

    note_id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(sa.String(36), index=True)
    flow_id: Mapped[str] = mapped_column(sa.ForeignKey("flows.id", ondelete="RESTRICT"), index=True)
    agent_instance_id: Mapped[str | None] = mapped_column(sa.String(36), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(sa.String(30), index=True)
    content: Mapped[str] = mapped_column(sa.Text)
    status: Mapped[str] = mapped_column(sa.String(30), index=True)
    evidence_ids_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    tags_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=utc_now)


class ContextSnapshotRow(Base):
    __tablename__ = "context_snapshots"

    snapshot_id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(sa.String(36), index=True)
    flow_id: Mapped[str] = mapped_column(sa.ForeignKey("flows.id", ondelete="RESTRICT"), index=True)
    agent_instance_id: Mapped[str | None] = mapped_column(sa.String(36), nullable=True, index=True)
    source_from_sequence: Mapped[int] = mapped_column(sa.Integer)
    source_to_sequence: Mapped[int] = mapped_column(sa.Integer, index=True)
    estimated_tokens_before: Mapped[int] = mapped_column(sa.Integer)
    estimated_tokens_after: Mapped[int] = mapped_column(sa.Integer)
    narrative_summary: Mapped[str] = mapped_column(sa.Text)
    structured_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utc_now)
