from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import ValidationError

from agents.actions import AgentAction
from agents.dispatcher import AgentDispatcher
from agents.loop_guard import AgentLoopGuard, LoopReason
from agents.native import StaticPromptResolver
from agents.registry import build_native_agent_registry
from agents.verifier import (
    IndependentVerifier,
    PredicateOperator,
    VerificationPredicate,
    VerificationProbe,
    VerificationRequest,
    register_verifier_tool,
)
from app.database import create_native_repositories
from app.schemas.agents import AgentInstance, AgentRole, AgentTask
from app.schemas.runtime import EventContext, VerificationVerdict
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
from llm.base import LLMMessage, LLMProvider, LLMResponse
from tools.mcp.gateway import UnifiedToolGateway


class SequenceModel(LLMProvider):
    name = "sequence"

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = responses
        self.calls = 0

    async def complete(self, messages: list[LLMMessage], **kwargs: Any) -> LLMResponse:
        index = min(self.calls, len(self.responses) - 1)
        self.calls += 1
        return LLMResponse(
            content=json.dumps(self.responses[index]),
            model="sequence",
            provider=self.name,
        )


class StableToolGateway:
    def __init__(self) -> None:
        self.calls: list[UnifiedToolInvocation] = []

    async def invoke(self, call: UnifiedToolInvocation) -> UnifiedToolResult:
        self.calls.append(call)
        mode = str(call.arguments.get("mode") or "same")
        return UnifiedToolResult(
            invocation_id=call.invocation_id,
            tool_id=call.tool_id,
            status=ToolExecutionStatus.COMPLETED,
            data={"mode": mode, "value": "unchanged"},
        )


def tool_action(mode: str = "same") -> dict[str, Any]:
    return {
        "action": "tool",
        "tool_id": "native:test",
        "arguments": {"mode": mode},
    }


def test_loop_guard_detects_repeated_call_and_strategy_change() -> None:
    guard = AgentLoopGuard()
    repeated = AgentAction.model_validate(tool_action())

    assert guard.inspect_action(repeated)[1] is None
    assert guard.inspect_action(repeated)[1] is None
    fingerprint, detection, _ = guard.inspect_action(repeated)

    assert detection is not None
    assert detection.reason == LoopReason.REPEATED_CALL
    assert detection.action_fingerprint == fingerprint
    _, next_detection, change = guard.inspect_action(
        AgentAction.model_validate(tool_action("different"))
    )
    assert next_detection is None
    assert change is not None
    assert change.previous_action_fingerprint == fingerprint


@pytest.mark.asyncio
async def test_native_agent_requires_strategy_change_after_repeated_result() -> None:
    model = SequenceModel(
        [
            tool_action(),
            tool_action(),
            tool_action(),
            tool_action("different"),
            {"action": "complete", "summary": "已切换方法并完成。"},
        ]
    )
    gateway = StableToolGateway()
    events: list[tuple[str, dict[str, Any]]] = []

    async def publish(event_type, payload, actor, context=None) -> None:
        events.append((event_type, payload))

    dispatcher = AgentDispatcher(
        registry=build_native_agent_registry(
            model=model,
            prompts=StaticPromptResolver(),
            max_iterations=8,
        ),
        publisher=publish,
        tool_gateway=gateway,
    )
    result = await dispatcher.dispatch_root(
        AgentRole.ASSISTANT,
        AgentTask(run_id="run-loop", flow_id="flow-loop", objective="测试循环防护"),
    )

    assert result.status.value == "completed"
    assert len(gateway.calls) == 4
    event_types = [item[0] for item in events]
    assert "loop.detected" in event_types
    assert "strategy.changed" in event_types
    detected = next(payload for event_type, payload in events if event_type == "loop.detected")
    assert detected["reason"] == "repeated_result"
    assert "required_change" in detected


@pytest.mark.asyncio
async def test_native_agent_fails_when_loop_guard_is_repeatedly_ignored() -> None:
    model = SequenceModel([tool_action()])
    gateway = StableToolGateway()
    events: list[str] = []

    async def publish(event_type, payload, actor, context=None) -> None:
        events.append(event_type)

    dispatcher = AgentDispatcher(
        registry=build_native_agent_registry(
            model=model,
            prompts=StaticPromptResolver(),
            max_iterations=10,
        ),
        publisher=publish,
        tool_gateway=gateway,
    )
    result = await dispatcher.dispatch_root(
        AgentRole.ASSISTANT,
        AgentTask(run_id="run-loop", flow_id="flow-loop", objective="持续重复调用"),
    )

    assert result.status.value == "failed"
    assert result.error_code == "AGENT_LOOP_DETECTED"
    assert events.count("loop.detected") == 3
    assert len(gateway.calls) == 3


class VerificationGateway:
    def __init__(self, values: dict[str, dict[str, Any]]) -> None:
        self.values = values
        self.calls: list[UnifiedToolInvocation] = []

    async def invoke(self, call: UnifiedToolInvocation) -> UnifiedToolResult:
        self.calls.append(call)
        value = self.values[str(call.arguments["target"])]
        return UnifiedToolResult(
            invocation_id=call.invocation_id,
            tool_id=call.tool_id,
            status=ToolExecutionStatus(value.get("status", "completed")),
            data=value.get("data", {}),
            evidence_ids=value.get("evidence_ids", []),
            error_code=value.get("error_code"),
        )


