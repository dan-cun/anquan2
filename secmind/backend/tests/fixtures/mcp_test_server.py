from __future__ import annotations

import asyncio
import os

from mcp.server.fastmcp import FastMCP

server = FastMCP(
    "secmind-mcp-test",
    log_level="ERROR",
    host="127.0.0.1",
    port=int(os.getenv("MCP_TEST_PORT", "8000")),
)


@server.tool(description="Echo a message through the MCP transport")
def echo(message: str) -> dict[str, str]:
    return {"echo": message, "transport": "stdio"}


@server.tool(description="Wait before returning a result")
async def pause(delay_seconds: float) -> str:
    await asyncio.sleep(delay_seconds)
    return "finished"


@server.tool(description="Return a protocol-level tool failure")
def fail() -> str:
    raise ValueError("intentional MCP failure")


@server.resource(
    "memory://secmind/status",
    name="runtime-status",
    description="Current test runtime status",
    mime_type="text/plain",
)
def runtime_status() -> str:
    return "ready"


@server.prompt(name="review", description="Build a security review request")
def review_prompt(topic: str) -> str:
    return f"Review the security posture of {topic}."


if __name__ == "__main__":
    server.run(transport=os.getenv("MCP_TEST_TRANSPORT", "stdio"))
