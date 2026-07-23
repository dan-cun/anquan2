from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


class ContractAuditError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ServerSpec:
    server_id: str
    endpoint: str
    expected_tool_count: int | None


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_contract(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_server_specs(config_path: Path, contract: dict[str, Any]) -> list[ServerSpec]:
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    servers = [item for item in payload.get("servers", []) if item.get("enabled", True)]
    expected_ids = [str(item) for item in contract["expected_mcp_server_ids"]]
    actual_ids = [str(item.get("server_id")) for item in servers]
    if len(actual_ids) != len(set(actual_ids)):
        raise ContractAuditError("MCP configuration contains duplicate server IDs")
    if sorted(actual_ids) != sorted(expected_ids):
        raise ContractAuditError(
            f"MCP server IDs drifted: expected={sorted(expected_ids)!r}, actual={sorted(actual_ids)!r}"
        )

    expected_counts = contract.get("expected_mcp_tool_counts") or {}
    specs: list[ServerSpec] = []
    ports: set[int] = set()
    for item in servers:
        parsed = urlparse(str(item["url"]))
        if parsed.port is None:
            raise ContractAuditError(f"MCP server {item['server_id']} has no explicit port")
        if parsed.port in ports:
            raise ContractAuditError(f"MCP configuration reuses port {parsed.port}")
        ports.add(parsed.port)
        local_host = "127.0.0.1" if parsed.hostname == "host.docker.internal" else parsed.hostname
        endpoint = f"{parsed.scheme}://{local_host}:{parsed.port}{parsed.path or '/mcp'}"
        server_id = str(item["server_id"])
        count = expected_counts.get(server_id)
        specs.append(
            ServerSpec(
                server_id=server_id,
                endpoint=endpoint,
                expected_tool_count=int(count) if count is not None else None,
            )
        )

    expected_ports = set(range(9011, 9018))
    if ports != expected_ports:
        raise ContractAuditError(
            f"MCP port contract drifted: expected={sorted(expected_ports)}, actual={sorted(ports)}"
        )
    return specs


def _model_payload(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=True, exclude_none=True)
    if isinstance(value, dict):
        return value
    raise ContractAuditError(f"Unsupported MCP capability type: {type(value).__name__}")


def _declared_version(payload: dict[str, Any]) -> tuple[str, str]:
    annotations = payload.get("annotations") or {}
    metadata = payload.get("_meta") or payload.get("meta") or {}
    for source, values in (("annotations", annotations), ("metadata", metadata)):
        if not isinstance(values, dict):
            continue
        for key in ("version", "toolVersion", "tool_version"):
            if values.get(key):
                return str(values[key]), source
    return "unavailable", "not_declared_by_mcp_tool"


def _tool_definition(server_id: str, server_version: str, tool: Any) -> dict[str, Any]:
    payload = _model_payload(tool)
    name = str(payload["name"])
    input_schema = payload.get("inputSchema") or payload.get("input_schema") or {}
    output_schema = payload.get("outputSchema") or payload.get("output_schema") or {}
    if not isinstance(input_schema, dict) or not isinstance(output_schema, dict):
        raise ContractAuditError(f"Tool {server_id}:{name} returned a non-object JSON Schema")
    declared_version, version_source = _declared_version(payload)
    schema = {"input": input_schema, "output": output_schema}
    return {
        "tool_id": f"mcp:{server_id}:{name}",
        "server_id": server_id,
        "name": name,
        "description": payload.get("description") or "",
        "server_version": server_version,
        "declared_version": declared_version,
        "version_source": version_source,
        "input_schema": input_schema,
        "output_schema": output_schema,
        "annotations": payload.get("annotations") or {},
        "schema_sha256": canonical_sha256(schema),
    }


async def discover_once(spec: ServerSpec, timeout_seconds: float) -> dict[str, Any]:
    async def operation() -> dict[str, Any]:
        timeout = httpx.Timeout(timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout) as http_client:
            async with streamable_http_client(
                spec.endpoint,
                http_client=http_client,
            ) as streams:
                async with ClientSession(streams[0], streams[1]) as session:
                    initialized = await session.initialize()
                    initialize_payload = _model_payload(initialized)
                    server_info = initialize_payload.get("serverInfo") or {}
                    server_version = str(server_info.get("version") or "unavailable")

                    async def list_definitions() -> list[dict[str, Any]]:
                        tools: list[Any] = []
                        cursor: str | None = None
                        seen_cursors: set[str] = set()
                        while True:
                            listed = await session.list_tools(cursor=cursor)
                            tools.extend(listed.tools)
                            next_cursor = listed.nextCursor
                            if not next_cursor:
                                break
                            if next_cursor in seen_cursors:
                                raise ContractAuditError(
                                    f"MCP server {spec.server_id} repeated pagination cursor"
                                )
                            seen_cursors.add(next_cursor)
                            cursor = next_cursor
                        return sorted(
                            (
                                _tool_definition(spec.server_id, server_version, tool)
                                for tool in tools
                            ),
                            key=lambda item: item["tool_id"],
                        )

                    definitions = await list_definitions()
                    repeated_definitions = await list_definitions()
                    definitions_sha256 = canonical_sha256(definitions)
                    if definitions_sha256 != canonical_sha256(repeated_definitions):
                        raise ContractAuditError(
                            f"MCP server {spec.server_id} returned unstable Tool IDs, "
                            "versions, or schemas"
                        )
                    tool_ids = [item["tool_id"] for item in definitions]
                    if len(tool_ids) != len(set(tool_ids)):
                        raise ContractAuditError(
                            f"MCP server {spec.server_id} returned duplicate Tool IDs"
                        )
                    return {
                        "server_id": spec.server_id,
                        "endpoint": spec.endpoint,
                        "protocol_version": str(initialize_payload.get("protocolVersion")),
                        "server_info": server_info,
                        "capabilities": initialize_payload.get("capabilities") or {},
                        "tool_count": len(definitions),
                        "tools": definitions,
                        "definitions_sha256": definitions_sha256,
                        "stable_discovery_runs": 2,
                    }

    try:
        return await asyncio.wait_for(operation(), timeout=timeout_seconds)
    except TimeoutError as exc:
        raise ContractAuditError(
            f"MCP server {spec.server_id} initialization timed out after {timeout_seconds:g}s"
        ) from exc
    except ContractAuditError:
        raise
    except Exception as exc:
        raise ContractAuditError(
            f"MCP server {spec.server_id} connection failed: {type(exc).__name__}: {exc}"
        ) from exc


async def audit_server(spec: ServerSpec, timeout_seconds: float) -> dict[str, Any]:
    result = await discover_once(spec, timeout_seconds)
    if spec.expected_tool_count is not None and result["tool_count"] != spec.expected_tool_count:
        raise ContractAuditError(
            f"MCP server {spec.server_id} Tool count drifted: "
            f"expected={spec.expected_tool_count}, actual={result['tool_count']}"
        )
    return result


def validate_audit(contract: dict[str, Any], servers: list[dict[str, Any]]) -> dict[str, Any]:
    tools = sorted(
        (tool for server in servers for tool in server["tools"]),
        key=lambda item: item["tool_id"],
    )
    tool_ids = [item["tool_id"] for item in tools]
    if len(tool_ids) != len(set(tool_ids)):
        raise ContractAuditError("Duplicate MCP Tool IDs were found across servers")

    expected_mcp = int(contract["expected_mcp_tool_count"])
    expected_native = int(contract["expected_native_tool_count"])
    expected_total = int(contract["expected_tool_count"])
    if expected_native + expected_mcp != expected_total:
        raise ContractAuditError(
            f"Invalid contract arithmetic: {expected_native} + {expected_mcp} != {expected_total}"
        )
    if len(tools) != expected_mcp:
        raise ContractAuditError(
            f"MCP Tool count drifted: expected={expected_mcp}, actual={len(tools)}"
        )

    definitions_sha256 = canonical_sha256(tools)
    expected_hash = contract.get("expected_mcp_tool_definitions_sha256")
    if expected_hash and definitions_sha256 != expected_hash:
        raise ContractAuditError(
            "MCP Tool IDs, versions, or schemas drifted: "
            f"expected={expected_hash}, actual={definitions_sha256}"
        )
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "passed",
        "server_count": len(servers),
        "native_tool_count": expected_native,
        "mcp_tool_count": len(tools),
        "total_tool_count": expected_native + len(tools),
        "definitions_sha256": definitions_sha256,
        "servers": servers,
    }


