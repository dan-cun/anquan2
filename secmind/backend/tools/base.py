from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field


class ToolContext(BaseModel):
    flow_id: str
    task_id: str | None = None
    subtask_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    ok: bool
    output: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolPlugin(ABC):
    name: str
    description: str

    @abstractmethod
    def parameter_schema(self) -> dict[str, Any]:
        """Return a JSON-schema-like parameter contract for LLM/tool routing."""

    @abstractmethod
    async def run(self, context: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        """Execute a tool call."""

