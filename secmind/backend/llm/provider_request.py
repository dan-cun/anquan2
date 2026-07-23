from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.provider import ProviderMessage, validate_provider_message_sequence


class ProviderRequest(BaseModel):
    """Explicit public boundary for OpenAI-compatible request payloads."""

    model_config = ConfigDict(extra="forbid")

    model: str
    messages: list[ProviderMessage]
    temperature: float | None = None
    stream: Literal[False] = False
    max_tokens: int | None = Field(default=None, ge=1)
    max_completion_tokens: int | None = Field(default=None, ge=1)
    top_p: float | None = None
    frequency_penalty: float | None = None
    presence_penalty: float | None = None
    stop: str | list[str] | None = None
    seed: int | None = None
    n: int | None = Field(default=None, ge=1)
    response_format: dict[str, Any] | None = None
    thinking: dict[str, Any] | None = None
    reasoning_effort: str | None = None
    tools: list[dict[str, Any]] | None = None
    tool_choice: str | dict[str, Any] | None = None
    parallel_tool_calls: bool | None = None
    user: str | None = None
    logit_bias: dict[str, float] | None = None
    logprobs: bool | None = None
    top_logprobs: int | None = None
    stream_options: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_message_sequence(self) -> ProviderRequest:
        validate_provider_message_sequence(self.messages)
        return self

    def payload(self) -> dict[str, Any]:
        payload = self.model_dump(mode="json", exclude_none=True, exclude={"messages"})
        payload["messages"] = [message.provider_payload() for message in self.messages]
        return payload
