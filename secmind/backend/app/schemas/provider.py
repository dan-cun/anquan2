from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

PROVIDER_PROTOCOL_VERSION = "1.0"
ProviderRole = Literal["system", "user", "assistant", "tool"]


class ProviderFunctionCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    arguments: str

    @model_validator(mode="after")
    def validate_arguments(self) -> ProviderFunctionCall:
        try:
            value = json.loads(self.arguments)
        except (TypeError, ValueError) as error:
            raise ValueError("function arguments must be valid JSON") from error
        if not isinstance(value, dict):
            raise ValueError("function arguments must encode a JSON object")
        return self


class ProviderToolCall(BaseModel):
    """One native function call emitted by a model provider."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    type: Literal["function"] = "function"
    function: ProviderFunctionCall

    @classmethod
    def create(cls, *, call_id: str, name: str, arguments: dict[str, Any]) -> ProviderToolCall:
        return cls(
            id=call_id,
            function=ProviderFunctionCall(
                name=name,
                arguments=json.dumps(arguments, ensure_ascii=False, separators=(",", ":")),
            ),
        )


class ProviderToolResult(BaseModel):
    """Result for a real provider tool call, identified by its provider-issued call ID."""

    model_config = ConfigDict(extra="forbid")

    tool_call_id: str = Field(min_length=1)
    content: str
    name: str | None = Field(default=None, min_length=1)

    def as_message(self) -> ProviderMessage:
        return ProviderMessage(
            role="tool",
            content=self.content,
            tool_call_id=self.tool_call_id,
            name=self.name,
        )


class ProviderMessage(BaseModel):
    """Provider-facing message with role-specific structural validation."""

    model_config = ConfigDict(extra="forbid")

    role: ProviderRole
    content: str | None = None
    tool_calls: list[ProviderToolCall] = Field(default_factory=list)
    tool_call_id: str | None = Field(default=None, min_length=1)
    name: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_role_fields(self) -> ProviderMessage:
        if self.role == "assistant":
            if self.tool_call_id is not None or self.name is not None:
                raise ValueError("assistant messages cannot contain tool result fields")
            if self.content is None and not self.tool_calls:
                raise ValueError("assistant messages require content or tool_calls")
            call_ids = [item.id for item in self.tool_calls]
            if len(call_ids) != len(set(call_ids)):
                raise ValueError("assistant tool call IDs must be unique")
            return self
        if self.role == "tool":
            if self.tool_call_id is None:
                raise ValueError("tool messages require tool_call_id")
            if self.content is None:
                raise ValueError("tool messages require content")
            if self.tool_calls:
                raise ValueError("tool messages cannot create tool_calls")
            return self
        if self.content is None:
            raise ValueError(f"{self.role} messages require content")
        if self.tool_calls or self.tool_call_id is not None or self.name is not None:
            raise ValueError(f"{self.role} messages cannot contain tool call fields")
        return self

    def provider_payload(self) -> dict[str, Any]:
        payload = self.model_dump(mode="json", exclude_none=True, exclude={"tool_calls"})
        if self.tool_calls:
            payload["tool_calls"] = [item.model_dump(mode="json") for item in self.tool_calls]
        return payload


def validate_provider_message_sequence(
    messages: list[ProviderMessage],
    *,
    require_resolved: bool = True,
) -> None:
    """Reject orphaned, duplicated, out-of-order, and unresolved native tool calls."""

    pending: set[str] = set()
    seen_call_ids: set[str] = set()
    for index, message in enumerate(messages):
        if pending and message.role != "tool":
            missing = ", ".join(sorted(pending))
            raise ValueError(
                f"message {index} must resolve pending tool call ID(s) before role={message.role}: "
                f"{missing}"
            )
        if message.role == "assistant" and message.tool_calls:
            call_ids = {item.id for item in message.tool_calls}
            duplicated = call_ids & seen_call_ids
            if duplicated:
                raise ValueError(
                    "tool call IDs cannot be reused: " + ", ".join(sorted(duplicated))
                )
            pending.update(call_ids)
            seen_call_ids.update(call_ids)
            continue
        if message.role == "tool":
            call_id = message.tool_call_id
            if call_id not in pending:
                raise ValueError(
                    f"tool message {index} references unknown or already resolved tool_call_id: "
                    f"{call_id}"
                )
            pending.remove(call_id)
    if require_resolved and pending:
        raise ValueError("unresolved tool call ID(s): " + ", ".join(sorted(pending)))


class AgentFinalReport(BaseModel):
    """Serializable public outcome of one Agent execution."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = PROVIDER_PROTOCOL_VERSION
    report_type: Literal["agent_final_report"] = "agent_final_report"
    agent_instance_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    status: str = Field(min_length=1)
    summary: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    artifact_refs: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    finding_ids: list[str] = Field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None


class AgentObservation(BaseModel):
    """Internal observation; it is never serialized as a provider tool message."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = PROVIDER_PROTOCOL_VERSION
    observation_type: Literal["agent_observation"] = "agent_observation"
    observation_id: str = Field(default_factory=lambda: str(uuid4()))
    source: Literal["agent", "tool", "policy", "runtime"]
    source_id: str = Field(min_length=1)
    summary: str
    status: str = Field(min_length=1)
    data: dict[str, Any] = Field(default_factory=dict)
    artifact_refs: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    finding_ids: list[str] = Field(default_factory=list)
    final_report: AgentFinalReport | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def as_provider_message(self) -> ProviderMessage:
        return ProviderMessage(role="user", content=self.model_dump_json())
