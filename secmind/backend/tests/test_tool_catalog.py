from __future__ import annotations

import json
from pathlib import Path

from agents.registry import ROLE_DESCRIPTORS
from agents.tool_catalog import render_tool_catalog, visible_tool_definitions
from agents.tool_guidance import _load_guide
from app.schemas.agents import AgentRole
from app.schemas.tools import ToolOrigin, UnifiedToolDefinition


def descriptor(role: AgentRole):
    return next(item for item in ROLE_DESCRIPTORS if item.role == role)


def definition(**annotations) -> UnifiedToolDefinition:
    return UnifiedToolDefinition(
        tool_id="mcp:research:lookup",
        name="lookup",
        description="Look up public research",
        origin=ToolOrigin.MCP,
        server_id="research",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        output_schema={
            "type": "object",
            "properties": {"documents": {"type": "array"}},
        },
        annotations=annotations,
    )


def test_tool_catalog_filters_role_and_required_capabilities() -> None:
    search_only = definition(
        allowed_roles=["searcher", "enricher"],
        required_capabilities=["knowledge:search"],
    )

    assert [
        item.tool_id
        for item in visible_tool_definitions(descriptor(AgentRole.SEARCHER), [search_only])
    ] == ["mcp:research:lookup"]
    assert visible_tool_definitions(descriptor(AgentRole.CODER), [search_only]) == []
    assert visible_tool_definitions(descriptor(AgentRole.GENERATOR), [definition()]) == []


def test_rendered_catalog_contains_complete_schemas_and_stable_digest() -> None:
    item = definition(compatible_roles=["searcher"])
    first, first_digest = render_tool_catalog(descriptor(AgentRole.SEARCHER), [item])
    second, second_digest = render_tool_catalog(descriptor(AgentRole.SEARCHER), [item])
    payload = json.loads(first.split("\n", 1)[1])

    assert first == second
    assert first_digest == second_digest
    assert len(first_digest) == 64
    assert payload["tools"][0]["input_schema"]["required"] == ["query"]
    assert payload["tools"][0]["output_schema"]["properties"]["documents"] == {"type": "array"}


def test_rendered_catalog_adds_configured_agent_guidance(
    tmp_path: Path,
    monkeypatch,
) -> None:
    guide_path = tmp_path / "tool-guide.json"
    guide_path.write_text(
        json.dumps(
            {
                "tools": {
                    "mcp:research:lookup": {
                        "what_is_it": "公开资料检索 Tool",
                        "purpose": "检索资料",
                        "when_to_use": "需要外部证据时",
                        "input_data": "query",
                        "output_data": "documents",
                        "input_schema": {"duplicated": True},
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SECMIND_TOOL_GUIDE_FILE", str(guide_path))
    _load_guide.cache_clear()

    rendered, _ = render_tool_catalog(descriptor(AgentRole.SEARCHER), [definition()])
    payload = json.loads(rendered.split("\n", 1)[1])

    assert payload["tools"][0]["usage_guide"]["when_to_use"] == "需要外部证据时"
    assert "input_schema" not in payload["tools"][0]["usage_guide"]

    _load_guide.cache_clear()
