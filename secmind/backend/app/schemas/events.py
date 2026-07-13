from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


class WSMessage(BaseModel):
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    flow_id: str | None = None
    request_id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = Field(default_factory=utc_now)

    model_config = ConfigDict(extra="allow")

    @classmethod
    def event(
        cls,
        event_type: str,
        *,
        flow_id: str | None = None,
        payload: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> WSMessage:
        return cls(
            type=event_type,
            flow_id=flow_id,
            payload=payload or {},
            request_id=request_id or str(uuid4()),
        )
