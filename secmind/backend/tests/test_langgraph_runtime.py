from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from langgraph.checkpoint.memory import MemorySaver

from agents.guardrail import Guardrail
from app.core.config import Settings
from app.schemas.runtime import (
    PlanStep,
    RiskLevel,
    RunStatus,
    RuntimeToolContext,
    RuntimeToolResult,
    Scenario,
    TaskRequest,
    ToolManifest,
    ToolStatus,
)
from app.services.runtime import RuntimeEventHub, RuntimeRunService
from ledger.runtime_store import RuntimeLedgerStore
from llm.base import LLMResponse
from tools.runtime import RuntimeTool, RuntimeToolBroker, RuntimeToolRegistry


class ControlledModelManager:
    def __init__(self) -> None:
        self.stages: list[str] = []

    def metadata(self) -> dict[str, Any]:
        return {"configured": True, "name": "controlled", "model": "controlled-model"}

    async def complete(self, messages: list[Any], **kwargs: Any) -> LLMResponse:
        stage = str(kwargs["stage"])
        self.stages.append(stage)
        if stage == "plan":
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
                            "max_attempts": 2,
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

    async def invoke(
        self,
        args: dict[str, Any],
        context: RuntimeToolContext,
    ) -> RuntimeToolResult:
        del args, context
        index = min(self.calls, len(self.outcomes) - 1)
        status = self.outcomes[index]
        self.calls += 1
        return RuntimeToolResult(
            status=status,
            summary=f"controlled result {self.calls}",
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
) -> tuple[RuntimeRunService, ControlledTool, ControlledModelManager]:
    settings = Settings(
        data_dir=tmp_path / "data",
        runtime_database_url=f"sqlite:///{(tmp_path / 'runtime.db').as_posix()}",
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
    tool = ControlledTool(risk=risk, outcomes=outcomes, idempotent=idempotent)
    registry.register(tool)
    model = ControlledModelManager()
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
    return TaskRequest(objective="audit code with the controlled tool", **updates)


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
    active = graph.active_interrupt("approval-run")
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
    assert graph.active_interrupt("approval-run") is None
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
async def test_model_budget_caps_managed_calls(tmp_path: Path) -> None:
    runtime, _, model = build_runtime(tmp_path, max_model_calls=2)

    state = await runtime.run_inline(audit_task(), "model-budget-run")

    assert state.status.value == "completed"
    assert state.budget.model_calls_used == 2
    assert model.stages == ["plan", "analyze"]
    assert state.report is not None
    assert state.report.executive_summary.startswith("Code audit completed")


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
    assert model.stages == ["plan", "analyze", "verify", "report"]
    assert state.report is not None
    assert state.report.executive_summary == "controlled report output"


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
