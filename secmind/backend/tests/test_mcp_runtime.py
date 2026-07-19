from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from typing import Any

import pytest

from app.schemas.mcp import MCPServerConfig, MCPServerStatus, MCPTransport
from app.schemas.tools import (
    CapabilityKind,
    ToolExecutionStatus,
    ToolOrigin,
    UnifiedToolDefinition,
    UnifiedToolInvocation,
    UnifiedToolResult,
)
from tools.mcp import MCPConfigError, MCPManager, MCPManagerError, UnifiedToolGateway
from tools.mcp.config import load_mcp_server_configs
from tools.mcp.manager import _paginated
from tools.mcp.transports import MCPTransportError, build_transport, resolve_environment_refs

FIXTURE_SERVER = Path(__file__).parent / "fixtures" / "mcp_test_server.py"


def unused_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


@asynccontextmanager
async def running_http_server(transport: str) -> AsyncIterator[int]:
    port = unused_tcp_port()
    environment = {
        **os.environ,
        "MCP_TEST_TRANSPORT": transport,
        "MCP_TEST_PORT": str(port),
    }
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        str(FIXTURE_SERVER),
        env=environment,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        for _ in range(100):
            if process.returncode is not None:
                raise RuntimeError(f"MCP HTTP fixture exited with {process.returncode}")
            try:
                reader, writer = await asyncio.open_connection("127.0.0.1", port)
            except OSError:
                await asyncio.sleep(0.05)
            else:
                writer.close()
                await writer.wait_closed()
                break
        else:
            raise TimeoutError("MCP HTTP fixture did not start")
        yield port
    finally:
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=3)
            except TimeoutError:
                process.kill()
                await process.wait()


def stdio_config(**overrides: Any) -> MCPServerConfig:
    values: dict[str, Any] = {
        "server_id": "test-server",
        "name": "Test MCP Server",
        "transport": MCPTransport.STDIO,
        "command": sys.executable,
        "args": [str(FIXTURE_SERVER)],
    }
    values.update(overrides)
    return MCPServerConfig(**values)


def invocation(tool_id: str, **overrides: Any) -> UnifiedToolInvocation:
    values: dict[str, Any] = {
        "run_id": "run-1",
        "flow_id": "flow-1",
        "agent_instance_id": "agent-1",
        "tool_id": tool_id,
        "arguments": {},
    }
    values.update(overrides)
    return UnifiedToolInvocation(**values)


def test_load_mcp_server_configs(tmp_path: Path) -> None:
    config_path = tmp_path / "mcp.json"
    config_path.write_text(
        json.dumps({"servers": [stdio_config().model_dump(mode="json")]}),
        encoding="utf-8",
    )

    configs = load_mcp_server_configs(config_path)

    assert configs == [stdio_config()]


def test_load_mcp_server_configs_rejects_duplicates(tmp_path: Path) -> None:
    config_path = tmp_path / "mcp.json"
    item = stdio_config().model_dump(mode="json")
    config_path.write_text(json.dumps([item, item]), encoding="utf-8")

    with pytest.raises(MCPConfigError, match="Duplicate MCP server_id"):
        load_mcp_server_configs(config_path)


def test_environment_reference_resolution() -> None:
    assert resolve_environment_refs(
        {"AUTH_TOKEN": "SOURCE_TOKEN"},
        {"SOURCE_TOKEN": "secret-value"},
    ) == {"AUTH_TOKEN": "secret-value"}
    with pytest.raises(MCPTransportError, match="MISSING_TOKEN"):
        resolve_environment_refs({"AUTH_TOKEN": "MISSING_TOKEN"}, {})


