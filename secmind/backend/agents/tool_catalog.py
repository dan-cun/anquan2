from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any

from app.schemas.agents import AgentDescriptor
from app.schemas.tools import UnifiedToolDefinition

TOOL_INVOKE_CAPABILITY = "tool:invoke"


def visible_tool_definitions(
    descriptor: AgentDescriptor,
    definitions: Iterable[UnifiedToolDefinition],
) -> list[UnifiedToolDefinition]:
    """Return the current public tool catalog authorized for one Agent role."""
    if TOOL_INVOKE_CAPABILITY not in descriptor.capabilities:
        return []
    visible = [
        definition.model_copy(deep=True)
        for definition in definitions
        if _definition_allows_descriptor(definition, descriptor)
    ]
    return sorted(visible, key=lambda item: item.tool_id)


def render_tool_catalog(
    descriptor: AgentDescriptor,
    definitions: Iterable[UnifiedToolDefinition],
) -> tuple[str, str]:
    tools = [
        {
            "tool_id": item.tool_id,
            "name": item.name,
            "description": item.description,
            "origin": item.origin.value,
            "server_id": item.server_id,
            "input_schema": item.input_schema,
            "output_schema": item.output_schema,
            "annotations": item.annotations,
        }
        for item in visible_tool_definitions(descriptor, definitions)
    ]
    catalog = {
        "agent_role": descriptor.role.value,
        "instructions": (
            "Only invoke tool_id values listed in this runtime catalog. Arguments must satisfy "
            "the corresponding input_schema. An empty tools list means this role cannot invoke "
            "tools."
        ),
        "tools": tools,
    }
    canonical = json.dumps(
        catalog,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(canonical.encode("ascii")).hexdigest()
    return (
        "Current role-filtered runtime tool catalog (authoritative JSON):\n"
        + json.dumps(catalog, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        digest,
    )


def _definition_allows_descriptor(
    definition: UnifiedToolDefinition,
    descriptor: AgentDescriptor,
) -> bool:
    annotations = definition.annotations
    role = descriptor.role.value
    allowed_roles = _string_set(annotations.get("allowed_roles"))
    compatible_roles = _string_set(annotations.get("compatible_roles"))
    denied_roles = _string_set(annotations.get("denied_roles"))
    required_capabilities = _string_set(annotations.get("required_capabilities"))
    if allowed_roles and role not in allowed_roles:
        return False
    if compatible_roles and role not in compatible_roles:
        return False
    if role in denied_roles:
        return False
    return required_capabilities.issubset(set(descriptor.capabilities))


def _string_set(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, (list, tuple, set)):
        return {str(item) for item in value if str(item)}
    return set()
