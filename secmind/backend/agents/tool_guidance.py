from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.schemas.tools import UnifiedToolDefinition

TOOL_GUIDE_ENV = "SECMIND_TOOL_GUIDE_FILE"
DEFAULT_TOOL_GUIDE = Path(__file__).resolve().parents[1] / "tools" / "tool-agent-guide.json"
RUNTIME_GUIDE_FIELDS = (
    "what_is_it",
    "purpose",
    "when_to_use",
    "input_data",
    "output_data",
    "source",
)


def guidance_for(definition: UnifiedToolDefinition) -> dict[str, Any] | None:
    guide = _load_guide(str(_guide_path()))
    tools = guide.get("tools")
    if not isinstance(tools, dict):
        return None
    value = tools.get(definition.tool_id)
    if value is None and definition.server_id:
        value = tools.get(f"mcp:{definition.server_id}:{definition.name}")
    if value is None:
        value = tools.get(definition.name)
    if not isinstance(value, dict):
        return None
    return {key: value[key] for key in RUNTIME_GUIDE_FIELDS if key in value}


def _guide_path() -> Path:
    configured = os.getenv(TOOL_GUIDE_ENV, "").strip()
    return Path(configured).expanduser().resolve() if configured else DEFAULT_TOOL_GUIDE


@lru_cache(maxsize=8)
def _load_guide(path_value: str) -> dict[str, Any]:
    path = Path(path_value)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}