def test_builds_all_supported_transports(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def capture(kind: str):
        def factory(*args: Any, **kwargs: Any) -> object:
            calls.append((kind, args, kwargs))
            return object()

        return factory

    monkeypatch.setattr("tools.mcp.transports.stdio_client", capture("stdio"))
    monkeypatch.setattr(
        "tools.mcp.transports._streamable_http_transport",
        capture("streamable_http"),
    )
    monkeypatch.setattr("tools.mcp.transports.sse_client", capture("sse"))

    build_transport(
        stdio_config(env_refs={"TOKEN": "SOURCE_TOKEN"}),
        connect_timeout_seconds=2,
        call_timeout_seconds=3,
        environ={"SOURCE_TOKEN": "resolved", "UNRELATED_SECRET": "do-not-inherit"},
    )
    build_transport(
        MCPServerConfig(
            server_id="http",
            name="HTTP",
            transport=MCPTransport.STREAMABLE_HTTP,
            url="http://127.0.0.1:9000/mcp",
            header_refs={"Authorization": "AUTH_HEADER"},
        ),
        connect_timeout_seconds=2,
        call_timeout_seconds=3,
        environ={"AUTH_HEADER": "Bearer token"},
    )
    build_transport(
        MCPServerConfig(
            server_id="sse",
            name="SSE",
            transport=MCPTransport.SSE,
            url="http://127.0.0.1:9000/sse",
        ),
        connect_timeout_seconds=2,
        call_timeout_seconds=3,
        environ={},
    )

    assert [item[0] for item in calls] == ["stdio", "streamable_http", "sse"]
    stdio_parameters = calls[0][1][0]
    assert stdio_parameters.env == {"TOKEN": "resolved"}
    assert calls[1][2]["headers"] == {"Authorization": "Bearer token"}
    assert calls[1][2]["connect_timeout_seconds"] == 2
    assert calls[2][2]["sse_read_timeout"] == 3


@pytest.mark.asyncio
async def test_paginated_discovery_rejects_repeated_cursor() -> None:
    class Page:
        tools: list[Any] = []
        nextCursor = "repeated"

    async def list_tools(cursor: str | None) -> Page:
        return Page()

    with pytest.raises(MCPManagerError, match="repeated cursor"):
        await _paginated(list_tools, "tools")


@pytest.mark.asyncio
async def test_stdio_connection_discovery_and_invocation_chain() -> None:
    events: list[tuple[str, dict[str, Any]]] = []

    async def publish(event_type: str, payload: dict[str, Any]) -> None:
        events.append((event_type, payload))

    manager = MCPManager(
        [stdio_config()],
        connect_timeout_seconds=10,
        call_timeout_seconds=10,
        refresh_interval_seconds=3600,
        publisher=publish,
    )
    await manager.startup()
    try:
        snapshot = manager.snapshots()[0]
        assert snapshot.status == MCPServerStatus.CONNECTED
        assert snapshot.protocol_version
        assert {item.kind for item in snapshot.capabilities} == {
            CapabilityKind.TOOL,
            CapabilityKind.RESOURCE,
            CapabilityKind.PROMPT,
        }

        definitions = manager.tool_definitions()
        echo_definition = next(item for item in definitions if item.name == "echo")
        result = await manager.call_tool(
            invocation(echo_definition.tool_id, arguments={"message": "hello MCP"})
        )

        assert result.status == ToolExecutionStatus.COMPLETED
        assert result.data["structured_content"] == {
            "echo": "hello MCP",
            "transport": "stdio",
        }
        assert "hello MCP" in result.text

        resource = next(
            item for item in manager.capabilities() if item.kind == CapabilityKind.RESOURCE
        )
        resource_result = await manager.read_resource(resource.capability_id)
        assert resource_result["contents"][0]["text"] == "ready"

        prompt = next(item for item in manager.capabilities() if item.kind == CapabilityKind.PROMPT)
        prompt_result = await manager.get_prompt(
            prompt.capability_id,
            {"topic": "MCP gateway"},
        )
        assert "MCP gateway" in prompt_result["messages"][0]["content"]["text"]

        event_types = [item[0] for item in events]
        assert "mcp.connected" in event_types
        assert "mcp.capabilities_updated" in event_types
        assert "mcp.call_started" in event_types
        assert "mcp.call_completed" in event_types
    finally:
        await manager.shutdown()

    assert manager.snapshots()[0].status == MCPServerStatus.DISCONNECTED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("transport", "server_transport", "path"),
    [
        (MCPTransport.STREAMABLE_HTTP, "streamable-http", "/mcp"),
        (MCPTransport.SSE, "sse", "/sse"),
    ],
)
async def test_http_transport_invocation_chain(
    transport: MCPTransport,
    server_transport: str,
    path: str,
) -> None:
    async with running_http_server(server_transport) as port:
        manager = MCPManager(
            [
                MCPServerConfig(
                    server_id=f"test-{transport.value}",
                    name=f"Test {transport.value}",
                    transport=transport,
                    url=f"http://127.0.0.1:{port}{path}",
                )
            ],
            connect_timeout_seconds=10,
            call_timeout_seconds=10,
            refresh_interval_seconds=3600,
        )
        await manager.startup()
        try:
            assert manager.snapshots()[0].status == MCPServerStatus.CONNECTED
            echo_definition = next(
                item for item in manager.tool_definitions() if item.name == "echo"
            )
            result = await manager.call_tool(
                invocation(echo_definition.tool_id, arguments={"message": transport.value})
            )
            assert result.status == ToolExecutionStatus.COMPLETED
            assert result.data["structured_content"]["echo"] == transport.value
        finally:
            await manager.shutdown()


