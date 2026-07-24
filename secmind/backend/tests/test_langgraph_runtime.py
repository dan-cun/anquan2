from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from langgraph.checkpoint.memory import MemorySaver
from pydantic import ValidationError

from agents.guardrail import Guardrail
from app.core.config import Settings
from app.schemas.runtime import (
    CapabilityPlan,
    CapabilityStatus,
    Evidence,
    Finding,
    InputArtifact,
    PlanStep,
    RiskLevel,
    RunStatus,
    RuntimeToolContext,
    RuntimeToolResult,
    Scenario,
    TaskComplexity,
    TaskRequest,
    ToolManifest,
    ToolStatus,
    UnitOutcomeStatus,
    UniversalPrimaryResult,
    VerificationDelta,
)
from app.services.runtime import RuntimeEventHub, RuntimeRunService
from ledger.runtime_store import RuntimeLedgerStore
from llm.base import EmptyContentReason, LLMResponse, ProviderHTTPError
from tools.runtime import RuntimeTool, RuntimeToolBroker, RuntimeToolRegistry


def test_plan_step_requires_an_executable_tool_candidate() -> None:
    with pytest.raises(ValidationError, match="tool_candidates"):
        PlanStep(
            step_id="analysis-only",
            objective="Analyze a previous tool result without an executable action.",
            agent_role="security_analyst",
            tool_candidates=[],
        )


class ControlledModelManager:
    def __init__(self, *, plan_max_attempts: int = 2) -> None:
        self.stages: list[str] = []
        self.plan_max_attempts = plan_max_attempts

    def metadata(self) -> dict[str, Any]:
        return {"configured": True, "name": "controlled", "model": "controlled-model"}

    async def complete(self, messages: list[Any], **kwargs: Any) -> LLMResponse:
        stage = str(kwargs["stage"])
        self.stages.append(stage)
        if stage == "universal_primary":
            content = json.dumps(
                {
                    "status": "success",
                    "final_answer": None,
                    "executive_summary": "Universal Primary completed.",
                    "findings": [],
                    "evidence_gaps": ["Specialist verification is pending."],
                    "confidence": 0.5,
                    "limitations": [],
                }
            )
        elif stage == "plan":
            content = json.dumps(
                {
                    "steps": [
                        {
                            "step_id": "audit-python-bandit",
                            "objective": "Run the controlled audit tool.",
                            "agent_role": "executor",
                            "tool_candidates": ["bandit_python_audit"],
                            "inputs": {"target": "."},
                            "success_criteria": ["Return a structured result"],
                            "risk_hint": 1,
                            "max_attempts": self.plan_max_attempts,
                        }
                    ]
                }
            )
        else:
            content = f"controlled {stage} output"
        return LLMResponse(
            content=content,
            model="controlled-model",
            provider="controlled",
        )


class ControlledTool(RuntimeTool):
    def __init__(
        self,
        *,
        risk: RiskLevel = RiskLevel.R1,
        outcomes: list[ToolStatus] | None = None,
        idempotent: bool = True,
        emit_finding: bool = True,
    ) -> None:
        self.manifest = ToolManifest(
            name="bandit_python_audit",
            version="test",
            description="Controlled graph-runtime test tool.",
            scenarios=[Scenario.CODE_AUDIT],
            input_schema={},
            output_schema={},
            risk_level=risk,
            idempotent=idempotent,
        )
        self.outcomes = outcomes or [ToolStatus.SUCCESS]
        self.calls = 0
        self.emit_finding = emit_finding

    async def invoke(
        self,
        args: dict[str, Any],
        context: RuntimeToolContext,
    ) -> RuntimeToolResult:
        del args, context
        index = min(self.calls, len(self.outcomes) - 1)
        status = self.outcomes[index]
        self.calls += 1
        evidence = []
        data: dict[str, Any] = {}
        if status == ToolStatus.SUCCESS and self.emit_finding:
            item = Evidence(source="controlled", summary="verified controlled evidence")
            evidence = [item]
            data["findings"] = [
                Finding(
                    rule_id="CONTROLLED-001",
                    severity="MEDIUM",
                    confidence="HIGH",
                    path="controlled.py",
                    line=1,
                    title="Controlled finding",
                    description="Finding emitted by the isolated controlled tool.",
                    evidence_ids=[item.evidence_id],
                ).model_dump(mode="json")
            ]
        return RuntimeToolResult(
            status=status,
            summary=f"controlled result {self.calls}",
            data=data,
            evidence=evidence,
            error_code=None if status == ToolStatus.SUCCESS else "CONTROLLED_FAILURE",
        )


