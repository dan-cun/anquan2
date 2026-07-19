from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.tools import CapabilityKind

MCP_CONTRACT_VERSION = "1.0"


class MCPTransport(StrEnum):
    STDIO = "stdio"
    STREAMABLE_HTTP = "streamable_http"
    SSE = "sse"


class MCPServerStatus(StrEnum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DEGRADED = "degraded"
    FAILED = "failed"


class MCPServerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = MCP_CONTRACT_VERSION
    server_id: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=120)
    transport: MCPTransport
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    cwd: str | None = None
    env_refs: dict[str, str] = Field(default_factory=dict)
    url: str | None = None
    header_refs: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True
    connect_timeout_seconds: float | None = Field(default=None, gt=0)
    call_timeout_seconds: float | None = Field(default=None, gt=0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_transport_target(self) -> MCPServerConfig:
        if self.transport == MCPTransport.STDIO and not self.command:
            raise ValueError("stdio transport requires command")
        if self.transport != MCPTransport.STDIO and not self.url:
            raise ValueError("HTTP transports require url")
        return self


class MCPCapability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = MCP_CONTRACT_VERSION
    capability_id: str = Field(min_length=1, max_length=320)
    server_id: str
    kind: CapabilityKind
    name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MCPServerSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = MCP_CONTRACT_VERSION
    config: MCPServerConfig
    status: MCPServerStatus = MCPServerStatus.DISCONNECTED
    protocol_version: str | None = None
    capabilities: list[MCPCapability] = Field(default_factory=list)
    error_message: str | None = None