@pytest.mark.asyncio
async def test_tool_error_and_timeout_are_normalized() -> None:
    events: list[str] = []

    def publish(event_type: str, payload: dict[str, Any]) -> None:
        events.append(event_type)

    manager = MCPManager(
        [stdio_config()],
        connect_timeout_seconds=10,
        call_timeout_seconds=10,
        refresh_interval_seconds=3600,
        publisher=publish,
    )
    await manager.startup()
    try:
        definitions = {item.name: item for item in manager.tool_definitions()}
        failed = await manager.call_tool(invocation(definitions["fail"].tool_id))
        timed_out = await manager.call_tool(
            invocation(
                definitions["pause"].tool_id,
                arguments={"delay_seconds": 0.3},
                timeout_seconds=0.03,
            )
        )

        assert failed.status == ToolExecutionStatus.FAILED
        assert failed.error_code == "mcp_tool_error"
        assert "intentional MCP failure" in (failed.error_message or "")
        assert timed_out.status == ToolExecutionStatus.TIMED_OUT
        assert timed_out.error_code == "mcp_timeout"
        assert events.count("mcp.call_failed") == 2
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
async def test_caller_cancellation_stops_active_mcp_call() -> None:
    events: list[tuple[str, dict[str, Any]]] = []

    def publish(event_type: str, payload: dict[str, Any]) -> None:
        events.append((event_type, payload))

    manager = MCPManager(
        [stdio_config()],
        connect_timeout_seconds=10,
        call_timeout_seconds=30,
        refresh_interval_seconds=3600,
        publisher=publish,
    )
    await manager.startup()
    try:
        definitions = {item.name: item for item in manager.tool_definitions()}
        call = asyncio.create_task(
            manager.call_tool(
                invocation(
                    definitions["pause"].tool_id,
                    arguments={"delay_seconds": 10},
                )
            )
        )
        await asyncio.sleep(0.05)
        call.cancel()

        with pytest.raises(asyncio.CancelledError):
            await call

        worker = manager._workers["test-server"]
        async with asyncio.timeout(1):
            while worker._active:
                await asyncio.sleep(0)

        cancelled = [
            payload
            for event_type, payload in events
            if event_type == "mcp.call_failed" and payload["status"] == "cancelled"
        ]
        assert len(cancelled) == 1

        echo = await manager.call_tool(
            invocation(definitions["echo"].tool_id, arguments={"message": "after cancel"})
        )
        assert echo.status == ToolExecutionStatus.COMPLETED
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
async def test_event_publisher_failure_does_not_break_mcp_runtime() -> None:
    def publish(event_type: str, payload: dict[str, Any]) -> None:
        raise RuntimeError(f"publisher unavailable for {event_type}")

    manager = MCPManager(
        [stdio_config()],
        connect_timeout_seconds=10,
        call_timeout_seconds=10,
        refresh_interval_seconds=3600,
        publisher=publish,
    )
    await manager.startup()
    try:
        assert manager.snapshots()[0].status == MCPServerStatus.CONNECTED
        echo_definition = next(item for item in manager.tool_definitions() if item.name == "echo")
        result = await manager.call_tool(
            invocation(echo_definition.tool_id, arguments={"message": "publisher failure"})
        )
        assert result.status == ToolExecutionStatus.COMPLETED
        assert "publisher failure" in result.text
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
async def test_event_payloads_redact_secrets_and_url_queries() -> None:
    events: list[tuple[str, dict[str, Any]]] = []

    def publish(event_type: str, payload: dict[str, Any]) -> None:
        events.append((event_type, payload))

    manager = MCPManager(
        [stdio_config()],
        connect_timeout_seconds=10,
        call_timeout_seconds=10,
        refresh_interval_seconds=3600,
        publisher=publish,
    )
    await manager.startup()
    try:
        echo_definition = next(item for item in manager.tool_definitions() if item.name == "echo")
        await manager.call_tool(
            invocation(
                echo_definition.tool_id,
                arguments={
                    "message": "https://example.test/mcp?token=top-secret",
                    "token": "top-secret",
                },
            )
        )

        started = next(
            payload for event_type, payload in events if event_type == "mcp.call_started"
        )
        assert started["arguments"]["token"] == "[REDACTED]"
        assert started["arguments"]["message"] == "https://example.test/mcp?[REDACTED]"
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
async def test_concurrent_shutdown_is_idempotent() -> None:
    manager = MCPManager(
        [stdio_config()],
        connect_timeout_seconds=10,
        call_timeout_seconds=10,
        refresh_interval_seconds=3600,
    )
    await manager.startup()

    worker = manager._workers["test-server"]
    async with asyncio.timeout(3):
        await asyncio.gather(worker.stop(), worker.stop())

    assert worker.snapshot.status == MCPServerStatus.DISCONNECTED


