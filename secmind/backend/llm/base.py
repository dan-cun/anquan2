from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field


class LLMMessage(BaseModel):
    role: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class LLMResponse(BaseModel):
    content: str
    model: str
    provider: str
    raw: dict[str, Any] = Field(default_factory=dict)


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