def build_runtime(
    tmp_path: Path,
    *,
    risk: RiskLevel = RiskLevel.R1,
    outcomes: list[ToolStatus] | None = None,
    max_steps: int = 12,
    max_tool_calls: int = 12,
    max_model_calls: int = 20,
    checkpointer: Any | None = None,
    idempotent: bool = True,
    emit_finding: bool = True,
    plan_max_attempts: int = 2,
) -> tuple[RuntimeRunService, ControlledTool, ControlledModelManager]:
    database_url = f"sqlite:///{(tmp_path / 'runtime.db').as_posix()}"
    settings = Settings(
        data_dir=tmp_path / "data",
        database_url=database_url,
        runtime_database_url=database_url,
        runtime_input_root=tmp_path / "inputs",
        runtime_run_root=tmp_path / "runs",
        runtime_upload_root=tmp_path / "uploads",
        runtime_max_steps=max_steps,
        runtime_max_tool_calls=max_tool_calls,
        runtime_max_model_calls=max_model_calls,
        mock_step_delay_seconds=0,
        llm_provider="null",
    )
    settings.prepare_runtime_directories()
    registry = RuntimeToolRegistry()
    tool = ControlledTool(
        risk=risk,
        outcomes=outcomes,
        idempotent=idempotent,
        emit_finding=emit_finding,
    )
    registry.register(tool)
    model = ControlledModelManager(plan_max_attempts=plan_max_attempts)
    runtime = RuntimeRunService(
        settings=settings,
        ledger=RuntimeLedgerStore(settings.resolved_runtime_database_url),
        broker=RuntimeToolBroker(registry, Guardrail()),
        event_hub=RuntimeEventHub(),
        llm_provider=model,  # type: ignore[arg-type]
        checkpointer=checkpointer,
    )
    return runtime, tool, model


def audit_task(**updates: Any) -> TaskRequest:
    return TaskRequest(objective="audit Python code with the controlled tool", **updates)


def test_complete_topology_and_checkpointer_injection(tmp_path: Path) -> None:
    checkpointer = MemorySaver()
    runtime, _, _ = build_runtime(tmp_path, checkpointer=checkpointer)
    graph = runtime.graph_runtime

    assert graph.checkpointer is checkpointer
    assert set(graph.NODE_NAMES) <= set(graph.graph.get_graph().nodes)
    assert {
        "retrieve_context",
        "select_step",
        "approval",
        "record_denial",
        "reflect",
        "memory_commit",
    } <= set(graph.NODE_NAMES)


@pytest.mark.asyncio
async def test_interrupt_and_command_resume_continue_same_graph(tmp_path: Path) -> None:
    runtime, tool, _ = build_runtime(tmp_path, risk=RiskLevel.R2)
    graph = runtime.graph_runtime

    updates = [
        update
        async for update in graph.stream_start(
            flow_id="approval-run",
            task=audit_task(),
        )
    ]
    assert "__interrupt__" in updates[-1]
    active = await graph.active_interrupt("approval-run")
    assert active is not None
    approval_id = active["approval_id"]
    assert runtime.state("approval-run").status.value == "waiting_approval"

    resumed = [
        update
        async for update in graph.stream_resume(
            flow_id="approval-run",
            response={
                "approval_id": approval_id,
                "approved": True,
                "reason": "authorized by test",
            },
        )
    ]

    assert any("approval" in update for update in resumed)
    assert runtime.state("approval-run").status.value == "completed"
    assert await graph.active_interrupt("approval-run") is None
    assert tool.calls == 1


@pytest.mark.asyncio
async def test_failed_idempotent_tool_routes_through_reflect_and_retries(tmp_path: Path) -> None:
    runtime, tool, _ = build_runtime(
        tmp_path,
        outcomes=[ToolStatus.ERROR, ToolStatus.SUCCESS],
    )

    state = await runtime.run_inline(audit_task(), "retry-run")

    assert state.status.value == "completed"
    assert state.retry_counts == {"audit-python-bandit": 1}
    assert state.reflection_count == 1
    assert state.budget.steps_used == 2
    assert state.budget.tool_calls_used == 2
    assert tool.calls == 2
    event_types = [event.event_type for event in runtime.ledger.events("retry-run")]
    assert "reflection.completed" in event_types


@pytest.mark.asyncio
async def test_graph_checkpoint_references_authoritative_runtime_state(tmp_path: Path) -> None:
    runtime, _, _ = build_runtime(tmp_path)

    state = await runtime.run_inline(audit_task(), "single-owner-run")
    state.opened_circuit_keys = ["server:restored-server"]
    state.unavailable_server_ids = ["restored-server"]
    state.unavailable_tool_ids = ["mcp:restored-server:scan"]
    runtime.ledger.save_state(state)
    snapshot = await runtime.graph_runtime.snapshot("single-owner-run")
    restored = runtime.ledger.load_state("single-owner-run")

    assert snapshot["run_id"] == state.run_id
    assert snapshot["state_revision"] == state.state_revision
    assert "runtime_state" not in snapshot
    assert restored is not None
    assert restored.completion_gate_result == state.completion_gate_result
    assert restored.completion_gate_passed == state.completion_gate_passed
    assert restored.opened_circuit_keys == ["server:restored-server"]
    assert restored.unavailable_server_ids == ["restored-server"]
    assert restored.unavailable_tool_ids == ["mcp:restored-server:scan"]


@pytest.mark.asyncio
async def test_idempotent_tool_retry_count_is_strictly_bounded(tmp_path: Path) -> None:
    runtime, tool, _ = build_runtime(
        tmp_path,
        outcomes=[ToolStatus.ERROR, ToolStatus.ERROR, ToolStatus.ERROR, ToolStatus.SUCCESS],
        plan_max_attempts=3,
    )

    state = await runtime.run_inline(audit_task(), "bounded-tool-retry-run")

    assert state.status == RunStatus.PARTIAL
    assert state.retry_counts == {"audit-python-bandit": 2}
    assert state.reflection_count == 2
    assert tool.calls == 3


