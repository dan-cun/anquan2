from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.schemas.mcp import MCPServerConfig


class MCPConfigError(ValueError):
    pass


def load_mcp_server_configs(path: Path | None) -> list[MCPServerConfig]:
    """Load the canonical MCP server list from a JSON configuration file."""

    if path is None:
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise MCPConfigError(f"Unable to read MCP config file {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise MCPConfigError(f"Invalid JSON in MCP config file {path}: {exc}") from exc

    raw_servers: Any
    if isinstance(payload, list):
        raw_servers = payload
    elif isinstance(payload, dict):
        raw_servers = payload.get("servers")
    else:
        raw_servers = None
    if not isinstance(raw_servers, list):
        raise MCPConfigError("MCP config must be a list or an object with a 'servers' list")

    try:
        configs = [MCPServerConfig.model_validate(item) for item in raw_servers]
    except ValidationError as exc:
        raise MCPConfigError(f"Invalid MCP server configuration: {exc}") from exc

    identifiers = [item.server_id for item in configs]
    duplicates = sorted({item for item in identifiers if identifiers.count(item) > 1})
    if duplicates:
        raise MCPConfigError(f"Duplicate MCP server_id values: {', '.join(duplicates)}")
    return configs
