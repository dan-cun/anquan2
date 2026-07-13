from __future__ import annotations

from tools.base import ToolContext, ToolPlugin, ToolResult


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolPlugin] = {}

    def register(self, tool: ToolPlugin) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolPlugin | None:
        return self._tools.get(name)

    def list_metadata(self) -> list[dict[str, object]]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameter_schema(),
            }
            for tool in sorted(self._tools.values(), key=lambda item: item.name)
        ]

    async def invoke(
        self,
        name: str,
        *,
        context: ToolContext,
        arguments: dict[str, object],
    ) -> ToolResult:
        tool = self.get(name)
        if tool is None:
            raise KeyError(f"tool not registered: {name}")
        return await tool.run(context, dict(arguments))

