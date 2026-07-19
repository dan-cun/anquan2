from __future__ import annotations

import asyncio
import hashlib
import inspect
import logging
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from mcp import ClientSession
from mcp import types as mcp_types
from pydantic import AnyUrl

from app.schemas.mcp import (
    MCPCapability,
    MCPServerConfig,
    MCPServerSnapshot,
    MCPServerStatus,
)
from app.schemas.tools import (
    CapabilityKind,
    ToolExecutionStatus,
    ToolOrigin,
    UnifiedToolDefinition,
    UnifiedToolInvocation,
    UnifiedToolResult,
)
from ledger.runtime_store import redact
from tools.mcp.transports import build_transport

EventPublisher = Callable[[str, dict[str, Any]], Awaitable[None] | None]
logger = logging.getLogger(__name__)
URL_PATTERN = re.compile(r"https?://[^\s'\"<>]+")


class MCPManagerError(RuntimeError):
    pass


class MCPConnectionError(MCPManagerError):
    pass


class MCPToolNotFoundError(MCPManagerError):
    pass


@dataclass(slots=True)
class _CapabilityTarget:
    kind: CapabilityKind
    name: str
    locator: str


@dataclass(slots=True)
class _Command:
    operation: str
    arguments: tuple[Any, ...]
    future: asyncio.Future[Any]


