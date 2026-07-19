from __future__ import annotations

import os
from collections.abc import Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any

import httpx
from mcp import StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

from app.schemas.mcp import MCPServerConfig, MCPTransport


class MCPTransportError(RuntimeError):
    pass


def resolve_environment_refs(
    refs: Mapping[str, str],
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    source = os.environ if environ is None else environ
    resolved: dict[str, str] = {}
    missing: list[str] = []
    for target_name, source_name in refs.items():
        value = source.get(source_name)
        if value is None:
            missing.append(source_name)
        else:
            resolved[target_name] = value
    if missing:
        raise MCPTransportError(
            f"Missing environment references: {', '.join(sorted(set(missing)))}"
        )
    return resolved


def build_transport(
    config: MCPServerConfig,
    *,
    connect_timeout_seconds: float,
    call_timeout_seconds: float,
    environ: Mapping[str, str] | None = None,
) -> AbstractAsyncContextManager[Any]:
    connect_timeout = config.connect_timeout_seconds or connect_timeout_seconds
    call_timeout = config.call_timeout_seconds or call_timeout_seconds

    if config.transport == MCPTransport.STDIO:
        if config.command is None:  # guarded by the canonical Pydantic contract
            raise MCPTransportError("stdio MCP server has no command")
        parameters = StdioServerParameters(
            command=config.command,
            args=list(config.args),
            cwd=config.cwd,
            env=resolve_environment_refs(config.env_refs, environ),
            encoding="utf-8",
            encoding_error_handler="replace",
        )
        return stdio_client(parameters)

    headers = resolve_environment_refs(config.header_refs, environ)
    if config.url is None:  # guarded by the canonical Pydantic contract
        raise MCPTransportError("HTTP MCP server has no URL")
    if config.transport == MCPTransport.STREAMABLE_HTTP:
        return _streamable_http_transport(
            config.url,
            headers=headers,
            connect_timeout_seconds=connect_timeout,
            call_timeout_seconds=call_timeout,
        )
    if config.transport == MCPTransport.SSE:
        return sse_client(
            config.url,
            headers=headers,
            timeout=connect_timeout,
            sse_read_timeout=call_timeout,
        )
    raise MCPTransportError(f"Unsupported MCP transport: {config.transport}")


@asynccontextmanager
async def _streamable_http_transport(
    url: str,
    *,
    headers: dict[str, str],
    connect_timeout_seconds: float,
    call_timeout_seconds: float,
) -> Any:
    timeout = httpx.Timeout(call_timeout_seconds, connect=connect_timeout_seconds)
    async with httpx.AsyncClient(headers=headers, timeout=timeout) as client:
        async with streamable_http_client(url, http_client=client) as streams:
            yield streams