@pytest.mark.asyncio
async def test_non_idempotent_tool_is_never_retried(tmp_path: Path) -> None:
    runtime, tool, _ = build_runtime(
        tmp_path,
        outcomes=[ToolStatus.ERROR, ToolStatus.SUCCESS],
        idempotent=False,
        plan_max_attempts=3,
    )

    state = await runtime.run_inline(audit_task(), "non-idempotent-tool-run")

    assert state.status == RunStatus.PARTIAL
    assert state.retry_counts == {}
    assert state.reflection_count == 0
    assert tool.calls == 1


@pytest.mark.asyncio
async def test_transient_model_failure_uses_bounded_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, _, model = build_runtime(tmp_path)
    state = runtime.new_state(audit_task(), "bounded-model-retry-run")
    runtime.ledger.save_state(state)
    calls = 0

    async def flaky_complete(messages: list[Any], **kwargs: Any) -> LLMResponse:
        nonlocal calls
        del messages, kwargs
        calls += 1
        if calls == 1:
            raise ProviderHTTPError(503, {"message": "temporary outage"})
        return LLMResponse(content="recovered", model="controlled-model", provider="controlled")

    monkeypatch.setattr(model, "complete", flaky_complete)
    result = await runtime._call_model(
        state,
        stage="test",
        system="test",
        payload={},
        max_tokens=10,
    )

    assert result == "recovered"
    assert calls == 2
    assert state.budget.model_calls_used == 2
    assert any(item.decision == "retry_model_test" for item in state.decisions)


@pytest.mark.asyncio
async def test_permanent_model_failure_degrades_without_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, _, model = build_runtime(tmp_path)
    state = runtime.new_state(audit_task(), "model-fallback-run")
    runtime.ledger.save_state(state)
    calls = 0

    async def invalid_request(messages: list[Any], **kwargs: Any) -> LLMResponse:
        nonlocal calls
        del messages, kwargs
        calls += 1
        raise ProviderHTTPError(400, {"message": "invalid request"})

    monkeypatch.setattr(model, "complete", invalid_request)
    result = await runtime._call_model(
        state,
        stage="test",
        system="test",
        payload={},
        max_tokens=10,
    )

    assert result is None
    assert calls == 1
    assert state.budget.model_calls_used == 1
    fallback = next(item for item in state.decisions if item.decision == "model_test_fallback")
    assert fallback.model_id == "deterministic-test-ProviderHTTPError-after-1-attempts-fallback"


@pytest.mark.asyncio
async def test_model_budget_caps_managed_calls(tmp_path: Path) -> None:
    runtime, _, model = build_runtime(tmp_path, max_model_calls=2)

    state = await runtime.run_inline(audit_task(), "model-budget-run")

    assert state.status.value == "completed"
    assert state.budget.model_calls_used == 2
    assert model.stages == ["universal_primary", "plan"]
    assert state.report is not None
    assert state.report.executive_summary == "Universal Primary completed."


@pytest.mark.asyncio
async def test_structured_runtime_output_retries_reasoning_only_with_stage_override(
    tmp_path: Path,
) -> None:
    runtime, _, model = build_runtime(tmp_path)
    runtime.settings.llm_primary_thinking_enabled = True
    state = runtime.new_state(audit_task(), "structured-runtime-run")
    responses = [
        LLMResponse(
            content="",
            model="controlled-model",
            provider="controlled",
            finish_reason="length",
            empty_content_reason=EmptyContentReason.LENGTH_REASONING_ONLY,
        ),
        LLMResponse(
            content=json.dumps(
                {
                    "status": "success",
                    "final_answer": None,
                    "executive_summary": "Structured result recovered.",
                    "findings": [],
                    "evidence_gaps": [],
                    "confidence": 0.9,
                    "limitations": [],
                }
            ),
            model="controlled-model",
            provider="controlled",
        ),
    ]
    requests: list[dict[str, Any]] = []

    async def complete(messages: list[Any], **kwargs: Any) -> LLMResponse:
        del messages
        requests.append(kwargs.copy())
        return responses.pop(0)

    model.complete = complete  # type: ignore[method-assign]
    result = await runtime._call_model(
        state,
        stage="universal_primary",
        system="Return one structured result.",
        payload={"objective": "test"},
        max_tokens=100,
        response_model=UniversalPrimaryResult,
    )

    assert isinstance(result, UniversalPrimaryResult)
    assert result.executive_summary == "Structured result recovered."
    assert requests[0]["thinking_enabled"] is True
    assert requests[1]["thinking_enabled"] is False
    assert "reasoning_effort" not in requests[1]
    assert state.budget.model_calls_used == 2


@pytest.mark.asyncio
async def test_prompt_budget_blocks_oversized_model_request(tmp_path: Path) -> None:
    runtime, _, model = build_runtime(tmp_path)
    state = runtime.new_state(audit_task(), "prompt-budget-run")
    state.budget.max_single_prompt_tokens = 1

    result = await runtime._call_model(
        state,
        stage="plan",
        system="This prompt cannot fit the configured budget.",
        payload={"objective": "test"},
        max_tokens=10,
    )

    assert result is None
    assert model.stages == []
    assert state.budget.model_calls_used == 0
    assert state.budget.max_prompt_tokens_seen > 1
    assert any(item.decision == "model_plan_fallback" for item in state.decisions)