@dataclass(slots=True)
class _ServerWorker:
    config: MCPServerConfig
    connect_timeout_seconds: float
    call_timeout_seconds: float
    publisher: EventPublisher | None
    environ: Mapping[str, str] | None
    snapshot: MCPServerSnapshot = field(init=False)
    tool_definitions: dict[str, UnifiedToolDefinition] = field(default_factory=dict)
    tool_names: dict[str, str] = field(default_factory=dict)
    capability_targets: dict[str, _CapabilityTarget] = field(default_factory=dict)
    _commands: asyncio.Queue[_Command] = field(default_factory=asyncio.Queue)
    _task: asyncio.Task[None] | None = None
    _ready: asyncio.Future[MCPServerSnapshot] | None = None
    _active: set[asyncio.Task[Any]] = field(default_factory=set)
    _stop_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def __post_init__(self) -> None:
        self.snapshot = MCPServerSnapshot(config=self.config)

    async def start(self) -> MCPServerSnapshot:
        if self._task is not None and not self._task.done():
            return self.snapshot.model_copy(deep=True)
        loop = asyncio.get_running_loop()
        self._ready = loop.create_future()
        self._task = asyncio.create_task(
            self._run(),
            name=f"mcp-server-{self.config.server_id}",
        )
        try:
            return await self._ready
        except asyncio.CancelledError:
            if self._task is not None:
                self._task.cancel()
                await asyncio.gather(self._task, return_exceptions=True)
            raise
        except Exception:
            if self._task is not None:
                await asyncio.gather(self._task, return_exceptions=True)
            raise

    async def stop(self) -> None:
        async with self._stop_lock:
            task = self._task
            if task is None:
                self._set_status(MCPServerStatus.DISCONNECTED)
                return
            if not task.done():
                loop = asyncio.get_running_loop()
                future: asyncio.Future[None] = loop.create_future()
                await self._commands.put(_Command("stop", (), future))
                await future
            await asyncio.gather(task, return_exceptions=True)
            self._task = None

    async def request(self, operation: str, *arguments: Any) -> Any:
        if self.snapshot.status not in {
            MCPServerStatus.CONNECTED,
            MCPServerStatus.DEGRADED,
        }:
            raise MCPConnectionError(f"MCP server {self.config.server_id} is not connected")
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        await self._commands.put(_Command(operation, arguments, future))
        return await future

    async def _run(self) -> None:
        self._set_status(MCPServerStatus.CONNECTING)
        stack = AsyncExitStack()
        try:
            timeout = self.config.connect_timeout_seconds or self.connect_timeout_seconds
            async with asyncio.timeout(timeout):
                transport = build_transport(
                    self.config,
                    connect_timeout_seconds=self.connect_timeout_seconds,
                    call_timeout_seconds=self.call_timeout_seconds,
                    environ=self.environ,
                )
                streams = await stack.enter_async_context(transport)
                read_stream, write_stream = streams[0], streams[1]
                session = await stack.enter_async_context(
                    ClientSession(
                        read_stream,
                        write_stream,
                        read_timeout_seconds=timedelta(
                            seconds=self.config.call_timeout_seconds or self.call_timeout_seconds
                        ),
                    )
                )
                initialized = await session.initialize()
                await self._discover(session, initialized)

            self.snapshot = self.snapshot.model_copy(
                update={
                    "status": MCPServerStatus.CONNECTED,
                    "protocol_version": str(initialized.protocolVersion),
                    "error_message": None,
                },
                deep=True,
            )
            await self._emit(
                "mcp.connected",
                {
                    "server_id": self.config.server_id,
                    "protocol_version": self.snapshot.protocol_version,
                    "capability_count": len(self.snapshot.capabilities),
                },
            )
            await self._emit_capabilities()
            if self._ready is not None and not self._ready.done():
                self._ready.set_result(self.snapshot.model_copy(deep=True))

            while True:
                command = await self._commands.get()
                if command.operation == "stop":
                    for active in tuple(self._active):
                        active.cancel()
                    if self._active:
                        await asyncio.gather(*self._active, return_exceptions=True)
                    if not command.future.done():
                        command.future.set_result(None)
                    break
                if command.future.cancelled():
                    continue
                task = asyncio.create_task(self._dispatch(session, initialized, command))
                self._active.add(task)
                task.add_done_callback(self._active.discard)
                command.future.add_done_callback(
                    lambda future, active_task=task: (
                        active_task.cancel()
                        if future.cancelled() and not active_task.done()
                        else None
                    )
                )
        except Exception as exc:
            self.tool_definitions.clear()
            self.tool_names.clear()
            self.capability_targets.clear()
            self.snapshot = self.snapshot.model_copy(
                update={
                    "status": MCPServerStatus.FAILED,
                    "error_message": f"{type(exc).__name__}: {exc}",
                    "capabilities": [],
                },
                deep=True,
            )
            if self._ready is not None and not self._ready.done():
                self._ready.set_exception(
                    MCPConnectionError(
                        f"Failed to connect MCP server {self.config.server_id}: {exc}"
                    )
                )
            await self._emit(
                "mcp.disconnected",
                {
                    "server_id": self.config.server_id,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                },
            )
            self._reject_queued(exc)
        finally:
            for active in tuple(self._active):
                active.cancel()
            if self._active:
                await asyncio.gather(*self._active, return_exceptions=True)
            self._reject_queued(
                MCPConnectionError(f"MCP server {self.config.server_id} stopped")
            )
            try:
                await stack.aclose()
            finally:
                if self.snapshot.status != MCPServerStatus.FAILED:
                    self.tool_definitions.clear()
                    self.tool_names.clear()
                    self.capability_targets.clear()
                    self.snapshot = self.snapshot.model_copy(
                        update={
                            "status": MCPServerStatus.DISCONNECTED,
                            "capabilities": [],
                            "error_message": None,
                        },
                        deep=True,
                    )
                    await self._emit(
                        "mcp.disconnected",
                        {"server_id": self.config.server_id},
                    )

    async def _dispatch(
        self,
        session: ClientSession,
        initialized: mcp_types.InitializeResult,
        command: _Command,
    ) -> None:
        try:
            if command.operation == "refresh":
                await self._discover(session, initialized)
                self.snapshot = self.snapshot.model_copy(
                    update={
                        "status": MCPServerStatus.CONNECTED,
                        "error_message": None,
                    },
                    deep=True,
                )
                await self._emit_capabilities()
                result: Any = self.snapshot.model_copy(deep=True)
            elif command.operation == "call_tool":
                result = await self._call_tool(session, command.arguments[0])
            elif command.operation == "read_resource":
                result = await self._read_resource(session, command.arguments[0])
            elif command.operation == "get_prompt":
                result = await self._get_prompt(
                    session,
                    command.arguments[0],
                    command.arguments[1],
                )
            else:
                raise MCPManagerError(f"Unknown MCP worker operation: {command.operation}")
            if not command.future.done():
                command.future.set_result(result)
        except asyncio.CancelledError:
            if not command.future.done():
                command.future.set_exception(
                    MCPConnectionError(f"MCP server {self.config.server_id} stopped")
                )
            raise
        except Exception as exc:
            if command.operation == "refresh":
                self.snapshot = self.snapshot.model_copy(
                    update={
                        "status": MCPServerStatus.DEGRADED,
                        "error_message": f"{type(exc).__name__}: {exc}",
                    },
                    deep=True,
                )
            if not command.future.done():
                command.future.set_exception(exc)

    async def _discover(
        self,
        session: ClientSession,
        initialized: mcp_types.InitializeResult,
    ) -> None:
        capabilities: list[MCPCapability] = []
        tool_definitions: dict[str, UnifiedToolDefinition] = {}
        tool_names: dict[str, str] = {}
        targets: dict[str, _CapabilityTarget] = {}

        if initialized.capabilities.tools is not None:
            for tool in await _paginated(session.list_tools, "tools"):
                capability_id = _identifier(
                    "mcp",
                    self.config.server_id,
                    "tool",
                    tool.name,
                    max_length=320,
                )
                tool_id = _identifier(
                    "mcp",
                    self.config.server_id,
                    tool.name,
                    max_length=240,
                )
                annotations = (
                    tool.annotations.model_dump(mode="json", by_alias=True)
                    if tool.annotations is not None
                    else {}
                )
                metadata = {
                    "title": tool.title,
                    "output_schema": tool.outputSchema or {},
                    "annotations": annotations,
                    "meta": tool.meta or {},
                }
                capabilities.append(
                    MCPCapability(
                        capability_id=capability_id,
                        server_id=self.config.server_id,
                        kind=CapabilityKind.TOOL,
                        name=tool.name,
                        description=tool.description or "",
                        input_schema=tool.inputSchema,
                        metadata=metadata,
                    )
                )
                tool_definitions[tool_id] = UnifiedToolDefinition(
                    tool_id=tool_id,
                    name=tool.name,
                    description=tool.description or "",
                    origin=ToolOrigin.MCP,
                    input_schema=tool.inputSchema,
                    output_schema=tool.outputSchema or {},
                    server_id=self.config.server_id,
                    annotations=annotations,
                )
                tool_names[tool_id] = tool.name
                targets[capability_id] = _CapabilityTarget(
                    kind=CapabilityKind.TOOL,
                    name=tool.name,
                    locator=tool.name,
                )

        if initialized.capabilities.resources is not None:
            for resource in await _paginated(session.list_resources, "resources"):
                locator = str(resource.uri)
                capability_id = _identifier(
                    "mcp",
                    self.config.server_id,
                    "resource",
                    locator,
                    max_length=320,
                )
                metadata = resource.model_dump(mode="json", by_alias=True)
                capabilities.append(
                    MCPCapability(
                        capability_id=capability_id,
                        server_id=self.config.server_id,
                        kind=CapabilityKind.RESOURCE,
                        name=resource.name,
                        description=resource.description or "",
                        metadata=metadata,
                    )
                )
                targets[capability_id] = _CapabilityTarget(
                    kind=CapabilityKind.RESOURCE,
                    name=resource.name,
                    locator=locator,
                )

        if initialized.capabilities.prompts is not None:
            for prompt in await _paginated(session.list_prompts, "prompts"):
                capability_id = _identifier(
                    "mcp",
                    self.config.server_id,
                    "prompt",
                    prompt.name,
                    max_length=320,
                )
                arguments = [
                    item.model_dump(mode="json", by_alias=True) for item in (prompt.arguments or [])
                ]
                capabilities.append(
                    MCPCapability(
                        capability_id=capability_id,
                        server_id=self.config.server_id,
                        kind=CapabilityKind.PROMPT,
                        name=prompt.name,
                        description=prompt.description or "",
                        input_schema={
                            "type": "object",
                            "properties": {
                                item["name"]: {
                                    "type": "string",
                                    "description": item.get("description") or "",
                                }
                                for item in arguments
                            },
                            "required": [
                                item["name"] for item in arguments if item.get("required") is True
                            ],
                        },
                        metadata={"arguments": arguments, "meta": prompt.meta or {}},
                    )
                )
                targets[capability_id] = _CapabilityTarget(
                    kind=CapabilityKind.PROMPT,
                    name=prompt.name,
                    locator=prompt.name,
                )

        self.tool_definitions = tool_definitions
        self.tool_names = tool_names
        self.capability_targets = targets
        self.snapshot = self.snapshot.model_copy(
            update={"capabilities": capabilities},
            deep=True,
        )

    async def _call_tool(
        self,
        session: ClientSession,
        invocation: UnifiedToolInvocation,
    ) -> UnifiedToolResult:
        tool_name = self.tool_names.get(invocation.tool_id)
        if tool_name is None:
            raise MCPToolNotFoundError(invocation.tool_id)
        timeout = (
            invocation.timeout_seconds
            or self.config.call_timeout_seconds
            or self.call_timeout_seconds
        )
        started = time.perf_counter()
        await self._emit(
            "mcp.call_started",
            {
                "run_id": invocation.run_id,
                "flow_id": invocation.flow_id,
                "invocation_id": invocation.invocation_id,
                "server_id": self.config.server_id,
                "tool_id": invocation.tool_id,
                "tool_name": tool_name,
                "arguments": redact(invocation.arguments),
            },
        )
        try:
            async with asyncio.timeout(timeout):
                response = await session.call_tool(
                    tool_name,
                    invocation.arguments,
                    read_timeout_seconds=timedelta(seconds=timeout),
                )
            result = _normalize_tool_result(invocation, response, started)
            event_type = (
                "mcp.call_failed"
                if result.status == ToolExecutionStatus.FAILED
                else "mcp.call_completed"
            )
            await self._emit(event_type, _result_event_payload(invocation, result))
            return result
        except TimeoutError:
            result = UnifiedToolResult(
                invocation_id=invocation.invocation_id,
                tool_id=invocation.tool_id,
                status=ToolExecutionStatus.TIMED_OUT,
                error_code="mcp_timeout",
                error_message=f"MCP tool call exceeded {timeout:g} seconds",
                duration_ms=_duration_ms(started),
            )
            await self._emit("mcp.call_failed", _result_event_payload(invocation, result))
            return result
        except asyncio.CancelledError:
            result = UnifiedToolResult(
                invocation_id=invocation.invocation_id,
                tool_id=invocation.tool_id,
                status=ToolExecutionStatus.CANCELLED,
                error_code="mcp_cancelled",
                error_message="MCP tool call was cancelled",
                duration_ms=_duration_ms(started),
            )
            await self._emit("mcp.call_failed", _result_event_payload(invocation, result))
            return result
        except Exception as exc:
            result = UnifiedToolResult(
                invocation_id=invocation.invocation_id,
                tool_id=invocation.tool_id,
                status=ToolExecutionStatus.FAILED,
                error_code="mcp_call_error",
                error_message=f"{type(exc).__name__}: {exc}",
                duration_ms=_duration_ms(started),
            )
            await self._emit("mcp.call_failed", _result_event_payload(invocation, result))
            return result

    async def _read_resource(
        self,
        session: ClientSession,
        capability_id: str,
    ) -> dict[str, Any]:
        target = self._target(capability_id, CapabilityKind.RESOURCE)
        response = await session.read_resource(AnyUrl(target.locator))
        return response.model_dump(mode="json", by_alias=True)

    async def _get_prompt(
        self,
        session: ClientSession,
        capability_id: str,
        arguments: dict[str, str] | None,
    ) -> dict[str, Any]:
        target = self._target(capability_id, CapabilityKind.PROMPT)
        response = await session.get_prompt(target.locator, arguments=arguments)
        return response.model_dump(mode="json", by_alias=True)

    def _target(
        self,
        capability_id: str,
        expected_kind: CapabilityKind,
    ) -> _CapabilityTarget:
        target = self.capability_targets.get(capability_id)
        if target is None or target.kind != expected_kind:
            raise MCPManagerError(f"Unknown {expected_kind.value} capability: {capability_id}")
        return target

    async def _emit_capabilities(self) -> None:
        await self._emit(
            "mcp.capabilities_updated",
            {
                "server_id": self.config.server_id,
                "capabilities": [
                    item.model_dump(mode="json") for item in self.snapshot.capabilities
                ],
            },
        )

    async def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self.publisher is None:
            return
        try:
            safe_payload = _redact_url_queries(redact(payload))
            result = self.publisher(event_type, safe_payload)
            if inspect.isawaitable(result):
                await result
        except Exception:
            logger.exception(
                "MCP event publisher failed for %s on server %s",
                event_type,
                self.config.server_id,
            )

    def _set_status(self, status: MCPServerStatus) -> None:
        self.snapshot = self.snapshot.model_copy(update={"status": status}, deep=True)

    def _reject_queued(self, error: Exception) -> None:
        while not self._commands.empty():
            command = self._commands.get_nowait()
            if not command.future.done():
                command.future.set_exception(error)


