from __future__ import annotations

from datetime import UTC, datetime
from enum import IntEnum, StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

LONG_TERM_CONTRACT_VERSION = "1.0"


def utc_now() -> datetime:
    return datetime.now(UTC)


class TodoStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TodoPriority(IntEnum):
    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4


class NoteKind(StrEnum):
    FACT = "fact"
    HYPOTHESIS = "hypothesis"
    CONSTRAINT = "constraint"
    DECISION = "decision"
    OBSERVATION = "observation"
    ERROR = "error"


class NoteStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class SkillDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LONG_TERM_CONTRACT_VERSION
    skill_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,119}$")
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4_000)
    version: str = Field(default="1.0", min_length=1, max_length=80)
    content: str = Field(min_length=1, max_length=200_000)
    checksum: str = Field(min_length=8, max_length=128)
    tags: list[str] = Field(default_factory=list)
    compatible_roles: list[str] = Field(default_factory=list)
    source: str = Field(default="operator", max_length=200)
    enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class SkillLoad(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LONG_TERM_CONTRACT_VERSION
    load_id: str = Field(default_factory=lambda: str(uuid4()))
    skill_id: str
    run_id: str
    flow_id: str
    agent_instance_id: str | None = None
    reason: str = Field(default="", max_length=4_000)
    loaded_at: datetime = Field(default_factory=utc_now)
    unloaded_at: datetime | None = None


class TodoItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LONG_TERM_CONTRACT_VERSION
    todo_id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str
    flow_id: str
    title: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=8_000)
    status: TodoStatus = TodoStatus.PENDING
    priority: TodoPriority = TodoPriority.NORMAL
    position: int = Field(default=0, ge=0)
    task_id: str | None = None
    agent_instance_id: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None


class NoteRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LONG_TERM_CONTRACT_VERSION
    note_id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str
    flow_id: str
    kind: NoteKind
    content: str = Field(min_length=1, max_length=50_000)
    status: NoteStatus = NoteStatus.ACTIVE
    agent_instance_id: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class StructuredContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tools: list[dict[str, Any]] = Field(default_factory=list)
    endpoints: list[dict[str, Any]] = Field(default_factory=list)
    findings: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)
    todos: list[dict[str, Any]] = Field(default_factory=list)
    notes: list[dict[str, Any]] = Field(default_factory=list)
    skills: list[dict[str, Any]] = Field(default_factory=list)


class ContextSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LONG_TERM_CONTRACT_VERSION
    snapshot_id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str
    flow_id: str
    source_from_sequence: int = Field(ge=0)
    source_to_sequence: int = Field(ge=0)
    estimated_tokens_before: int = Field(ge=0)
    estimated_tokens_after: int = Field(ge=0)
    narrative_summary: str = Field(max_length=20_000)
    structured: StructuredContext = Field(default_factory=StructuredContext)
    agent_instance_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