def test_runtime_profile_is_explicit_or_deterministically_classified(tmp_path: Path) -> None:
    runtime, _, _ = build_runtime(tmp_path)
    explicit = runtime.new_state(
        TaskRequest(objective="small task", complexity_profile=TaskComplexity.SIMPLE),
        "explicit-profile-run",
    )
    assert explicit.budget.complexity_profile == TaskComplexity.SIMPLE
    assert explicit.budget.max_agents == 6
    assert explicit.budget.max_runtime_seconds == 120

    large = runtime.new_state(TaskRequest(objective="audit repository"), "large-profile-run")
    large.input_artifacts = [
        InputArtifact(
            original_name=f"file-{index}.py",
            relative_path=f"src/file-{index}.py",
            sha256=f"{index:064x}",
            size_bytes=100,
            media_type="text/x-python",
        )
        for index in range(332)
    ]
    large.capability_plan = CapabilityPlan(
        task_kind="code_audit",
        status=CapabilityStatus.READY,
        allowed_tool_ids=["native:bandit_python_audit"],
    )
    assert runtime._classify_complexity(large) == TaskComplexity.COMPLEX


@pytest.mark.asyncio
async def test_hard_collaboration_deadline_persists_inconclusive_checkpoint(
    tmp_path: Path,
) -> None:
    runtime, _, _ = build_runtime(tmp_path)
    state = runtime.new_state(TaskRequest(objective="long task"), "deadline-run")
    now = datetime.now(UTC)
    state.soft_deadline_at = now - timedelta(seconds=1)
    state.tool_grace_deadline_at = now + timedelta(milliseconds=10)
    state.hard_deadline_at = now + timedelta(milliseconds=50)

    async def never_finishes(current: Any, review_round: int) -> dict[str, Any]:
        del current, review_round
        await asyncio.sleep(10)
        return {}

    runtime.set_collaboration_runner(never_finishes)
    updated = await runtime.node_collaborate(state)

    assert updated.status == RunStatus.PARTIAL
    assert updated.hard_deadline_reached is True
    assert updated.collaboration_completed is True
    assert updated.receipts[-1].status == UnitOutcomeStatus.INCONCLUSIVE
    assert updated.receipts[-1].error_type == "CollaborationTimeout"
    assert runtime.state("deadline-run").hard_deadline_reached is True


@pytest.mark.asyncio
async def test_tool_budget_prevents_retry_route(tmp_path: Path) -> None:
    runtime, tool, _ = build_runtime(
        tmp_path,
        outcomes=[ToolStatus.ERROR, ToolStatus.SUCCESS],
        max_tool_calls=1,
    )

    state = await runtime.run_inline(audit_task(), "tool-budget-run")

    assert state.status.value == "partial"
    assert state.budget.tool_calls_used == 1
    assert state.reflection_count == 0
    assert tool.calls == 1


@pytest.mark.asyncio
async def test_plan_analyze_verify_and_report_use_managed_model(tmp_path: Path) -> None:
    runtime, _, model = build_runtime(tmp_path)

    state = await runtime.run_inline(audit_task(), "model-stages-run")

    assert state.status.value == "completed"
    assert model.stages == ["universal_primary", "plan", "analyze", "verify", "report"]
    assert state.report is not None
    assert state.report.executive_summary == "controlled report output"


@pytest.mark.asyncio
async def test_finding_task_rejects_successful_tool_with_empty_evidence(tmp_path: Path) -> None:
    runtime, _, _ = build_runtime(tmp_path, emit_finding=False)

    state = await runtime.run_inline(audit_task(), "empty-evidence-run")

    assert state.status == RunStatus.PARTIAL
    assert state.verification_passed is True
    assert state.completion_gate_passed is False
    assert state.review_round == 2
    assert state.review_converged is True
    assert state.completion_gate_reason is not None
    assert "missing expected output(s): findings, evidence" in state.completion_gate_reason


@pytest.mark.asyncio
async def test_completion_gate_rejects_evidence_not_in_verified_delta(tmp_path: Path) -> None:
    runtime, _, _ = build_runtime(tmp_path)
    state = runtime.new_state(
        audit_task(expected_outputs=["evidence"], required_evidence=["evidence"]),
        "unverified-evidence-run",
    )
    evidence = Evidence(
        evidence_id="unverified-evidence",
        source="test",
        summary="Recorded but never independently verified",
    )
    state.evidence = [evidence]
    state.findings = [
        Finding(
            finding_id="unverified-finding",
            rule_id="TEST-UNVERIFIED",
            path="test.py",
            title="Unverified finding",
            description="The evidence reference exists but has no verification delta.",
            evidence_ids=[evidence.evidence_id],
        )
    ]
    state.review_converged = True
    state.verification_attempted = True
    state.verification_completed = True
    state.verification_passed = True
    state.status = RunStatus.RUNNING
    runtime.ledger.save_state(state)

    updated = await runtime.node_completion_gate(state)

    assert updated.status == RunStatus.PARTIAL
    assert updated.verification_passed is True
    assert updated.completion_gate_passed is False
    assert updated.completion_gate_checks["evidence_closure"] is False
    assert updated.completion_gate_reason == "Evidence reference closure was not satisfied"


