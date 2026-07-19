from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

NATIVE_AGENT_CONTRACT_VERSION = "1.0"


def utc_now() -> datetime:
    return datetime.now(UTC)


class AgentRole(StrEnum):
    PRIMARY_AGENT = "primary_agent"
    ASSISTANT = "assistant"
    GENERATOR = "generator"
    REFINER = "refiner"
    ADVISER = "adviser"
    REFLECTOR = "reflector"
    SEARCHER = "searcher"
    ENRICHER = "enricher"
    CODER = "coder"
    INSTALLER = "installer"
    PENTESTER = "pentester"
    MEMORIST = "memorist"
    REPORTER = "reporter"
    SUMMARIZER = "summarizer"
    TOOLCALL_FIXER = "toolcall_fixer"


class AgentStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentMessageKind(StrEnum):
    DELEGATION = "delegation"
    REQUEST = "request"
    RESPONSE = "response"
    STATUS = "status"
    REFLECTION = "reflection"
    ERROR = "error"


class AgentDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = NATIVE_AGENT_CONTRACT_VERSION
    role: AgentRole
    display_name: str = Field(min_length=1, max_length=120)
    description: str = ""
    prompt_key: str = Field(min_length=1, max_length=120)
    model_profile: str = Field(default="worker", min_length=1, max_length=120)
    capabilities: list[str] = Field(default_factory=list)
    enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = NATIVE_AGENT_CONTRACT_VERSION
    task_id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str = Field(min_length=1)
    flow_id: str = Field(min_length=1)
    subtask_id: str | None = None
    parent_agent_instance_id: str | None = None
    objective: str = Field(min_length=1, max_length=20_000)
    context_refs: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    expected_outputs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("objective")
    @classmethod
    def normalize_objective(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("objective must not be blank")
        return normalized


class AgentInstance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = NATIVE_AGENT_CONTRACT_VERSION
    instance_id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str
    flow_id: str
    role: AgentRole
    status: AgentStatus = AgentStatus.CREATED
    task_id: str | None = None
    parent_instance_id: str | None = None
    prompt_version_id: str | None = None
    model_profile: str = "worker"
    started_at: datetime | None = None
    updated_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentDelegation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = NATIVE_AGENT_CONTRACT_VERSION
    delegation_id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str
    flow_id: str
    from_agent_instance_id: str
    to_role: AgentRole
    task: AgentTask
    to_agent_instance_id: str | None = None
    status: AgentStatus = AgentStatus.CREATED
    result_summary: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None


class AgentMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = NATIVE_AGENT_CONTRACT_VERSION
    message_id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str
    flow_id: str
    from_agent_instance_id: str
    to_agent_instance_id: str | None = None
    to_role: AgentRole | None = None
    kind: AgentMessageKind
    summary: str = Field(min_length=1)
    payload_ref: str | None = None
    sequence: int | None = Field(default=None, ge=1)
    timestamp: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = NATIVE_AGENT_CONTRACT_VERSION
    agent_instance_id: str
    task_id: str
    status: AgentStatus
    summary: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    artifact_refs: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    finding_ids: list[str] = Field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime = Field(default_factory=utc_now)
