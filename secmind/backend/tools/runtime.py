from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from agents.guardrail import Guardrail, GuardrailDecision
from app.schemas.runtime import RuntimeToolContext, RuntimeToolResult, ToolManifest


class RuntimeToolError(RuntimeError):
    pass


class RuntimeTool(ABC):
    manifest: ToolManifest

    @abstractmethod
    async def invoke(self, args: dict[str, Any], context: RuntimeToolContext) -> RuntimeToolResult:
        raise NotImplementedError


class RuntimeToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, RuntimeTool] = {}

    def register(self, tool: RuntimeTool) -> None:
        if tool.manifest.name in self._tools:
            raise RuntimeToolError(f"Duplicate tool: {tool.manifest.name}")
        self._tools[tool.manifest.name] = tool

    def get(self, name: str) -> RuntimeTool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise RuntimeToolError(f"Unknown tool: {name}") from exc

    def manifests(self) -> list[ToolManifest]:
        return [tool.manifest for tool in self._tools.values()]


class RuntimeToolBroker:
    def __init__(self, registry: RuntimeToolRegistry, guardrail: Guardrail) -> None:
        self.registry = registry
        self.guardrail = guardrail

    def assess(self, name: str, args: dict[str, Any], autonomy_policy: str) -> GuardrailDecision:
        return self.guardrail.evaluate(self.registry.get(name).manifest, args, autonomy_policy)

    async def invoke(
        self,
        name: str,
        args: dict[str, Any],
        context: RuntimeToolContext,
    ) -> RuntimeToolResult:
        return await self.registry.get(name).invoke(args, context)