@pytest.mark.asyncio
async def test_completion_gate_rejects_run_when_verify_was_not_attempted(tmp_path: Path) -> None:
    runtime, _, _ = build_runtime(tmp_path)
    state = runtime.new_state(audit_task(), "verify-not-attempted-run")
    state.review_converged = True
    state.status = RunStatus.RUNNING

    updated = await runtime.node_completion_gate(state)

    assert updated.status == RunStatus.PARTIAL
    assert updated.verification_attempted is False
    assert updated.completion_gate_passed is False
    assert updated.completion_gate_reason == "Verify stage was not attempted"


@pytest.mark.asyncio
async def test_completion_gate_rejects_incomplete_evaluator_prerequisite(
    tmp_path: Path,
) -> None:
    runtime, _, _ = build_runtime(tmp_path)
    state = runtime.new_state(
        audit_task(
            expected_outputs=["final_answer"],
            required_evidence=["final_answer", "independent_verification"],
            completion_mode="final_answer",
            evaluator="manual_no_verified_evidence",
        ),
        "evaluator-not-ready-run",
    )
    evidence = Evidence(
        evidence_id="answer-evidence",
        source="test",
        summary="Evidence for an independently checked answer",
    )
    state.evidence = [evidence]
    state.final_answer = "answer-42"
    state.final_answer_evidence_ids = [evidence.evidence_id]
    state.final_answer_source_agent_id = "answer-agent"
    state.final_answer_verified = True
    state.verification_attempted = True
    state.verification_completed = True
    state.verification_passed = True
    state.review_converged = True
    state.verified_deltas = [
        VerificationDelta(
            source="independent-verifier",
            evidence_ids=[evidence.evidence_id],
            final_answer_verified=True,
            verifier_agent_instance_id="verifier-agent",
            answer_source_agent_id="answer-agent",
        )
    ]
    state.status = RunStatus.RUNNING

    updated = await runtime.node_completion_gate(state)

    assert updated.status == RunStatus.PARTIAL
    assert updated.completion_gate_passed is False
    assert updated.completion_gate_checks["evaluator:manual_no_verified_evidence"] is False
    assert updated.completion_gate_reason == (
        "Task evaluator prerequisite was not satisfied: manual_no_verified_evidence"
    )


@pytest.mark.asyncio
async def test_collaboration_products_share_identity_and_enter_report(tmp_path: Path) -> None:
    runtime, _, _ = build_runtime(tmp_path)
    calls: list[tuple[str | None, str, str | None, int]] = []

    async def collaboration(state: Any, review_round: int) -> dict[str, Any]:
        calls.append((state.flow_id, state.run_id, state.task_id, review_round))
        return {
            "agent_result": {
                "agent_instance_id": f"agent-{review_round}",
                "task_id": state.task_id,
                "status": "completed",
                "summary": f"review {review_round}",
                "data": {},
                "artifact_refs": ["artifact-1"],
                "evidence_ids": ["collab-evidence"],
                "finding_ids": ["collab-finding"],
                "completed_at": f"2026-07-21T00:00:0{review_round}Z",
            },
            "artifacts": [{"artifact_id": "artifact-1", "uri": "sandbox://artifact-1"}],
            "evidence": [
                {
                    "evidence_id": "collab-evidence",
                    "source": "isolated-collaboration",
                    "summary": "verified collaboration evidence",
                }
            ],
            "findings": [
                {
                    "finding_id": "collab-finding",
                    "rule_id": "COLLAB-001",
                    "severity": "HIGH",
                    "confidence": "HIGH",
                    "path": "collab.py",
                    "line": 9,
                    "title": "Collaboration finding",
                    "description": "Finding returned by the collaboration network.",
                    "evidence_ids": ["collab-evidence"],
                }
            ],
            "tool_calls": [
                {
                    "invocation_id": "tool-call-1",
                    "tool_id": "sandbox:test",
                    "status": "completed",
                    "data": {},
                }
            ],
        }

    runtime.set_collaboration_runner(collaboration)
    state = await runtime.run_inline(
        audit_task(),
        "shared-run",
        flow_id="shared-flow",
        task_id="shared-task",
    )

    assert state.status == RunStatus.COMPLETED
    assert calls == [
        ("shared-flow", "shared-run", "shared-task", 1),
        ("shared-flow", "shared-run", "shared-task", 2),
    ]
    assert len(state.agent_results) == 2
    assert state.artifact_refs == ["artifact-1"]
    assert state.tool_call_ids == ["tool-call-1"]
    assert state.report is not None
    assert len(state.report.agent_results) == 2
    assert state.report.artifacts[0]["artifact_id"] == "artifact-1"
    assert state.report.tool_calls[0]["invocation_id"] == "tool-call-1"
    assert any(
        item.finding_ids == ["collab-finding"] for item in state.verified_deltas
    )
    assert {item.unit_type for item in state.receipts} >= {
        "agent",
        "tool",
        "verification",
    }
    assert state.report.verified_deltas == state.verified_deltas
    assert state.report.receipts == state.receipts


