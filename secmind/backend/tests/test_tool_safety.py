from __future__ import annotations

import asyncio
from typing import Any

import pytest

from agents.guardrail import Guardrail
from app.database import create_native_repositories
from app.schemas.agents import AgentInstance, AgentRole
from app.schemas.runtime import (
    CircuitState,
    RiskLevel,
    RuntimeToolContext,
    Scenario,
    ToolManifest,
)
from app.schemas.tools import (
    ToolExecutionStatus,
    ToolOrigin,
    UnifiedToolDefinition,
    UnifiedToolInvocation,
    UnifiedToolResult,
)
from app.services.collaboration import PersistedToolGateway
from app.services.runtime import RuntimeEventHub
from ledger.runtime_store import Base, RuntimeLedgerStore
from tools.mcp.gateway import UnifiedToolGateway
from tools.runtime import RuntimeTool, RuntimeToolBroker, RuntimeToolRegistry
from tools.safety import (
    CircuitBreakerRegistry,
    ToolScopeGuard,
    redact_tool_value,
)


class FakeMCPManager:
    def __init__(self, definitions: list[UnifiedToolDefinition] | None = None) -> None:
        self.definitions = definitions or []
        self.calls = 0
        self.result: UnifiedToolResult | None = None

    def tool_definitions(self) -> list[UnifiedToolDefinition]:
        return [item.model_copy(deep=True) for item in self.definitions]

    async def call_tool(self, invocation: UnifiedToolInvocation) -> UnifiedToolResult:
        self.calls += 1
        if self.result is None:
            raise RuntimeError("MCP result was not configured")
        return self.result.model_copy(
            update={
                "invocation_id": invocation.invocation_id,
                "tool_id": invocation.tool_id,
            },
            deep=True,
        )


def invocation(
    tool_id: str,
    *,
    arguments: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    timeout_seconds: float | None = None,
) -> UnifiedToolInvocation:
    return UnifiedToolInvocation(
        run_id="run-1",
        flow_id="flow-1",
        agent_instance_id="agent-1",
        tool_id=tool_id,
        arguments=arguments or {},
        metadata=metadata or {},
        timeout_seconds=timeout_seconds,
    )


def test_tool_redaction_is_recursive_and_idempotent() -> None:
    private_key = "-----BEGIN PRIVATE KEY-----\nsecret\n-----END PRIVATE KEY-----"
    payload = {
        "Authorization": "Bearer abcdefgh",
        "nested": {
            "x-api-key": "secret-key",
            "refreshToken": "refresh-secret",
            "url": "https://user:pass@example.test/api?X-Amz-Signature=secret",
            "private": private_key,
        },
    }

    first = redact_tool_value(payload)
    second = redact_tool_value(first)

    assert first == second
    assert first["Authorization"] == "[REDACTED]"
    assert first["nested"]["x-api-key"] == "[REDACTED]"
    assert first["nested"]["refreshToken"] == "[REDACTED]"
    assert first["nested"]["url"] == "https://example.test/api?[REDACTED]"
    assert first["nested"]["private"] == "[REDACTED]"


def test_scope_guard_enforces_declared_paths_hosts_and_targets(tmp_path) -> None:
    allowed_root = tmp_path / "authorized"
    allowed_root.mkdir()
    definition = UnifiedToolDefinition(
        tool_id="native:scan",
        name="scan",
        origin=ToolOrigin.NATIVE,
        annotations={
            "scope": {
                "workspace": str(allowed_root),
                "allowed_paths": [str(allowed_root)],
                "allowed_hosts": ["*.authorized.test", "10.0.0.0/24"],
            }
        },
    )
    guard = ToolScopeGuard()

    inside = guard.evaluate(
        definition,
        invocation(
            definition.tool_id,
            arguments={"path": "src", "url": "https://api.authorized.test/status"},
        ),
    )
    outside = guard.evaluate(
        definition,
        invocation(definition.tool_id, arguments={"path": "../outside"}),
    )

    assert inside.allowed is True
    assert outside.allowed is False
    assert "outside the declared tool scope" in outside.reason


