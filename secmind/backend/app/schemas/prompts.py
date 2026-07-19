from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.agents import AgentRole

PROMPT_CONTRACT_VERSION = "1.0"


def utc_now() -> datetime:
    return datetime.now(UTC)


class PromptMessageRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    TEMPLATE = "template"
    MEMORY = "memory"


class PromptVersionStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class PromptTemplateRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = PROMPT_CONTRACT_VERSION
    prompt_key: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=200)
    category: str
    message_role: PromptMessageRole
    agent_role: AgentRole | None = None
    source_path: str | None = None
    variables: list[str] = Field(default_factory=list)
    active_version_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PromptVersionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = PROMPT_CONTRACT_VERSION
    version_id: str = Field(default_factory=lambda: str(uuid4()))
    prompt_key: str
    version: int = Field(ge=1)
    content: str = Field(min_length=1)
    variables: list[str] = Field(default_factory=list)
    checksum: str = Field(min_length=1)
    status: PromptVersionStatus = PromptVersionStatus.DRAFT
    source: str = "native"
    created_at: datetime = Field(default_factory=utc_now)
    activated_at: datetime | None = None


class PromptWorkbookRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt_key: str
    modified_prompt: str = Field(min_length=1)
    modification_status: str = "未修改"
    modification_notes: str = ""