@pytest.mark.asyncio
async def test_answer_task_requires_answer_and_verification_result(tmp_path: Path) -> None:
    runtime, _, _ = build_runtime(tmp_path)

    async def collaboration(state: Any, review_round: int) -> dict[str, Any]:
        del state
        evidence_id = "answer-evidence"
        return {
            "agent_result": {
                "agent_instance_id": f"answer-agent-{review_round}",
                "task_id": "answer-task",
                "status": "completed",
                "data": {
                    "final_answer": "answer-42",
                },
                "evidence_ids": [evidence_id],
            },
            "evidence": [
                {
                    "evidence_id": evidence_id,
                    "source": "answer-verifier",
                    "summary": "Independent answer verification output",
                }
            ],
            "tool_calls": [
                {
                    "invocation_id": f"answer-verifier-{review_round}",
                    "tool_id": "sandbox:answer-verifier",
                    "status": "completed",
                    "data": {
                        "verification_result": (
                            "verified" if review_round == 2 else "inconclusive"
                        )
                    },
                    "agent_instance_id": f"verifier-agent-{review_round}",
                    "evidence_ids": [evidence_id],
                }
            ],
        }

    runtime.set_collaboration_runner(collaboration)
    state = await runtime.run_inline(
        audit_task(expected_outputs=["final_answer"]),
        "answer-run",
        flow_id="answer-flow",
        task_id="answer-task",
    )

    assert state.status == RunStatus.COMPLETED
    assert state.final_answer == "answer-42"
    assert state.final_answer_verified is True
    assert state.final_answer_evidence_ids == ["answer-evidence"]
    assert state.completion_gate_passed is True
    assert state.report is not None
    assert state.report.final_answer == "answer-42"


@pytest.mark.asyncio
async def test_successful_answer_tool_cannot_bypass_missing_contract_outputs(
    tmp_path: Path,
) -> None:
    runtime, _, _ = build_runtime(tmp_path, emit_finding=False)

    async def collaboration(state: Any, review_round: int) -> dict[str, Any]:
        return {
            "agent_result": {
                "agent_instance_id": f"answer-agent-{review_round}",
                "task_id": state.task_id,
                "status": "completed",
                "data": {"final_answer": "answer-without-proof"},
            },
            "tool_calls": [
                {
                    "invocation_id": f"answer-verifier-{review_round}",
                    "tool_id": "sandbox:answer-verifier",
                    "status": "completed",
                    "data": {"verification_result": "verified"},
                }
            ],
        }

    runtime.set_collaboration_runner(collaboration)
    state = await runtime.run_inline(
        audit_task(
            expected_outputs=["final_answer", "evidence", "reproduction_steps"],
            completion_mode="final_answer",
        ),
        "missing-contract-output-run",
        task_id="missing-contract-output-task",
    )

    assert state.status == RunStatus.PARTIAL
    assert state.final_answer_verified is False
    assert state.completion_gate_passed is False
    assert state.completion_gate_checks["output:evidence"] is False
    assert state.completion_gate_checks["output:reproduction_steps"] is False
    assert state.completion_gate_reason == (
        "Task contract missing expected output(s): evidence, reproduction_steps"
    )


@pytest.mark.asyncio
async def test_complete_answer_contract_requires_outputs_evidence_and_evaluator(
    tmp_path: Path,
) -> None:
    runtime, _, _ = build_runtime(tmp_path)

    async def collaboration(state: Any, review_round: int) -> dict[str, Any]:
        evidence_id = f"answer-evidence-{review_round}"
        return {
            "agent_result": {
                "agent_instance_id": f"complete-answer-agent-{review_round}",
                "task_id": state.task_id,
                "status": "completed",
                "data": {
                    "final_answer": "verified-answer",
                    "reproduction_steps": ["Run the supplied verifier", "Compare its output"],
                },
                "evidence_ids": [evidence_id],
            },
            "evidence": [
                {
                    "evidence_id": evidence_id,
                    "source": "answer-verifier",
                    "summary": "Independent answer verification output",
                }
            ],
            "tool_calls": [
                {
                    "invocation_id": f"complete-answer-verifier-{review_round}",
                    "tool_id": "sandbox:answer-verifier",
                    "status": "completed",
                    "data": {"verification_result": "verified"},
                    "evidence_ids": [evidence_id],
                }
            ],
        }

    runtime.set_collaboration_runner(collaboration)
    state = await runtime.run_inline(
        audit_task(
            expected_outputs=["final_answer", "evidence", "reproduction_steps"],
            completion_mode="final_answer",
            evaluator="final_answer_independent_verification",
        ),
        "complete-answer-contract-run",
        task_id="complete-answer-contract-task",
    )

    assert state.status == RunStatus.COMPLETED
    assert all(state.completion_gate_checks.values())
    assert state.task_contract is not None
    assert state.report is not None
    assert state.report.task_contract == state.task_contract
    assert state.report.reproduction_steps == [
        "Run the supplied verifier",
        "Compare its output",
    ]
    summary = runtime.summary(state.run_id)
    assert summary.task_contract == state.task_contract
    assert summary.completion_gate_checks == state.completion_gate_checks


