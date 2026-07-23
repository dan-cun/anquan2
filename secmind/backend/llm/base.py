from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.provider import ProviderMessage, ProviderToolCall


class LLMMessage(ProviderMessage):
    """Internal extension of the validated provider message with audit-only metadata."""

    metadata: dict[str, Any] = Field(default_factory=dict)


class EmptyContentReason(StrEnum):
    LENGTH = "length"
    LENGTH_REASONING_ONLY = "length_reasoning_only"
    REASONING_ONLY = "reasoning_only"
    TOOL_CALLS_ONLY = "tool_calls_only"
    PROVIDER_EMPTY = "provider_empty"


class LLMUsage(BaseModel):
    """Normalized public usage fields while retaining provider-specific counters."""

    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    reasoning_tokens: int = Field(default=0, ge=0)
    cache_read_tokens: int = Field(default=0, ge=0)
    raw: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_provider(cls, value: Any) -> LLMUsage:
        raw = value.copy() if isinstance(value, dict) else {}
        completion_details = raw.get("completion_tokens_details")
        prompt_details = raw.get("prompt_tokens_details")
        completion_details = completion_details if isinstance(completion_details, dict) else {}
        prompt_details = prompt_details if isinstance(prompt_details, dict) else {}
        return cls(
            prompt_tokens=_nonnegative_int(raw.get("prompt_tokens")),
            completion_tokens=_nonnegative_int(raw.get("completion_tokens")),
            total_tokens=_nonnegative_int(raw.get("total_tokens")),
            reasoning_tokens=_nonnegative_int(completion_details.get("reasoning_tokens")),
            cache_read_tokens=_nonnegative_int(
                raw.get("prompt_cache_hit_tokens", prompt_details.get("cached_tokens"))
            ),
            raw=raw,
        )


class LLMResponse(BaseModel):
    content: str
    model: str
    provider: str
    tool_calls: list[ProviderToolCall] = Field(default_factory=list)
    finish_reason: str | None = None
    usage: LLMUsage = Field(default_factory=LLMUsage)
    empty_content_reason: EmptyContentReason | None = None
    raw: dict[str, Any] = Field(default_factory=dict)

    @property
    def should_retry_without_thinking(self) -> bool:
        return self.empty_content_reason in {
            EmptyContentReason.LENGTH_REASONING_ONLY,
            EmptyContentReason.REASONING_ONLY,
        }


class ProviderHTTPError(RuntimeError):
    def __init__(self, status_code: int, diagnostics: dict[str, Any]) -> None:
        super().__init__(f"Model provider returned HTTP {status_code}")
        self.status_code = status_code
        self.diagnostics = diagnostics


class LLMProvider(ABC):
    name: str

    def metadata(self) -> dict[str, Any]:
        return {"name": self.name, "configured": True}

    @abstractmethod
    async def complete(self, messages: list[LLMMessage], **kwargs: Any) -> LLMResponse:
        """Return a model response for the supplied messages."""


class NullLLMProvider(LLMProvider):
    name = "null"

    def __init__(self, reason: str = "LLM provider is not configured.") -> None:
        self.reason = reason

    def metadata(self) -> dict[str, Any]:
        return {"name": self.name, "configured": False, "reason": self.reason}

    async def complete(self, messages: list[LLMMessage], **kwargs: Any) -> LLMResponse:
        return LLMResponse(
            content=self.reason,
            model="none",
            provider=self.name,
            raw={"message_count": len(messages), "kwargs": kwargs},
        )


def empty_content_reason(
    *,
    content: str,
    finish_reason: str | None,
    reasoning_content: str,
    has_tool_calls: bool,
) -> EmptyContentReason | None:
    if content.strip():
        return None
    if has_tool_calls:
        return EmptyContentReason.TOOL_CALLS_ONLY
    if finish_reason == "length" and reasoning_content.strip():
        return EmptyContentReason.LENGTH_REASONING_ONLY
    if finish_reason == "length":
        return EmptyContentReason.LENGTH
    if reasoning_content.strip():
        return EmptyContentReason.REASONING_ONLY
    return EmptyContentReason.PROVIDER_EMPTY


def _nonnegative_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)