async def run_audit(
    contract_path: Path,
    config_path: Path,
    *,
    timeout_seconds: float,
) -> dict[str, Any]:
    contract = load_contract(contract_path)
    specs = load_server_specs(config_path, contract)
    results = await asyncio.gather(
        *(audit_server(spec, timeout_seconds) for spec in specs),
        return_exceptions=True,
    )
    failures = [item for item in results if isinstance(item, BaseException)]
    if failures:
        raise ContractAuditError("; ".join(str(item) for item in failures))
    return validate_audit(contract, [item for item in results if isinstance(item, dict)])


async def main() -> None:
    parser = argparse.ArgumentParser(description="Audit the live SecMind 7/10/78/88 tool contract")
    parser.add_argument("--contract", type=Path, default=Path("config/runtime-contract.json"))
    parser.add_argument("--config", type=Path, default=Path("config/mcp-servers.json"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    args = parser.parse_args()

    try:
        report = await run_audit(
            args.contract.resolve(),
            args.config.resolve(),
            timeout_seconds=args.timeout_seconds,
        )
    except ContractAuditError as exc:
        raise SystemExit(f"MCP contract audit failed: {exc}") from exc
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(
        json.dumps(
            {
                "status": report["status"],
                "server_count": report["server_count"],
                "native_tool_count": report["native_tool_count"],
                "mcp_tool_count": report["mcp_tool_count"],
                "total_tool_count": report["total_tool_count"],
                "definitions_sha256": report["definitions_sha256"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