@pytest.mark.asyncio
async def test_gateway_wraps_native_exception_and_recovers_half_open_circuit() -> None:
    now = [0.0]
    events: list[str] = []
    should_fail = [True]

    async def publish(
        event_type: str,
        call: UnifiedToolInvocation,
        payload: dict[str, Any],
    ) -> None:
        events.append(event_type)

    gateway = UnifiedToolGateway(
        FakeMCPManager(),  # type: ignore[arg-type]
        circuit_breakers=CircuitBreakerRegistry(
            failure_threshold=2,
            reset_timeout_seconds=10,
            clock=lambda: now[0],
        ),
        event_publisher=publish,
    )
    definition = UnifiedToolDefinition(
        tool_id="native:unstable",
        name="unstable",
        origin=ToolOrigin.NATIVE,
    )

    async def handler(call: UnifiedToolInvocation) -> UnifiedToolResult:
        if should_fail[0]:
            raise RuntimeError("Bearer top-secret-token")
        return UnifiedToolResult(
            invocation_id=call.invocation_id,
            tool_id=call.tool_id,
            status=ToolExecutionStatus.COMPLETED,
            text="recovered",
            data={"apiKey": "result-secret"},
        )

    gateway.register_native(definition, handler)
    first = await gateway.invoke(invocation(definition.tool_id))
    second = await gateway.invoke(invocation(definition.tool_id))
    blocked = await gateway.invoke(invocation(definition.tool_id))

    assert first.error_code == "native_tool_error"
    assert "top-secret-token" not in (first.error_message or "")
    assert second.status == ToolExecutionStatus.FAILED
    assert blocked.error_code == "circuit_open"
    assert "circuit.opened" in events

    now[0] = 11
    should_fail[0] = False
    recovered = await gateway.invoke(invocation(definition.tool_id))
    snapshot = await gateway.circuit_breakers.snapshot(f"tool:{definition.tool_id}")

    assert recovered.status == ToolExecutionStatus.COMPLETED
    assert recovered.data["apiKey"] == "[REDACTED]"
    assert snapshot.state == CircuitState.CLOSED
    assert "circuit.half_opened" in events
    assert "circuit.closed" in events


@pytest.mark.asyncio
async def test_gateway_timeout_is_model_visible() -> None:
    gateway = UnifiedToolGateway(FakeMCPManager())  # type: ignore[arg-type]
    definition = UnifiedToolDefinition(
        tool_id="native:slow",
        name="slow",
        origin=ToolOrigin.NATIVE,
    )

    async def handler(call: UnifiedToolInvocation) -> UnifiedToolResult:
        await asyncio.sleep(1)
        return UnifiedToolResult(
            invocation_id=call.invocation_id,
            tool_id=call.tool_id,
            status=ToolExecutionStatus.COMPLETED,
        )

    gateway.register_native(definition, handler)
    result = await gateway.invoke(invocation(definition.tool_id, timeout_seconds=0.01))

    assert result.status == ToolExecutionStatus.TIMED_OUT
    assert result.error_code == "tool_timeout"
    assert "exceeded" in (result.error_message or "")


@pytest.mark.asyncio
async def test_mcp_server_circuit_blocks_sibling_tool() -> None:
    first_definition = UnifiedToolDefinition(
        tool_id="mcp:server:one",
        name="one",
        origin=ToolOrigin.MCP,
        server_id="server",
    )
    second_definition = first_definition.model_copy(
        update={"tool_id": "mcp:server:two", "name": "two"}
    )
    manager = FakeMCPManager([first_definition, second_definition])
    manager.result = UnifiedToolResult(
        invocation_id="placeholder",
        tool_id="placeholder",
        status=ToolExecutionStatus.FAILED,
        error_code="mcp_call_error",
        error_message="server failed",
    )
    gateway = UnifiedToolGateway(
        manager,  # type: ignore[arg-type]
        circuit_breakers=CircuitBreakerRegistry(failure_threshold=1),
    )

    failed = await gateway.invoke(invocation(first_definition.tool_id))
    blocked = await gateway.invoke(invocation(second_definition.tool_id))

    assert failed.status == ToolExecutionStatus.FAILED
    assert blocked.error_code == "circuit_open"
    assert manager.calls == 1


