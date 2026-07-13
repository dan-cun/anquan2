from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.events import WSMessage


class FlowStatus(StrEnum):
    created = "created"
    running = "running"
    waiting = "waiting"
    finished = "finished"
    failed = "failed"


class Flow(BaseModel):
    id: str
    title: str
    status: FlowStatus
    created_at: datetime
    updated_at: datetime


class FlowCreateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    initial_input: str | None = Field(default=None, max_length=20000)


class FlowMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=20000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ApprovalRequest(BaseModel):
    approval_id: str
    approved: bool
    reason: str | None = None


class FlowRunResponse(BaseModel):
    flow_id: str
    events: list[WSMessage]

