from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from typing import Any

from agents.guardrail import Guardrail, GuardrailDecision
from app.schemas.runtime import RuntimeToolContext, RuntimeToolResult, ToolManifest, ToolStatus
from tools.safety import (
    CircuitBreakerOpenError,
    CircuitBreakerRegistry,
    redact_tool_value,
    safe_error_message,
)


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
    def __init__(
        self,
        registry: RuntimeToolRegistry,
        guardrail: Guardrail,
        *,
        circuit_breakers: CircuitBreakerRegistry | None = None,
    ) -> None:
        self.registry = registry
        self.guardrail = guardrail
        self.circuit_breakers = circuit_breakers or CircuitBreakerRegistry()

    def assess(self, name: str, args: dict[str, Any], autonomy_policy: str) -> GuardrailDecision:
        return self.guardrail.evaluate(self.registry.get(name).manifest, args, autonomy_policy)

    async def invoke(
        self,
        name: str,
        args: dict[str, Any],
        context: RuntimeToolContext,
    ) -> RuntimeToolResult:
        started = time.perf_counter()
        tool = self.registry.get(name)
        circuit_key = f"runtime-tool:{name}"
        try:
            await self.circuit_breakers.acquire((circuit_key,))
        except CircuitBreakerOpenError as error:
            return RuntimeToolResult(
                status=ToolStatus.ERROR,
                error_code="TOOL_CIRCUIT_OPEN",
                error_message=safe_error_message(error),
            )

        try:
            async with asyncio.timeout(tool.manifest.timeout_seconds):
                result = await tool.invoke(args, context)
            result = self._safe_result(result, started)
        except TimeoutError:
            result = RuntimeToolResult(
                status=ToolStatus.TIMEOUT,
                duration_ms=_duration_ms(started),
                error_code="TOOL_TIMEOUT",
                error_message=(
                    f"Tool {name} exceeded {tool.manifest.timeout_seconds:g} seconds"
                ),
            )
        except asyncio.CancelledError:
            await self.circuit_breakers.record_cancelled((circuit_key,))
            raise
        except Exception as error:
            result = RuntimeToolResult(
                status=ToolStatus.ERROR,
                duration_ms=_duration_ms(started),
                error_code="TOOL_RUNTIME_ERROR",
                error_message=f"{type(error).__name__}: {safe_error_message(error)}",
            )

        if result.status == ToolStatus.SUCCESS:
            await self.circuit_breakers.record_success((circuit_key,))
        elif result.status in {ToolStatus.ERROR, ToolStatus.TIMEOUT}:
            await self.circuit_breakers.record_failure((circuit_key,))
        else:
            await self.circuit_breakers.record_cancelled((circuit_key,))
        return result

    @staticmethod
    def _safe_result(result: RuntimeToolResult, started: float) -> RuntimeToolResult:
        if not isinstance(result, RuntimeToolResult):
            raise TypeError("Runtime tool must return RuntimeToolResult")
        payload = redact_tool_value(result.model_dump(mode="json"))
        if not result.duration_ms:
            payload["duration_ms"] = _duration_ms(started)
        return RuntimeToolResult.model_validate(payload)


def _duration_ms(started: float) -> int:
    return max(0, round((time.perf_counter() - started) * 1_000))