def verification_request(*, reject: bool = False) -> VerificationRequest:
    return VerificationRequest(
        run_id="run-verify",
        flow_id="flow-verify",
        finding_id="finding-1",
        claim="目标存在可独立复现的安全问题",
        subject_agent_instance_id="agent-original",
        verifier_agent_instance_id="agent-verifier",
        evidence_ids=["evidence-original"],
        reproduction=VerificationProbe(
            tool_id="native:verify",
            arguments={"target": "target"},
        ),
        baseline=VerificationProbe(
            tool_id="native:verify",
            arguments={"target": "baseline"},
        ),
        negative_control=VerificationProbe(
            tool_id="native:verify",
            arguments={"target": "negative"},
        ),
        confirm_when=VerificationPredicate(
            pointer="/data/vulnerable",
            operator=PredicateOperator.EQUALS,
            expected=True,
        ),
        reject_when=(
            VerificationPredicate(
                pointer="/data/state",
                operator=PredicateOperator.EQUALS,
                expected="safe",
            )
            if reject
            else None
        ),
        scope={"allowed_targets": ["target", "baseline", "negative"]},
    )


@pytest.mark.asyncio
async def test_independent_verifier_confirms_with_discriminating_controls() -> None:
    gateway = VerificationGateway(
        {
            "target": {
                "data": {"vulnerable": True, "state": "unsafe"},
                "evidence_ids": ["evidence-reproduction"],
            },
            "baseline": {"data": {"vulnerable": False, "state": "safe"}},
            "negative": {"data": {"vulnerable": False, "state": "safe"}},
        }
    )
    events: list[tuple[str, dict[str, Any]]] = []

    async def publish(event_type, request, payload) -> None:
        events.append((event_type, payload))

    verifier = IndependentVerifier(
        tool_gateway=gateway,
        evidence_resolver=lambda run_id, finding_id, ids: set(ids),
        publisher=publish,
    )
    result = await verifier.verify(verification_request())

    assert result.verdict == VerificationVerdict.CONFIRMED
    assert result.confidence == 0.9
    assert result.source_evidence_valid is True
    assert "evidence-reproduction" in result.evidence_ids
    assert len({item.invocation_id for item in gateway.calls}) == 3
    assert all(item.agent_instance_id == "agent-verifier" for item in gateway.calls)
    assert [item[0] for item in events] == [
        "verification.started",
        "verification.completed",
    ]
    assert events[-1][1]["verdict"] == "confirmed"


@pytest.mark.asyncio
async def test_verifier_rejects_only_with_explicit_counterevidence() -> None:
    values = {
        "target": {"data": {"vulnerable": False, "state": "safe"}},
        "baseline": {"data": {"vulnerable": False, "state": "safe"}},
        "negative": {"data": {"vulnerable": False, "state": "safe"}},
    }
    verifier = IndependentVerifier(
        tool_gateway=VerificationGateway(values),
        evidence_resolver=lambda run_id, finding_id, ids: set(ids),
    )

    inconclusive = await verifier.verify(verification_request(reject=False))
    rejected = await verifier.verify(verification_request(reject=True))

    conflicting_values = dict(values)
    conflicting_values["target"] = {"data": {"vulnerable": True, "state": "safe"}}
    conflicting = await IndependentVerifier(
        tool_gateway=VerificationGateway(conflicting_values),
        evidence_resolver=lambda run_id, finding_id, ids: set(ids),
    ).verify(verification_request(reject=True))

    assert inconclusive.verdict == VerificationVerdict.INCONCLUSIVE
    assert any("没有满足显式反证谓词" in item for item in inconclusive.limitations)
    assert rejected.verdict == VerificationVerdict.REJECTED
    assert rejected.counterevidence_refs[0].startswith("tool-call:")
    assert conflicting.verdict == VerificationVerdict.INCONCLUSIVE
    assert any("判定规则相互冲突" in item for item in conflicting.limitations)


@pytest.mark.asyncio
async def test_verifier_is_inconclusive_for_missing_evidence_or_bad_control() -> None:
    gateway = VerificationGateway(
        {
            "target": {"data": {"vulnerable": True}},
            "baseline": {"data": {"vulnerable": True}},
            "negative": {"data": {"vulnerable": False}},
        }
    )
    verifier = IndependentVerifier(
        tool_gateway=gateway,
        evidence_resolver=lambda run_id, finding_id, ids: set(),
    )
    result = await verifier.verify(verification_request())

    assert result.verdict == VerificationVerdict.INCONCLUSIVE
    assert result.source_evidence_valid is False
    assert any("缺乏区分度" in item for item in result.limitations)


