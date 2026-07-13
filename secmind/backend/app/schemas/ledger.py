from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class LedgerEntry(BaseModel):
    flow_id: str
    seq: int
    event_type: str
    actor: str
    payload: dict[str, Any] = Field(default_factory=dict)
    prev_hash: str
    hash: str
    created_at: datetime


class LedgerAnchor(BaseModel):
    flow_id: str
    seq: int
    hash: str
    created_at: datetime


class LedgerVerifyResponse(BaseModel):
    flow_id: str
    valid: bool
    entries_checked: int
    anchors_checked: int
    last_hash: str | None = None
    errors: list[str] = Field(default_factory=list)