@pytest.mark.asyncio
async def test_agent_result_cannot_self_verify_final_answer(tmp_path: Path) -> None:
    runtime, _, _ = build_runtime(tmp_path)

    async def collaboration(state: Any, review_round: int) -> dict[str, Any]:
        return {
            "agent_result": {
                "agent_instance_id": f"self-verifying-agent-{review_round}",
                "task_id": state.task_id,
                "status": "completed",
                "data": {
                    "final_answer": "untrusted-answer",
                    "final_answer_verified": True,
                },
            }
        }

    runtime.set_collaboration_runner(collaboration)
    state = await runtime.run_inline(
        audit_task(expected_outputs=["final_answer"]),
        "untrusted-answer-run",
        task_id="untrusted-answer-task",
    )

    assert state.status == RunStatus.PARTIAL
    assert state.final_answer == "untrusted-answer"
    assert state.final_answer_verified is False


@pytest.mark.asyncio
async def test_second_review_new_finding_prevents_completion(tmp_path: Path) -> None:
    runtime, _, _ = build_runtime(tmp_path)

    async def collaboration(state: Any, review_round: int) -> dict[str, Any]:
        if review_round == 1:
            return {
                "agent_result": {
                    "agent_instance_id": "first",
                    "task_id": "task",
                    "status": "completed",
                }
            }
        return {
            "agent_result": {
                "agent_instance_id": "second",
                "task_id": "task",
                "status": "completed",
            },
            "evidence": [
                {
                    "evidence_id": "new-evidence",
                    "source": "secondary-review",
                    "summary": "new evidence",
                }
            ],
            "findings": [
                {
                    "finding_id": "new-finding",
                    "rule_id": "SECOND-001",
                    "severity": "HIGH",
                    "confidence": "HIGH",
                    "path": "new.py",
                    "title": "New secondary finding",
                    "description": "Only found during the second review.",
                    "evidence_ids": ["new-evidence"],
                }
            ],
        }

    runtime.set_collaboration_runner(collaboration)
    state = await runtime.run_inline(audit_task(), "new-finding-run")

    assert state.status == RunStatus.PARTIAL
    assert state.review_round == 2
    assert state.review_converged is False
    assert state.completion_gate_passed is False


@pytest.mark.asyncio
async def test_execute_node_reuses_completed_execution_key(tmp_path: Path) -> None:
    runtime, tool, _ = build_runtime(tmp_path)
    state = runtime.new_state(audit_task(), "idempotent-run")
    state.status = RunStatus.RUNNING
    state.scenario = Scenario.CODE_AUDIT
    state.workspace = str(tmp_path)
    state.plan = [
        PlanStep(
            step_id="audit-python-bandit",
            objective="Run the controlled audit tool.",
            agent_role="executor",
            tool_candidates=["bandit_python_audit"],
            inputs={"target": "."},
            max_attempts=2,
        )
    ]
    state.active_step_id = "audit-python-bandit"
    runtime.ledger.save_state(state)

    first = await runtime.node_execute(state)
    second = await runtime.node_execute(first.model_copy(deep=True))

    assert tool.calls == 1
    assert second.budget.tool_calls_used == 1
    assert len(second.observations) == 1
    assert any(
        event.event_type == "tool.replayed"
        for event in runtime.ledger.events("idempotent-run")
    )


@pytest.mark.asyncio
async def test_universal_primary_is_language_agnostic(tmp_path: Path) -> None:
    runtime, _, model = build_runtime(tmp_path)

    state = await runtime.run_inline(
        TaskRequest(
            objective="Provide a final answer for this repository-independent logic task",
            expected_outputs=["final_answer"],
        ),
        "universal-primary-run",
    )

    assert model.stages[0] == "universal_primary"
    assert state.primary_persisted is True
    assert state.primary_result is not None
    assert state.report is not None
    assert state.report.primary_result == state.primary_result


@pytest.mark.asyncio
async def test_missing_required_capability_stops_before_model_call(tmp_path: Path) -> None:
    runtime, _, model = build_runtime(tmp_path)

    state = await runtime.run_inline(
        TaskRequest(
            objective="Exploit this pwn binary and return the flag",
            expected_outputs=["final_answer"],
        ),
        "missing-pwn-capability",
    )

    assert model.stages == []
    assert state.status == RunStatus.PARTIAL
    assert state.capability_plan is not None
    assert state.capability_plan.status == CapabilityStatus.UNAVAILABLE
    assert state.primary_result is not None
    assert state.primary_result.status == UnitOutcomeStatus.CAPABILITY_UNAVAILABLE
    assert state.report is not None
    assert state.report.executive_summary == state.primary_result.executive_summary


