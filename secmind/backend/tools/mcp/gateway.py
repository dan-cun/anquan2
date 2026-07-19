from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.schemas.tools import (
    ToolExecutionStatus,
    ToolOrigin,
    UnifiedToolDefinition,
    UnifiedToolInvocation,
    UnifiedToolResult,
)
from tools.mcp.manager import MCPManager, MCPToolNotFoundError

NativeToolHandler = Callable[[UnifiedToolInvocation], Awaitable[UnifiedToolResult]]


class UnifiedToolGateway:
    """Presents native and MCP tools through the canonical unified contract."""

    def __init__(self, mcp_manager: MCPManager) -> None:
        self.mcp_manager = mcp_manager
        self._native_definitions: dict[str, UnifiedToolDefinition] = {}
        self._native_handlers: dict[str, NativeToolHandler] = {}

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
        handler = self._native_handlers.get(invocation.tool_id)
        if handler is not None:
            return await handler(invocation)
        try:
            return await self.mcp_manager.call_tool(invocation)
        except MCPToolNotFoundError:
            return UnifiedToolResult(
                invocation_id=invocation.invocation_id,
                tool_id=invocation.tool_id,
                status=ToolExecutionStatus.FAILED,
                error_code="unknown_tool",
                error_message=f"Unknown unified tool: {invocation.tool_id}",
                duration_ms=0,
            )