@pytest.mark.asyncio
async def test_server_disconnect_returns_cancelled_tool_result() -> None:
    manager = MCPManager(
        [stdio_config()],
        connect_timeout_seconds=10,
        call_timeout_seconds=30,
        refresh_interval_seconds=3600,
    )
    await manager.startup()
    definitions = {item.name: item for item in manager.tool_definitions()}
    call = asyncio.create_task(
        manager.call_tool(
            invocation(
                definitions["pause"].tool_id,
                arguments={"delay_seconds": 10},
            )
        )
    )
    await asyncio.sleep(0.05)

    await manager.disconnect("test-server")
    result = await call

    assert result.status == ToolExecutionStatus.CANCELLED
    assert result.error_code == "mcp_cancelled"


@pytest.mark.asyncio
async def test_close_failure_still_clears_connected_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_aclose = AsyncExitStack.aclose

    async def failing_aclose(stack: AsyncExitStack) -> None:
        await original_aclose(stack)
        raise RuntimeError("simulated close failure")

    monkeypatch.setattr(AsyncExitStack, "aclose", failing_aclose)
    manager = MCPManager(
        [stdio_config()],
        connect_timeout_seconds=10,
        call_timeout_seconds=10,
        refresh_interval_seconds=3600,
    )
    await manager.startup()

    await manager.disconnect("test-server")

    assert manager.snapshots()[0].status == MCPServerStatus.DISCONNECTED
    assert manager.tool_definitions() == []
    await manager.shutdown()


@pytest.mark.asyncio
async def test_unified_gateway_routes_native_and_mcp_tools() -> None:
    manager = MCPManager(
        [stdio_config()],
        connect_timeout_seconds=10,
        call_timeout_seconds=10,
        refresh_interval_seconds=3600,
    )
    await manager.startup()
    try:
        gateway = UnifiedToolGateway(manager)
        native_definition = UnifiedToolDefinition(
            tool_id="native:status",
            name="status",
            origin=ToolOrigin.NATIVE,
        )

        async def native_handler(call: UnifiedToolInvocation) -> UnifiedToolResult:
            return UnifiedToolResult(
                invocation_id=call.invocation_id,
                tool_id=call.tool_id,
                status=ToolExecutionStatus.COMPLETED,
                text="native ready",
            )

        gateway.register_native(native_definition, native_handler)
        echo_definition = next(item for item in gateway.definitions() if item.name == "echo")

        native_result = await gateway.invoke(invocation(native_definition.tool_id))
        mcp_result = await gateway.invoke(
            invocation(echo_definition.tool_id, arguments={"message": "gateway"})
        )
        missing_result = await gateway.invoke(invocation("missing:tool"))

        assert native_result.text == "native ready"
        assert mcp_result.status == ToolExecutionStatus.COMPLETED
        assert missing_result.error_code == "unknown_tool"
        assert {item.origin for item in gateway.definitions()} == {
            ToolOrigin.NATIVE,
            ToolOrigin.MCP,
        }
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
async def test_startup_keeps_failed_server_snapshot() -> None:
    manager = MCPManager(
        [stdio_config(command="definitely-not-a-real-command")],
        connect_timeout_seconds=1,
        call_timeout_seconds=1,
        refresh_interval_seconds=3600,
        environ={},
    )

    await manager.startup()
    try:
        snapshot = manager.snapshots()[0]
        assert snapshot.status == MCPServerStatus.FAILED
        assert snapshot.error_message
        assert manager.tool_definitions() == []
    finally:
        await manager.shutdown()