@pytest.mark.asyncio
async def test_tool_exception_is_isolated_and_preserves_primary_answer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, _, _ = build_runtime(tmp_path)
    state = runtime.new_state(audit_task(expected_outputs=["final_answer"]), "tool-exception")
    state.workspace = str(tmp_path)
    state.scenario = Scenario.CODE_AUDIT
    state.classification_completed = True
    state.capability_plan = CapabilityPlan(
        task_kind="code_audit",
        languages=["python"],
        status=CapabilityStatus.READY,
    )
    state.primary_result = UniversalPrimaryResult(
        status=UnitOutcomeStatus.SUCCESS,
        final_answer="primary-answer",
        executive_summary="Primary answer exists before tools run.",
        confidence=0.6,
    )
    state.primary_persisted = True
    state.final_answer = "primary-answer"
    state.plan = [
        PlanStep(
            step_id="audit-python-bandit",
            objective="Run isolated tool",
            agent_role="executor",
            tool_candidates=["bandit_python_audit"],
            inputs={"target": "."},
        )
    ]
    state.active_step_id = "audit-python-bandit"
    runtime.ledger.save_state(state)

    async def explode(*_args: Any, **_kwargs: Any) -> RuntimeToolResult:
        raise RuntimeError("isolated tool crash")

    monkeypatch.setattr(runtime.broker, "invoke", explode)
    updated = await runtime.node_execute(state)

    assert updated.final_answer == "primary-answer"
    assert updated.observations[-1].status == ToolStatus.ERROR
    assert updated.receipts[-1].unit_type == "tool"
    assert updated.receipts[-1].status == UnitOutcomeStatus.FAILED


@pytest.mark.asyncio
async def test_missing_workspace_chunk_has_independent_receipt(tmp_path: Path) -> None:
    runtime, _, _ = build_runtime(tmp_path)
    state = runtime.new_state(audit_task(), "missing-workspace-chunk")
    state.workspace = str(tmp_path)
    state.capability_plan = CapabilityPlan(
        task_kind="code_audit",
        languages=["python"],
        status=CapabilityStatus.READY,
    )
    state.input_artifacts = [
        InputArtifact(
            original_name="missing.py",
            relative_path="missing.py",
            sha256="0" * 64,
            size_bytes=10,
            media_type="text/x-python",
        )
    ]
    runtime.ledger.save_state(state)

    updated = await runtime.node_universal_primary(state)

    receipt = next(item for item in updated.receipts if item.unit_id == "missing.py")
    assert receipt.unit_type == "workspace_chunk"
    assert receipt.status == UnitOutcomeStatus.FAILED
    assert updated.primary_persisted is True


@pytest.mark.asyncio
async def test_primary_prompt_uses_bounded_workspace_manifest(tmp_path: Path) -> None:
    runtime, _, _ = build_runtime(tmp_path)
    state = runtime.new_state(audit_task(), "bounded-primary-prompt")
    state.capability_plan = CapabilityPlan(
        task_kind="code_audit",
        languages=["python"],
        status=CapabilityStatus.READY,
    )
    state.input_artifacts = [
        InputArtifact(
            original_name=f"file-{index}.py",
            relative_path=f"src/file-{index}.py",
            sha256=f"{index:064x}"[-64:],
            size_bytes=1_000,
            media_type="text/x-python",
        )
        for index in range(332)
    ]
    captured: dict[str, Any] = {}

    async def capture_model(_state: Any, **kwargs: Any) -> UniversalPrimaryResult:
        captured.update(kwargs)
        return UniversalPrimaryResult(
            status=UnitOutcomeStatus.SUCCESS,
            final_answer="unverified primary candidate",
            executive_summary="bounded",
        )

    runtime._call_model = capture_model  # type: ignore[method-assign]
    updated = await runtime.node_universal_primary(state)

    manifest = captured["payload"]["workspace_manifest"]
    assert manifest["file_count"] == 332
    assert len(manifest["files"]) == 64
    assert manifest["omitted_file_count"] == 268
    assert all("content" not in item for item in manifest["files"])
    assert len(json.dumps(captured["payload"], ensure_ascii=False)) < 32_000 * 4
    assert updated.primary_result is not None
    assert updated.final_answer is None


@pytest.mark.asyncio
async def test_report_prompt_projects_large_findings_without_raw_payload(tmp_path: Path) -> None:
    runtime, _, _ = build_runtime(tmp_path)
    state = runtime.new_state(audit_task(), "bounded-report-prompt")
    state.status = RunStatus.PARTIAL
    state.findings = [
        Finding(
            rule_id=f"RULE-{index}",
            severity="HIGH" if index < 5 else "MEDIUM",
            confidence="HIGH",
            path=f"src/file-{index}.py",
            line=index + 1,
            title=f"Finding {index}",
            description="A bounded finding description.",
            remediation="Apply the recommended fix.",
            evidence_ids=[f"evidence-{index}"],
            raw={"large_code": "x" * 20_000},
        )
        for index in range(275)
    ]
    captured: dict[str, Any] = {}

    async def capture_model(_state: Any, **kwargs: Any) -> str:
        captured.update(kwargs)
        return "bounded report"

    runtime._call_model = capture_model  # type: ignore[method-assign]
    updated = await runtime.node_report(state)

    projection = captured["payload"]["findings_projection"]
    assert projection["finding_summary"]["reported_count"] == 275
    assert projection["finding_summary"]["included_count"] <= 20
    assert projection["projection"]["source_sha256"]
    assert all("raw" not in item for item in projection["findings"])
    assert all("evidence_ids" in item for item in projection["findings"])
    assert "large_code" not in json.dumps(captured["payload"], ensure_ascii=False)
    assert len(json.dumps(captured["payload"], ensure_ascii=False)) < 32_000 * 4
    assert updated.report is not None
    assert updated.report.executive_summary == "bounded report"
