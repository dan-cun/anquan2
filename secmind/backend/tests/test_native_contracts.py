from __future__ import annotations

from pathlib import Path

import pytest
from graphql import build_ast_schema, parse, validate_schema
from pydantic import ValidationError

from app.schemas.agents import (
    AgentDelegation,
    AgentDescriptor,
    AgentMessage,
    AgentMessageKind,
    AgentRole,
    AgentStatus,
    AgentTask,
)
from app.schemas.mcp import MCPCapability, MCPServerConfig, MCPTransport
from app.schemas.prompts import (
    PromptMessageRole,
    PromptTemplateRecord,
    PromptVersionRecord,
)
from app.schemas.tools import (
    CapabilityKind,
    ToolExecutionStatus,
    ToolOrigin,
    UnifiedToolDefinition,
    UnifiedToolInvocation,
    UnifiedToolResult,
)


def test_native_agent_role_set_is_frozen() -> None:
    assert {role.value for role in AgentRole} == {
        "primary_agent",
        "assistant",
        "generator",
        "refiner",
        "adviser",
        "reflector",
        "searcher",
        "enricher",
        "coder",
        "installer",
        "pentester",
        "memorist",
        "reporter",
        "summarizer",
        "toolcall_fixer",
    }


def test_agent_delegation_round_trip() -> None:
    task = AgentTask(
        run_id="run-1",
        flow_id="flow-1",
        objective="Inspect the authorized Python project",
    )
    delegation = AgentDelegation(
        run_id="run-1",
        flow_id="flow-1",
        from_agent_instance_id="agent-primary",
        to_role=AgentRole.CODER,
        task=task,
    )
    restored = AgentDelegation.model_validate_json(delegation.model_dump_json())

    assert restored.task.task_id == task.task_id
    assert restored.to_role == AgentRole.CODER
    assert restored.status == AgentStatus.CREATED


def test_agent_descriptor_and_message_reject_unknown_fields() -> None:
    descriptor = AgentDescriptor(
        role=AgentRole.PENTESTER,
        display_name="Pentester",
        prompt_key="pentester",
        capabilities=["native:terminal", "mcp:security:scan"],
    )
    message = AgentMessage(
        run_id="run-1",
        flow_id="flow-1",
        from_agent_instance_id="agent-1",
        to_role=AgentRole.REPORTER,
        kind=AgentMessageKind.RESPONSE,
        summary="Two evidence-backed findings were produced.",
    )

    assert descriptor.enabled is True
    assert message.to_role == AgentRole.REPORTER
    with pytest.raises(ValidationError):
        AgentDescriptor.model_validate({**descriptor.model_dump(), "unknown": True})


def test_mcp_transport_requires_the_native_target() -> None:
    stdio = MCPServerConfig(
        server_id="local-security",
        name="Local Security",
        transport=MCPTransport.STDIO,
        command="security-mcp",
    )
    remote = MCPServerConfig(
        server_id="remote-research",
        name="Remote Research",
        transport=MCPTransport.STREAMABLE_HTTP,
        url="https://mcp.example.test/api",
        header_refs={"Authorization": "SECMIND_RESEARCH_MCP_TOKEN"},
    )

    assert stdio.command == "security-mcp"
    assert remote.header_refs["Authorization"] == "SECMIND_RESEARCH_MCP_TOKEN"
    with pytest.raises(ValidationError, match="requires command"):
        MCPServerConfig(
            server_id="invalid",
            name="Invalid",
            transport=MCPTransport.STDIO,
        )


def test_mcp_capability_and_unified_tool_contract() -> None:
    capability = MCPCapability(
        capability_id="research:search",
        server_id="research",
        kind=CapabilityKind.TOOL,
        name="search",
        input_schema={"type": "object"},
    )
    definition = UnifiedToolDefinition(
        tool_id="mcp:research:search",
        name="search",
        origin=ToolOrigin.MCP,
        server_id="research",
        input_schema=capability.input_schema,
    )
    invocation = UnifiedToolInvocation(
        run_id="run-1",
        flow_id="flow-1",
        agent_instance_id="agent-searcher",
        tool_id=definition.tool_id,
        arguments={"query": "CVE-2026"},
    )
    result = UnifiedToolResult(
        invocation_id=invocation.invocation_id,
        tool_id=definition.tool_id,
        status=ToolExecutionStatus.COMPLETED,
        text="Search completed",
    )

    assert capability.kind == CapabilityKind.TOOL
    assert result.status == ToolExecutionStatus.COMPLETED


def test_prompt_version_contract_preserves_key_and_variables() -> None:
    template = PromptTemplateRecord(
        prompt_key="pentester",
        name="Pentester",
        category="Agent system prompt",
        message_role=PromptMessageRole.SYSTEM,
        agent_role=AgentRole.PENTESTER,
        variables=["CurrentTime", "ExecutionContext"],
    )
    version = PromptVersionRecord(
        prompt_key=template.prompt_key,
        version=1,
        content="Time: {{ CurrentTime }}",
        variables=["CurrentTime"],
        checksum="sha256:test",
    )

    assert version.prompt_key == template.prompt_key
    assert version.version == 1


def test_graphql_sdl_contains_native_operations() -> None:
    schema_path = Path(__file__).parents[1] / "app" / "graphql" / "schema.graphql"
    schema = schema_path.read_text(encoding="utf-8")
    required_operations = {
        "agentInstances",
        "agentDelegations",
        "mcpServers",
        "registerMCPServer",
        "createPromptVersion",
        "delegateAgent",
        "createAgent",
        "sendAgentMessage",
        "waitAgent",
        "stopAgent",
        "agentDelegated",
        "runtimeEventAdded",
    }

    assert all(operation in schema for operation in required_operations)
    assert "type Query" in schema
    assert "type Mutation" in schema
    assert "type Subscription" in schema

    graphql_schema = build_ast_schema(parse(schema))
    assert validate_schema(graphql_schema) == []
