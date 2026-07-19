from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

NATIVE_TOOL_CONTRACT_VERSION = "1.0"


class ToolOrigin(StrEnum):
    NATIVE = "native"
    MCP = "mcp"


class CapabilityKind(StrEnum):
    TOOL = "tool"
    RESOURCE = "resource"
    PROMPT = "prompt"


class ToolExecutionStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class UnifiedToolDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = NATIVE_TOOL_CONTRACT_VERSION
    tool_id: str = Field(min_length=1, max_length=240)
    name: str = Field(min_length=1, max_length=240)
    description: str = ""
    origin: ToolOrigin
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    server_id: str | None = None
    annotations: dict[str, Any] = Field(default_factory=dict)


class UnifiedToolInvocation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = NATIVE_TOOL_CONTRACT_VERSION
    invocation_id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str
    flow_id: str
    agent_instance_id: str
    tool_id: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    task_id: str | None = None
    subtask_id: str | None = None
    timeout_seconds: float | None = Field(default=None, gt=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class UnifiedToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = NATIVE_TOOL_CONTRACT_VERSION
    invocation_id: str
    tool_id: str
    status: ToolExecutionStatus
    text: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    artifact_refs: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None
    duration_ms: int = Field(default=0, ge=0)