@pytest.mark.asyncio
async def test_persisted_gateway_records_decision_scope_block_and_redacted_arguments(
    tmp_path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'tools.db'}"
    repositories = create_native_repositories(database_url)
    Base.metadata.create_all(repositories.engine)
    flow = repositories.flows.ensure_flow("flow-1", title="Scope test")
    repositories.agents.create_instance(
        AgentInstance(
            instance_id="agent-1",
            run_id="run-1",
            flow_id=flow.id,
            role=AgentRole.PENTESTER,
        )
    )
    manager = FakeMCPManager()
    gateway = UnifiedToolGateway(manager)  # type: ignore[arg-type]
    definition = UnifiedToolDefinition(
        tool_id="native:scoped",
        name="scoped",
        origin=ToolOrigin.NATIVE,
        annotations={"scope": {"allowed_hosts": ["authorized.test"]}},
    )
    handler_called = False

    async def handler(call: UnifiedToolInvocation) -> UnifiedToolResult:
        nonlocal handler_called
        handler_called = True
        return UnifiedToolResult(
            invocation_id=call.invocation_id,
            tool_id=call.tool_id,
            status=ToolExecutionStatus.COMPLETED,
        )

    gateway.register_native(definition, handler)
    ledger = RuntimeLedgerStore(database_url)
    persisted = PersistedToolGateway(
        gateway=gateway,
        repositories=repositories,
        ledger=ledger,
        event_hub=RuntimeEventHub(),
    )
    call = invocation(
        definition.tool_id,
        arguments={
            "url": "https://outside.test/scan?token=secret",
            "token": "secret",
        },
    )
    result = await persisted.invoke(call)

    assert result.error_code == "scope_violation"
    assert handler_called is False
    row = repositories.tool_calls.get(call.invocation_id)
    assert row is not None
    assert row.arguments_json["token"] == "[REDACTED]"
    assert row.arguments_json["url"] == "https://outside.test/scan?[REDACTED]"

    events = ledger.events(call.run_id)
    event_types = [item.event_type for item in events]
    assert event_types == [
        "decision.recorded",
        "tool.started",
        "guardrail.evaluated",
        "guardrail.denied",
        "tool.blocked",
    ]
    assert events[0].context.decision_id == events[1].context.decision_id
    assert all(item.context.tool_invocation_id == call.invocation_id for item in events)


@pytest.mark.asyncio
async def test_persisted_gateway_closes_cancelled_tool_lifecycle(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'cancelled-tools.db'}"
    repositories = create_native_repositories(database_url)
    Base.metadata.create_all(repositories.engine)
    flow = repositories.flows.ensure_flow("flow-1", title="Cancellation test")
    repositories.agents.create_instance(
        AgentInstance(
            instance_id="agent-1",
            run_id="run-1",
            flow_id=flow.id,
            role=AgentRole.PENTESTER,
        )
    )
    gateway = UnifiedToolGateway(FakeMCPManager())  # type: ignore[arg-type]
    definition = UnifiedToolDefinition(
        tool_id="native:waiting",
        name="waiting",
        origin=ToolOrigin.NATIVE,
    )
    handler_started = asyncio.Event()

    async def handler(call: UnifiedToolInvocation) -> UnifiedToolResult:
        handler_started.set()
        await asyncio.Future()
        raise AssertionError("unreachable")

    gateway.register_native(definition, handler)
    ledger = RuntimeLedgerStore(database_url)
    persisted = PersistedToolGateway(
        gateway=gateway,
        repositories=repositories,
        ledger=ledger,
        event_hub=RuntimeEventHub(),
    )
    call = invocation(definition.tool_id)
    task = asyncio.create_task(persisted.invoke(call))
    await handler_started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    row = repositories.tool_calls.get(call.invocation_id)
    assert row is not None
    assert row.status == ToolExecutionStatus.CANCELLED.value
    assert [item.event_type for item in ledger.events(call.run_id)][-1] == "tool.cancelled"


class ExplodingRuntimeTool(RuntimeTool):
    manifest = ToolManifest(
        name="exploding",
        version="1",
        description="Test runtime exception normalization",
        scenarios=[Scenario.CODE_AUDIT],
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        risk_level=RiskLevel.R0,
    )

    async def invoke(self, args, context):
        raise RuntimeError("password=should-not-escape")


@pytest.mark.asyncio
async def test_legacy_runtime_broker_wraps_tool_exception() -> None:
    registry = RuntimeToolRegistry()
    registry.register(ExplodingRuntimeTool())
    broker = RuntimeToolBroker(registry, Guardrail())

    result = await broker.invoke(
        "exploding",
        {},
        RuntimeToolContext(
            run_id="run-1",
            step_id="step-1",
            workspace=".",
            allowed_paths=["."],
        ),
    )

    assert result.error_code == "TOOL_RUNTIME_ERROR"
    assert "should-not-escape" not in (result.error_message or "")
