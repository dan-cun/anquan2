from __future__ import annotations

import asyncio
import inspect
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from app.schemas.runtime import CircuitState
from app.schemas.tools import (
    ToolExecutionStatus,
    ToolOrigin,
    UnifiedToolDefinition,
    UnifiedToolInvocation,
    UnifiedToolResult,
)
from tools.mcp.manager import MCPManager
from tools.safety import (
    CircuitBreakerOpenError,
    CircuitBreakerRegistry,
    CircuitTransition,
    ToolScopeGuard,
    redact_tool_value,
    safe_error_message,
)

NativeToolHandler = Callable[[UnifiedToolInvocation], Awaitable[UnifiedToolResult]]
GatewayEventPublisher = Callable[
    [str, UnifiedToolInvocation, dict[str, Any]],
    Awaitable[None] | None,
]
logger = logging.getLogger(__name__)


class UnifiedToolGateway:
    """Apply one safety and reliability boundary to native and MCP tools."""

    def __init__(
        self,
        mcp_manager: MCPManager,
        *,
        default_timeout_seconds: float = 300.0,
        scope_guard: ToolScopeGuard | None = None,
        circuit_breakers: CircuitBreakerRegistry | None = None,
        event_publisher: GatewayEventPublisher | None = None,
    ) -> None:
        if default_timeout_seconds <= 0:
            raise ValueError("default_timeout_seconds must be positive")
        self.mcp_manager = mcp_manager
        self.default_timeout_seconds = default_timeout_seconds
        self.scope_guard = scope_guard or ToolScopeGuard()
        self.circuit_breakers = circuit_breakers or CircuitBreakerRegistry()
        self.event_publisher = event_publisher
        self._native_definitions: dict[str, UnifiedToolDefinition] = {}
        self._native_handlers: dict[str, NativeToolHandler] = {}

    def set_event_publisher(self, publisher: GatewayEventPublisher | None) -> None:
        self.event_publisher = publisher

    def register_native(
        self,
        definition: UnifiedToolDefinition,
        handler: NativeToolHandler,
    ) -> None:
        if definition.origin != ToolOrigin.NATIVE:
            raise ValueError("register_native requires a native tool definition")
        if definition.tool_id in self._native_definitions:
            raise ValueError(f"Duplicate unified tool_id: {definition.tool_id}")
        if any(item.tool_id == definition.tool_id for item in self.mcp_manager.tool_definitions()):
            raise ValueError(f"Duplicate unified tool_id: {definition.tool_id}")
        self._native_definitions[definition.tool_id] = definition
        self._native_handlers[definition.tool_id] = handler

    def definitions(self) -> list[UnifiedToolDefinition]:
        native = [item.model_copy(deep=True) for item in self._native_definitions.values()]
        return [*native, *self.mcp_manager.tool_definitions()]

    async def invoke(self, invocation: UnifiedToolInvocation) -> UnifiedToolResult:
        started = time.perf_counter()
        definition = self._definition(invocation.tool_id)
        if definition is None:
            return self._failure(
                invocation,
                started,
                error_code="unknown_tool",
                error_message=f"Unknown unified tool: {invocation.tool_id}",
            )

        scope = self.scope_guard.evaluate(definition, invocation)
        scope_payload = {
            "tool_id": invocation.tool_id,
            "allowed": scope.allowed,
            "reason": scope.reason,
            "policy_ids": list(scope.policy_ids),
        }
        await self._emit("guardrail.evaluated", invocation, scope_payload)
        if not scope.allowed:
            await self._emit("guardrail.denied", invocation, scope_payload)
            return self._failure(
                invocation,
                started,
                error_code="scope_violation",
                error_message=scope.reason,
            )

        circuit_keys = self._circuit_keys(definition)
        try:
            transitions = await self.circuit_breakers.acquire(circuit_keys)
        except CircuitBreakerOpenError as error:
            return self._failure(
                invocation,
                started,
                error_code="circuit_open",
                error_message=safe_error_message(error),
                data={"circuit_key": error.key, "retry_after_seconds": error.retry_after_seconds},
            )
        await self._emit_transitions(invocation, transitions)

        timeout = self._timeout_seconds(definition, invocation)
        try:
            async with asyncio.timeout(timeout):
                result = await self._dispatch(definition, invocation)
            result = self._safe_result(invocation, result, started)
        except TimeoutError:
            result = self._failure(
                invocation,
                started,
                status=ToolExecutionStatus.TIMED_OUT,
                error_code="tool_timeout",
                error_message=f"Tool call exceeded {timeout:g} seconds",
            )
        except asyncio.CancelledError:
            transitions = await self.circuit_breakers.record_cancelled(circuit_keys)
            await self._emit_transitions(invocation, transitions)
            raise
        except Exception as error:
            result = self._failure(
                invocation,
                started,
                error_code=(
                    "native_tool_error"
                    if definition.origin == ToolOrigin.NATIVE
                    else "mcp_gateway_error"
                ),
                error_message=f"{type(error).__name__}: {safe_error_message(error)}",
            )

        if result.status == ToolExecutionStatus.COMPLETED:
            transitions = await self.circuit_breakers.record_success(circuit_keys)
        elif result.status in {ToolExecutionStatus.FAILED, ToolExecutionStatus.TIMED_OUT}:
            transitions = await self.circuit_breakers.record_failure(
                self._failure_circuit_keys(definition, result, circuit_keys)
            )
        else:
            transitions = await self.circuit_breakers.record_cancelled(circuit_keys)
        await self._emit_transitions(invocation, transitions)
        return result

    async def _dispatch(
        self,
        definition: UnifiedToolDefinition,
        invocation: UnifiedToolInvocation,
    ) -> UnifiedToolResult:
        if definition.origin == ToolOrigin.NATIVE:
            return await self._native_handlers[definition.tool_id](invocation)
        return await self.mcp_manager.call_tool(invocation)

    def _definition(self, tool_id: str) -> UnifiedToolDefinition | None:
        native = self._native_definitions.get(tool_id)
        if native is not None:
            return native
        return next(
            (item for item in self.mcp_manager.tool_definitions() if item.tool_id == tool_id),
            None,
        )

    def _timeout_seconds(
        self,
        definition: UnifiedToolDefinition,
        invocation: UnifiedToolInvocation,
    ) -> float:
        if invocation.timeout_seconds is not None:
            return invocation.timeout_seconds
        annotated = definition.annotations.get("timeout_seconds")
        if (
            isinstance(annotated, (int, float))
            and not isinstance(annotated, bool)
            and annotated > 0
        ):
            return float(annotated)
        return self.default_timeout_seconds

    @staticmethod
    def _circuit_keys(definition: UnifiedToolDefinition) -> tuple[str, ...]:
        keys = [f"tool:{definition.tool_id}"]
        if definition.server_id:
            keys.append(f"server:{definition.server_id}")
        return tuple(keys)

    @staticmethod
    def _failure_circuit_keys(
        definition: UnifiedToolDefinition,
        result: UnifiedToolResult,
        circuit_keys: tuple[str, ...],
    ) -> tuple[str, ...]:
        if definition.origin != ToolOrigin.MCP or result.status == ToolExecutionStatus.TIMED_OUT:
            return circuit_keys
        if result.error_code in {"mcp_call_error", "mcp_gateway_error", "mcp_timeout"}:
            return circuit_keys
        return circuit_keys[:1]

    @staticmethod
    def _safe_result(
        invocation: UnifiedToolInvocation,
        result: UnifiedToolResult,
        started: float,
    ) -> UnifiedToolResult:
        if not isinstance(result, UnifiedToolResult):
            raise TypeError("Tool handler must return UnifiedToolResult")
        if result.invocation_id != invocation.invocation_id or result.tool_id != invocation.tool_id:
            raise ValueError("Tool result does not match its invocation")
        payload = result.model_dump(mode="json")
        payload["text"] = redact_tool_value(result.text)
        payload["data"] = redact_tool_value(result.data)
        payload["artifact_refs"] = redact_tool_value(result.artifact_refs)
        payload["error_message"] = (
            None if result.error_message is None else safe_error_message(result.error_message)
        )
        if not result.duration_ms:
            payload["duration_ms"] = _duration_ms(started)
        return UnifiedToolResult.model_validate(payload)

    @staticmethod
    def _failure(
        invocation: UnifiedToolInvocation,
        started: float,
        *,
        error_code: str,
        error_message: str,
        status: ToolExecutionStatus = ToolExecutionStatus.FAILED,
        data: dict[str, Any] | None = None,
    ) -> UnifiedToolResult:
        return UnifiedToolResult(
            invocation_id=invocation.invocation_id,
            tool_id=invocation.tool_id,
            status=status,
            data=redact_tool_value(data or {}),
            error_code=error_code,
            error_message=safe_error_message(error_message),
            duration_ms=_duration_ms(started),
        )

    async def _emit_transitions(
        self,
        invocation: UnifiedToolInvocation,
        transitions: list[CircuitTransition],
    ) -> None:
        event_by_state = {
            CircuitState.OPEN: "circuit.opened",
            CircuitState.HALF_OPEN: "circuit.half_opened",
            CircuitState.CLOSED: "circuit.closed",
        }
        for transition in transitions:
            await self._emit(
                event_by_state[transition.state],
                invocation,
                {
                    "circuit_key": transition.key,
                    "previous_state": transition.previous_state.value,
                    "state": transition.state.value,
                    "reason": transition.reason,
                    "tool_id": invocation.tool_id,
                },
            )

    async def _emit(
        self,
        event_type: str,
        invocation: UnifiedToolInvocation,
        payload: dict[str, Any],
    ) -> None:
        if self.event_publisher is None:
            return
        try:
            outcome = self.event_publisher(
                event_type,
                invocation,
                redact_tool_value(payload),
            )
            if inspect.isawaitable(outcome):
                await outcome
        except Exception:
            logger.exception("Unified tool event publisher failed for %s", event_type)


def _duration_ms(started: float) -> int:
    return max(0, round((time.perf_counter() - started) * 1_000))
