from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StrictBool

WS_PROTOCOL_VERSION = "1.0"


class WSClientMessageType(StrEnum):
    USER_MESSAGE = "client.user_message"
    APPROVAL_RESPONSE = "client.approval_response"
    PING = "client.ping"


class WSServerMessageType(StrEnum):
    CONNECTED = "server.connected"
    STATUS = "server.status"
    LEDGER_ENTRY = "server.ledger_entry"
    INTERRUPT = "server.interrupt"
    DONE = "server.done"
    ERROR = "server.error"
    PONG = "server.pong"


class ClientUserMessagePayload(BaseModel):
    content: str = Field(min_length=1, max_length=10_000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ClientApprovalResponsePayload(BaseModel):
    approval_id: str = Field(min_length=1)
    approved: StrictBool
    reason: str | None = None


def utc_now() -> datetime:
    return datetime.now(UTC)


class WSMessage(BaseModel):
    schema_version: str = WS_PROTOCOL_VERSION
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    flow_id: str | None = None
    request_id: str = Field(default_factory=lambda: str(uuid4()))
    sequence: int | None = Field(default=None, ge=1)
    timestamp: datetime = Field(default_factory=utc_now)

    model_config = ConfigDict(extra="allow")

    @classmethod
    def event(
        cls,
        event_type: str | StrEnum,
        *,
        flow_id: str | None = None,
        payload: dict[str, Any] | None = None,
        request_id: str | None = None,
        sequence: int | None = None,
    ) -> WSMessage:
        return cls(
            type=str(event_type),
            flow_id=flow_id,
            payload=payload or {},
            request_id=request_id or str(uuid4()),
            sequence=sequence,
        )