def test_verification_request_requires_independence_and_distinct_baseline() -> None:
    raw = verification_request().model_dump(mode="json")
    raw["verifier_agent_instance_id"] = "agent-original"
    with pytest.raises(ValidationError, match="independent Agent"):
        VerificationRequest.model_validate(raw)

    raw = verification_request().model_dump(mode="json")
    raw["baseline"]["arguments"] = raw["reproduction"]["arguments"]
    with pytest.raises(ValidationError, match="baseline arguments"):
        VerificationRequest.model_validate(raw)


class EmptyMCPManager:
    def tool_definitions(self) -> list[UnifiedToolDefinition]:
        return []

    async def call_tool(self, invocation: UnifiedToolInvocation) -> UnifiedToolResult:
        raise AssertionError("MCP should not be called")


@pytest.mark.asyncio
async def test_verifier_persists_probe_and_verdict_event_chain(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'verifier.db'}"
    repositories = create_native_repositories(database_url)
    Base.metadata.create_all(repositories.engine)
    repositories.flows.ensure_flow("flow-verify", title="Verifier")
    for instance_id, role in (
        ("agent-original", AgentRole.PENTESTER),
        ("agent-verifier", AgentRole.REFLECTOR),
    ):
        repositories.agents.create_instance(
            AgentInstance(
                instance_id=instance_id,
                run_id="run-verify",
                flow_id="flow-verify",
                role=role,
            )
        )
    repositories.results.record_evidence(
        evidence_id="evidence-original",
        run_id="run-verify",
        source="original-tool",
        summary="原始 Finding 证据",
    )
    repositories.results.record_finding(
        finding_id="finding-1",
        run_id="run-verify",
        rule_id="TEST-1",
        severity="HIGH",
        confidence="HIGH",
        path="authorized-target",
        title="待独立验证的 Finding",
        description="目标存在可独立复现的安全问题",
        evidence_ids=["evidence-original"],
    )

    unified = UnifiedToolGateway(EmptyMCPManager())  # type: ignore[arg-type]
    definition = UnifiedToolDefinition(
        tool_id="native:verify",
        name="verify",
        origin=ToolOrigin.NATIVE,
        annotations={
            "scope": {"allowed_targets": ["target", "baseline", "negative"]}
        },
    )

    async def handler(call: UnifiedToolInvocation) -> UnifiedToolResult:
        target = str(call.arguments["target"])
        return UnifiedToolResult(
            invocation_id=call.invocation_id,
            tool_id=call.tool_id,
            status=ToolExecutionStatus.COMPLETED,
            data={"vulnerable": target == "target"},
            evidence_ids=[f"evidence-{target}"],
        )

    unified.register_native(definition, handler)
    ledger = RuntimeLedgerStore(database_url)
    persisted = PersistedToolGateway(
        gateway=unified,
        repositories=repositories,
        ledger=ledger,
        event_hub=RuntimeEventHub(),
    )

    async def publish(event_type, request, payload) -> None:
        ledger.append(
            request.run_id,
            event_type,
            payload,
            actor="independent_verifier",
            context=EventContext(
                flow_id=request.flow_id,
                correlation_id=request.verification_id,
                agent_instance_id=request.verifier_agent_instance_id,
            ),
        )

    verifier = IndependentVerifier(
        tool_gateway=persisted,
        evidence_resolver=lambda run_id, finding_id, ids: {
            item.evidence_id
            for item in repositories.results.list_evidence(run_id)
            if item.evidence_id in ids and finding_id == "finding-1"
        },
        publisher=publish,
    )
    result = await verifier.verify(verification_request())
    events = ledger.events("run-verify")

    assert result.verdict == VerificationVerdict.CONFIRMED
    assert [item.event_type for item in events].count("tool.completed") == 3
    assert events[0].event_type == "verification.started"
    assert events[-1].event_type == "verification.completed"
    assert events[-1].verification_verdict == VerificationVerdict.CONFIRMED
    assert len(repositories.tool_calls.list_for_run("run-verify")) == 3


@pytest.mark.asyncio
async def test_registered_verifier_tool_is_agent_callable() -> None:
    registered: dict[str, Any] = {}

    class Registry:
        def register_native(self, definition, handler) -> None:
            registered["definition"] = definition
            registered["handler"] = handler

    gateway = VerificationGateway(
        {
            "target": {"data": {"vulnerable": True}},
            "baseline": {"data": {"vulnerable": False}},
            "negative": {"data": {"vulnerable": False}},
        }
    )
    verifier = IndependentVerifier(
        tool_gateway=gateway,
        evidence_resolver=lambda run_id, finding_id, ids: set(ids),
    )
    register_verifier_tool(Registry(), verifier)
    request = verification_request().model_dump(
        mode="json",
        exclude={
            "verification_id",
            "run_id",
            "flow_id",
            "verifier_agent_instance_id",
        },
    )
    result = await registered["handler"](
        UnifiedToolInvocation(
            run_id="run-verify",
            flow_id="flow-verify",
            agent_instance_id="agent-verifier",
            tool_id="native:independent_verify",
            arguments=request,
        )
    )

    assert registered["definition"].tool_id == "native:independent_verify"
    assert result.status == ToolExecutionStatus.COMPLETED
    assert result.data["verdict"] == "confirmed"