class MCPManager:
    """Owns native MCP server sessions and exposes discovered capabilities."""

    def __init__(
        self,
        configs: list[MCPServerConfig],
        *,
        connect_timeout_seconds: float = 30.0,
        call_timeout_seconds: float = 300.0,
        refresh_interval_seconds: float = 60.0,
        publisher: EventPublisher | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        identifiers = [item.server_id for item in configs]
        if len(identifiers) != len(set(identifiers)):
            raise MCPManagerError("MCP server_id values must be unique")
        self.configs = {item.server_id: item for item in configs}
        self.connect_timeout_seconds = connect_timeout_seconds
        self.call_timeout_seconds = call_timeout_seconds
        self.refresh_interval_seconds = refresh_interval_seconds
        self.publisher = publisher
        self.environ = environ
        self._workers: dict[str, _ServerWorker] = {}
        self._refresh_task: asyncio.Task[None] | None = None

    async def startup(self) -> None:
        results = await asyncio.gather(
            *(self.connect(item.server_id) for item in self.configs.values() if item.enabled),
            return_exceptions=True,
        )
        # Failed servers remain visible through their FAILED snapshots while healthy peers start.
        _ = results
        if any(item.enabled for item in self.configs.values()):
            self._refresh_task = asyncio.create_task(
                self._refresh_loop(),
                name="mcp-capability-refresh",
            )

    async def shutdown(self) -> None:
        if self._refresh_task is not None:
            self._refresh_task.cancel()
            await asyncio.gather(self._refresh_task, return_exceptions=True)
            self._refresh_task = None
        await asyncio.gather(
            *(worker.stop() for worker in self._workers.values()),
            return_exceptions=True,
        )

    async def connect(self, server_id: str) -> MCPServerSnapshot:
        config = self._config(server_id)
        existing = self._workers.get(server_id)
        if existing is not None:
            await existing.stop()
        worker = _ServerWorker(
            config=config,
            connect_timeout_seconds=self.connect_timeout_seconds,
            call_timeout_seconds=self.call_timeout_seconds,
            publisher=self.publisher,
            environ=self.environ,
        )
        self._workers[server_id] = worker
        return await worker.start()

    async def disconnect(self, server_id: str) -> None:
        worker = self._workers.get(server_id)
        if worker is not None:
            await worker.stop()

    async def refresh(self, server_id: str) -> MCPServerSnapshot:
        return await self._worker(server_id).request("refresh")

    async def refresh_all(self) -> list[MCPServerSnapshot]:
        results = await asyncio.gather(
            *(
                worker.request("refresh")
                for worker in self._workers.values()
                if worker.snapshot.status in {MCPServerStatus.CONNECTED, MCPServerStatus.DEGRADED}
            ),
            return_exceptions=True,
        )
        return [item for item in results if isinstance(item, MCPServerSnapshot)]

    def snapshots(self) -> list[MCPServerSnapshot]:
        snapshots: list[MCPServerSnapshot] = []
        for server_id, config in self.configs.items():
            worker = self._workers.get(server_id)
            snapshots.append(
                worker.snapshot.model_copy(deep=True)
                if worker is not None
                else MCPServerSnapshot(config=config)
            )
        return snapshots

    def capabilities(self) -> list[MCPCapability]:
        return [
            item.model_copy(deep=True)
            for worker in self._workers.values()
            if worker.snapshot.status in {MCPServerStatus.CONNECTED, MCPServerStatus.DEGRADED}
            for item in worker.snapshot.capabilities
        ]

    def tool_definitions(self) -> list[UnifiedToolDefinition]:
        return [
            item.model_copy(deep=True)
            for worker in self._workers.values()
            if worker.snapshot.status in {MCPServerStatus.CONNECTED, MCPServerStatus.DEGRADED}
            for item in worker.tool_definitions.values()
        ]

    async def call_tool(self, invocation: UnifiedToolInvocation) -> UnifiedToolResult:
        for worker in self._workers.values():
            if invocation.tool_id in worker.tool_definitions:
                return await worker.request("call_tool", invocation)
        raise MCPToolNotFoundError(invocation.tool_id)

    async def read_resource(self, capability_id: str) -> dict[str, Any]:
        for worker in self._workers.values():
            target = worker.capability_targets.get(capability_id)
            if target is not None and target.kind == CapabilityKind.RESOURCE:
                return await worker.request("read_resource", capability_id)
        raise MCPManagerError(f"Unknown resource capability: {capability_id}")

    async def get_prompt(
        self,
        capability_id: str,
        arguments: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        for worker in self._workers.values():
            target = worker.capability_targets.get(capability_id)
            if target is not None and target.kind == CapabilityKind.PROMPT:
                return await worker.request("get_prompt", capability_id, arguments)
        raise MCPManagerError(f"Unknown prompt capability: {capability_id}")

    async def _refresh_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(self.refresh_interval_seconds)
                await self.refresh_all()
        except asyncio.CancelledError:
            raise

    def _config(self, server_id: str) -> MCPServerConfig:
        try:
            return self.configs[server_id]
        except KeyError as exc:
            raise MCPManagerError(f"Unknown MCP server: {server_id}") from exc

    def _worker(self, server_id: str) -> _ServerWorker:
        try:
            return self._workers[server_id]
        except KeyError as exc:
            raise MCPConnectionError(f"MCP server {server_id} has not been started") from exc


async def _paginated(method: Callable[..., Awaitable[Any]], attribute: str) -> list[Any]:
    values: list[Any] = []
    cursor: str | None = None
    seen_cursors: set[str] = set()
    while True:
        response = await method(cursor)
        values.extend(getattr(response, attribute))
        cursor = response.nextCursor
        if cursor is None:
            return values
        if cursor in seen_cursors:
            raise MCPManagerError(f"MCP pagination repeated cursor: {cursor}")
        seen_cursors.add(cursor)


def _identifier(*parts: str, max_length: int) -> str:
    raw = ":".join(parts)
    if len(raw) <= max_length:
        return raw
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"{raw[: max_length - len(digest) - 1]}:{digest}"


def _normalize_tool_result(
    invocation: UnifiedToolInvocation,
    response: mcp_types.CallToolResult,
    started: float,
) -> UnifiedToolResult:
    content = [item.model_dump(mode="json", by_alias=True) for item in response.content]
    text_parts = [item.text for item in response.content if item.type == "text"]
    artifact_refs: list[str] = []
    for item in response.content:
        if item.type == "resource_link":
            artifact_refs.append(str(item.uri))
        elif item.type == "resource":
            artifact_refs.append(str(item.resource.uri))
    text = "\n".join(text_parts).strip()
    structured = response.structuredContent or {}
    data = {"content": content, "structured_content": structured}
    is_error = bool(response.isError)
    return UnifiedToolResult(
        invocation_id=invocation.invocation_id,
        tool_id=invocation.tool_id,
        status=(ToolExecutionStatus.FAILED if is_error else ToolExecutionStatus.COMPLETED),
        text=text,
        data=data,
        artifact_refs=artifact_refs,
        error_code="mcp_tool_error" if is_error else None,
        error_message=text or "MCP tool returned an error" if is_error else None,
        duration_ms=_duration_ms(started),
    )


def _result_event_payload(
    invocation: UnifiedToolInvocation,
    result: UnifiedToolResult,
) -> dict[str, Any]:
    return {
        "run_id": invocation.run_id,
        "flow_id": invocation.flow_id,
        "invocation_id": invocation.invocation_id,
        "tool_id": invocation.tool_id,
        "status": result.status.value,
        "duration_ms": result.duration_ms,
        "error_code": result.error_code,
        "error_message": result.error_message,
    }


def _duration_ms(started: float) -> int:
    return max(0, round((time.perf_counter() - started) * 1000))


def _redact_url_queries(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _redact_url_queries(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_url_queries(item) for item in value]
    if not isinstance(value, str):
        return value

    def replace(match: re.Match[str]) -> str:
        raw_url = match.group(0)
        try:
            parts = urlsplit(raw_url)
            if not parts.query:
                return raw_url
            return urlunsplit(
                (parts.scheme, parts.netloc, parts.path, "[REDACTED]", parts.fragment)
            )
        except ValueError:
            return "[REDACTED_URL]"

    return URL_PATTERN.sub(replace, value)
