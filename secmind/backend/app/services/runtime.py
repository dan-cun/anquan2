from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from agents.guardrail import GuardrailAction
from app.core.config import Settings
from app.schemas.runtime import (
    AgentReport,
    AgentState,
    ApprovalDecision,
    ApprovalRequest,
    ApprovalResponse,
    BudgetState,
    DecisionRecord,
    Finding,
    KnowledgeHit,
    PlanStep,
    RiskLevel,
    RunStatus,
    RunSummary,
    RuntimeToolContext,
    RuntimeToolResult,
    Scenario,
    TaskRequest,
    ToolStatus,
)
from app.services.ingest import IngestError, InputIngestor
from knowledge.models import VerifierAttestation
from ledger.runtime_store import RuntimeLedgerStore
from llm.base import LLMMessage
from llm.manager import LLMProviderManager
from tools.runtime import RuntimeToolBroker

if TYPE_CHECKING:
    from agents.langgraph_runtime import LangGraphRuntime
    from knowledge.service import QdrantKnowledgeService

Publisher = Callable[[dict[str, Any]], Awaitable[None] | None]


class RuntimeEventHub:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def publish(self, event: dict[str, Any]) -> None:
        async with self._lock:
            subscribers = tuple(self._subscribers.get(str(event["run_id"]), ()))
        for queue in subscribers:
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(event)

    @asynccontextmanager
    async def subscribe(self, run_id: str) -> AsyncIterator[asyncio.Queue[dict[str, Any]]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=500)
        async with self._lock:
            self._subscribers[run_id].add(queue)
        try:
            yield queue
        finally:
            async with self._lock:
                self._subscribers[run_id].discard(queue)


class RuntimeRunService:
    """Runtime state operations used as LangGraph nodes.

    Graph topology belongs to ``LangGraphRuntime``. This service owns deterministic
    policy, side effects, model calls, and durable audit events.
    """

    def __init__(
        self,
        settings: Settings,
        ledger: RuntimeLedgerStore,
        broker: RuntimeToolBroker,
        event_hub: RuntimeEventHub,
        llm_provider: LLMProviderManager,
        checkpointer: Any | None = None,
        checkpoint_namespace: str = "",
        knowledge_service: QdrantKnowledgeService | None = None,
    ) -> None:
        self.settings = settings
        self.ledger = ledger
        self.broker = broker
        self.event_hub = event_hub
        self.llm_provider = llm_provider
        self.ingestor = InputIngestor(settings)
        self._checkpointer = checkpointer
        self.checkpoint_namespace = checkpoint_namespace
        self.knowledge_service = knowledge_service
        self._graph_runtime: LangGraphRuntime | None = None
        self._tasks: set[asyncio.Task[Any]] = set()

    @property
    def graph_runtime(self) -> LangGraphRuntime:
        if self._graph_runtime is None:
            from agents.langgraph_runtime import LangGraphRuntime

            self._graph_runtime = LangGraphRuntime(
                self,
                checkpointer=self._checkpointer,
                checkpoint_namespace=self.checkpoint_namespace,
            )
        return self._graph_runtime

    def submit(self, task: TaskRequest) -> str:
        run_id = str(uuid4())
        state = self.new_state(task, run_id)
        self.ledger.save_state(state)
        self.ledger.append(run_id, "run.queued", {"objective": task.objective}, actor="api")
        self._spawn(self._start_state(state))
        return run_id

    async def prepare_run(self, task: TaskRequest, run_id: str | None = None) -> AgentState:
        state = self.new_state(task, run_id or str(uuid4()))
        self.ledger.save_state(state)
        await self._event(state, "run.queued", {"objective": task.objective}, actor="api")
        return state

    async def run_inline(self, task: TaskRequest, run_id: str | None = None) -> AgentState:
        state = await self.prepare_run(task, run_id)
        return await self._start_state(state)

    async def resume_inline(self, run_id: str, response: ApprovalResponse) -> AgentState:
        return await self.graph_runtime.invoke_resume(
            run_id=run_id,
            response=response.model_dump(mode="json"),
        )

    def submit_approval(self, run_id: str, response: ApprovalResponse) -> None:
        if self.ledger.load_state(run_id) is None:
            raise KeyError(run_id)
        self._spawn(self.resume_inline(run_id, response))

    def state(self, run_id: str) -> AgentState:
        state = self.ledger.load_state(run_id)
        if state is None:
            raise KeyError(run_id)
        return state

    def summary(self, run_id: str) -> RunSummary:
        state = self.state(run_id)
        return RunSummary(
            run_id=run_id,
            status=state.status,
            scenario=state.scenario,
            current_step=state.current_step_index,
            total_steps=len(state.plan),
            active_step_id=state.active_step_id,
            verification_passed=state.verification_passed,
            state_revision=state.state_revision,
            pending_approval=state.pending_approval,
            last_error=state.last_error,
        )

    async def recover_incomplete(self) -> None:
        for run_id in self.ledger.incomplete_run_ids():
            state = self.ledger.load_state(run_id)
            if state and state.status not in {RunStatus.WAITING_APPROVAL, RunStatus.PENDING}:
                self._spawn(self._start_state(state))

    async def shutdown(self) -> None:
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def new_state(self, task: TaskRequest, run_id: str) -> AgentState:
        return AgentState(
            run_id=run_id,
            task=task,
            status=RunStatus.PENDING,
            budget=BudgetState(
                max_steps=self.settings.runtime_max_steps,
                max_tool_calls=self.settings.runtime_max_tool_calls,
                max_model_calls=self.settings.runtime_max_model_calls,
                max_runtime_seconds=self.settings.runtime_max_runtime_seconds,
            ),
        )

    async def _start_state(self, state: AgentState) -> AgentState:
        try:
            return await self.graph_runtime.invoke_state(state)
        except Exception as exc:
            state.status = RunStatus.FAILED
            state.last_error = f"{type(exc).__name__}: {exc}"
            await self._checkpoint(state, "run.failed", {"error": state.last_error})
            return state

    async def node_ingest(self, state: AgentState) -> AgentState:
        state.status = RunStatus.RUNNING
        try:
            workspace, artifacts = self.ingestor.ingest(state.run_id, state.task.attachments)
            state.workspace = str(workspace)
            state.input_artifacts = artifacts
        except IngestError as exc:
            state.status = RunStatus.FAILED
            state.last_error = str(exc)
        return await self._checkpoint(
            state,
            "input.ingested",
            {
                "artifact_count": len(state.input_artifacts),
                "artifact_hashes": [item.sha256 for item in state.input_artifacts],
                "error": state.last_error,
            },
        )

    async def node_classify(self, state: AgentState) -> AgentState:
        text = " ".join(
            [state.task.objective, *state.task.expected_outputs, *state.task.constraints]
        ).lower()
        suffixes = {
            artifact.relative_path.rsplit(".", 1)[-1].lower()
            for artifact in state.input_artifacts
        }
        if any(term in text for term in ("code", "audit", "bandit", "代码", "漏洞")) or (
            "py" in suffixes
        ):
            scenario = Scenario.CODE_AUDIT
        elif any(term in text for term in ("log", "日志")):
            scenario = Scenario.LOG_ANALYSIS
        elif any(term in text for term in ("incident", "应急")):
            scenario = Scenario.INCIDENT_RESPONSE
        elif any(term in text for term in ("penetration", "渗透")):
            scenario = Scenario.PENETRATION_TEST
        else:
            scenario = Scenario.UNKNOWN
        state.scenario = scenario
        state.decisions.append(
            DecisionRecord(
                decision=f"scenario={scenario.value}",
                rationale_summary=(
                    "Scenario selected from the operator objective and immutable input inventory."
                ),
                policy_ids=["ROUTE-SCENARIO-V1"],
                model_id="deterministic-router",
                prompt_version="v1",
            )
        )
        return await self._checkpoint(state, "scenario.classified", {"scenario": scenario})

    async def node_retrieve_context(self, state: AgentState) -> AgentState:
        source = "disabled"
        error_type = None
        if self.knowledge_service is not None:
            source = "qdrant"
            try:
                results = await asyncio.to_thread(
                    self.knowledge_service.search,
                    query=state.task.objective,
                    limit=5,
                )
                state.knowledge_hits = [
                    KnowledgeHit(
                        memory_id=item.document.id,
                        content=item.document.content,
                        source=str(item.document.metadata.get("source") or "qdrant"),
                        version=str(item.document.metadata.get("version") or "1"),
                        confidence=item.score,
                        metadata=item.document.metadata,
                    )
                    for item in results
                ]
            except Exception as error:
                source = "qdrant-error"
                error_type = type(error).__name__
                state.knowledge_hits = []
        return await self._checkpoint(
            state,
            "context.retrieved",
            {
                "hit_count": len(state.knowledge_hits),
                "source": source,
                "error_type": error_type,
            },
        )

    async def node_plan(self, state: AgentState) -> AgentState:
        fallback = self._fallback_plan(state)
        response = await self._call_model(
            state,
            stage="plan",
            system=(
                "Create a bounded security task plan as JSON with a steps array. Use only the "
                "allowed tool manifests. Do not include hidden reasoning."
            ),
            payload={
                "objective": state.task.objective,
                "scenario": state.scenario.value,
                "constraints": state.task.constraints,
                "knowledge_hits": [item.model_dump(mode="json") for item in state.knowledge_hits],
                "allowed_tools": [
                    item.model_dump(mode="json") for item in self.broker.registry.manifests()
                ],
            },
            max_tokens=1200,
        )
        plan = self._parse_plan(response) if response else None
        state.plan = plan if plan is not None else fallback
        source = "managed-llm" if plan is not None else "deterministic-fallback"
        state.decisions.append(
            DecisionRecord(
                decision="plan_created" if state.plan else "no_supported_plan",
                rationale_summary=(
                    "The plan is bounded by the registered tool manifests and runtime budget."
                    if state.plan
                    else "No executable plan is available for the selected scenario."
                ),
                policy_ids=["PLAN-BOUNDED-V1"],
                model_id=source,
                prompt_version="planner-v2",
            )
        )
        return await self._checkpoint(
            state,
            "plan.created",
            {
                "source": source,
                "steps": [item.model_dump(mode="json") for item in state.plan],
            },
        )

    async def node_validate_plan(self, state: AgentState) -> AgentState:
        errors: list[str] = []
        identifiers = [step.step_id for step in state.plan]
        identifier_set = set(identifiers)
        if len(identifiers) != len(identifier_set):
            errors.append("Plan step identifiers must be unique")
        if len(state.plan) > state.budget.max_steps:
            errors.append("Plan exceeds step budget")
        known_tools = {item.name for item in self.broker.registry.manifests()}
        for step in state.plan:
            if step.step_id in step.dependencies:
                errors.append(f"Self dependency in {step.step_id}")
            if not set(step.dependencies).issubset(identifier_set):
                errors.append(f"Unknown dependency in {step.step_id}")
            if not set(step.tool_candidates).issubset(known_tools):
                errors.append(f"Unknown tool in {step.step_id}")
        if errors:
            state.status = RunStatus.FAILED
            state.last_error = "; ".join(errors)
        return await self._checkpoint(state, "plan.validated", {"errors": errors})

    async def node_select_step(self, state: AgentState) -> tuple[AgentState, str]:
        if state.current_step_index >= len(state.plan):
            return await self._checkpoint(state, "step.selection_complete", {}), "report"
        elapsed = (datetime.now(UTC) - state.started_at).total_seconds()
        if elapsed >= state.budget.max_runtime_seconds:
            state.status = RunStatus.PARTIAL
            state.last_error = "Runtime budget exhausted"
            return await self._checkpoint(
                state, "budget.exhausted", {"budget": "runtime"}
            ), "report"
        if state.budget.steps_used >= state.budget.max_steps:
            state.status = RunStatus.PARTIAL
            state.last_error = "Step budget exhausted"
            return await self._checkpoint(
                state, "budget.exhausted", {"budget": "steps"}
            ), "report"
        step = state.plan[state.current_step_index]
        missing = [item for item in step.dependencies if item not in state.completed_step_ids]
        if missing:
            state.status = RunStatus.FAILED
            state.last_error = f"Step dependencies are incomplete: {', '.join(missing)}"
            return await self._checkpoint(
                state, "step.blocked", {"step_id": step.step_id, "missing": missing}
            ), "report"
        state.budget.steps_used += 1
        state.active_step_id = step.step_id
        return await self._checkpoint(
            state,
            "step.selected",
            {"step_id": step.step_id, "index": state.current_step_index},
        ), "guardrail"

    async def node_guardrail(self, state: AgentState) -> tuple[AgentState, str]:
        step = state.plan[state.current_step_index]
        if not step.tool_candidates:
            state.status = RunStatus.FAILED
            state.last_error = "Selected step has no tool candidate"
            return await self._checkpoint(
                state, "guardrail.denied", {"reason": state.last_error}
            ), "deny"
        tool_name = step.tool_candidates[0]
        approved = next(
            (
                item
                for item in reversed(state.approvals)
                if item.get("step_id") == step.step_id
                and item.get("decision")
                in {ApprovalDecision.APPROVE.value, ApprovalDecision.EDIT.value}
            ),
            None,
        )
        decision = self.broker.assess(tool_name, step.inputs, state.task.autonomy_policy)
        state.decisions.append(
            DecisionRecord(
                decision=f"guardrail={decision.action.value}",
                rationale_summary=decision.reason,
                policy_ids=list(decision.policy_ids),
                model_id="deterministic-guardrail",
            )
        )
        if decision.action == GuardrailAction.DENY:
            state.status = RunStatus.DENIED
            route = "deny"
        elif decision.action == GuardrailAction.REQUIRE_APPROVAL and approved is None:
            state.status = RunStatus.WAITING_APPROVAL
            state.pending_approval = ApprovalRequest(
                run_id=state.run_id,
                step_id=step.step_id,
                tool_name=tool_name,
                parameters=step.inputs,
                target=str(step.inputs.get("target", state.workspace)),
                risk_level=decision.risk_level,
                reason=decision.reason,
                expected_impact="Execute one bounded tool call inside the controlled workspace.",
            )
            route = "approval"
        else:
            route = "execute"
        return await self._checkpoint(
            state,
            "guardrail.evaluated",
            {
                "step_id": step.step_id,
                "action": decision.action,
                "risk_level": decision.risk_level,
                "policy_ids": decision.policy_ids,
            },
        ), route

    async def node_request_approval(self, state: AgentState) -> AgentState:
        pending = state.pending_approval
        if pending is None:
            state.status = RunStatus.FAILED
            state.last_error = "Approval node entered without a pending request"
            return await self._checkpoint(state, "approval.invalid", {})
        if not self._event_exists(
            state.run_id,
            "approval.requested",
            "request_id",
            pending.request_id,
        ):
            await self._event(
                state,
                "approval.requested",
                pending.model_dump(mode="json"),
            )
        self.ledger.save_state(state)
        return state

    async def node_resolve_approval(
        self,
        state: AgentState,
        raw_response: dict[str, Any],
    ) -> tuple[AgentState, str]:
        pending = state.pending_approval
        if pending is None:
            state.status = RunStatus.FAILED
            state.last_error = "Approval response has no active request"
            return await self._checkpoint(state, "approval.invalid", {}), "deny"
        response = self._approval_response(raw_response)
        state.approvals.append(
            {
                "request_id": pending.request_id,
                "step_id": pending.step_id,
                **response.model_dump(mode="json"),
            }
        )
        state.pending_approval = None
        if response.decision == ApprovalDecision.DENY:
            state.status = RunStatus.DENIED
            route = "deny"
        else:
            if (
                response.decision == ApprovalDecision.EDIT
                and response.edited_parameters is not None
            ):
                state.plan[state.current_step_index].inputs = response.edited_parameters
            state.status = RunStatus.RUNNING
            route = "execute"
        return await self._checkpoint(
            state,
            "approval.resolved",
            response.model_dump(mode="json"),
            actor=response.actor,
        ), route

    async def node_record_denial(self, state: AgentState) -> AgentState:
        if state.status != RunStatus.FAILED:
            state.status = RunStatus.DENIED
        return await self._checkpoint(
            state,
            "step.denied",
            {"step_id": state.active_step_id, "error": state.last_error},
        )

    async def node_execute(self, state: AgentState) -> AgentState:
        step = state.plan[state.current_step_index]
        tool_name = step.tool_candidates[0]
        attempt = state.retry_counts.get(step.step_id, 0) + 1
        execution_key = f"{state.run_id}:{step.step_id}:{attempt}"
        replayed = self._completed_execution(state.run_id, execution_key)
        if replayed is not None:
            if not state.observations or state.observations[-1] != replayed:
                state.observations.append(replayed)
            completed_keys = {
                str(event.payload.get("execution_key"))
                for event in self.ledger.events(state.run_id)
                if event.event_type == "tool.completed" and event.payload.get("execution_key")
            }
            state.budget.tool_calls_used = max(
                state.budget.tool_calls_used,
                len(completed_keys),
            )
            return await self._checkpoint(
                state,
                "tool.replayed",
                {"tool": tool_name, "execution_key": execution_key},
            )
        if state.budget.tool_calls_used >= state.budget.max_tool_calls:
            state.status = RunStatus.PARTIAL
            state.last_error = "Tool-call budget exhausted"
            return await self._checkpoint(state, "budget.exhausted", {"budget": "tools"})
        state.budget.tool_calls_used += 1
        await self._event(
            state,
            "tool.started",
            {
                "tool": tool_name,
                "tool_version": self.broker.registry.get(tool_name).manifest.version,
                "args": step.inputs,
                "step_id": step.step_id,
                "attempt": attempt,
                "execution_key": execution_key,
            },
        )
        result = await self.broker.invoke(
            tool_name,
            step.inputs,
            RuntimeToolContext(
                run_id=state.run_id,
                step_id=step.step_id,
                workspace=state.workspace,
                allowed_paths=[state.workspace],
            ),
        )
        state.observations.append(result)
        return await self._checkpoint(
            state,
            "tool.completed",
            {
                "tool": tool_name,
                "step_id": step.step_id,
                "attempt": attempt,
                "execution_key": execution_key,
                "status": result.status,
                "duration_ms": result.duration_ms,
                "evidence_ids": [item.evidence_id for item in result.evidence],
                "error_code": result.error_code,
                "result": result.model_dump(mode="json"),
            },
        )

    async def node_observe(self, state: AgentState) -> AgentState:
        if not state.observations:
            state.status = RunStatus.PARTIAL
            state.last_error = state.last_error or "Execution produced no observation"
            return await self._checkpoint(
                state, "observation.missing", {"error": state.last_error}
            )
        latest = state.observations[-1]
        return await self._checkpoint(
            state,
            "observation.recorded",
            {"status": latest.status, "summary": latest.summary},
        )

    async def node_analyze(self, state: AgentState) -> AgentState:
        if not state.observations:
            return state
        latest = state.observations[-1]
        if latest.status == ToolStatus.SUCCESS:
            known_evidence = {item.evidence_id for item in state.evidence}
            state.evidence.extend(
                item for item in latest.evidence if item.evidence_id not in known_evidence
            )
            known_findings = {item.finding_id for item in state.findings}
            for item in latest.data.get("findings", []):
                finding = Finding.model_validate(item)
                if finding.finding_id not in known_findings:
                    state.findings.append(finding)
        model_analysis = await self._call_model(
            state,
            stage="analyze",
            system=(
                "Summarize the supplied tool observation for an audit ledger. Use only supplied "
                "evidence and do not invent findings or include hidden reasoning."
            ),
            payload={
                "status": latest.status.value,
                "summary": latest.summary,
                "finding_count": len(state.findings),
                "evidence_ids": [item.evidence_id for item in latest.evidence],
            },
            max_tokens=300,
        )
        state.decisions.append(
            DecisionRecord(
                decision="tool_result_normalized",
                rationale_summary=model_analysis or latest.summary or "Tool result normalized.",
                evidence_ids=[item.evidence_id for item in latest.evidence],
                policy_ids=["EVIDENCE-REQUIRED-V1"],
                model_id="managed-llm" if model_analysis else "deterministic-evidence-analyzer",
                prompt_version="analysis-v2",
            )
        )
        return await self._checkpoint(
            state,
            "analysis.completed",
            {"finding_count": len(state.findings), "evidence_count": len(state.evidence)},
        )

    async def node_verify(self, state: AgentState) -> tuple[AgentState, str]:
        step = state.plan[state.current_step_index]
        latest = state.observations[-1]
        orphaned = [item.finding_id for item in state.findings if not item.evidence_ids]
        evidence_ids = {item.evidence_id for item in state.evidence}
        broken = [
            item.finding_id
            for item in state.findings
            if any(reference not in evidence_ids for reference in item.evidence_ids)
        ]
        deterministic_pass = latest.status == ToolStatus.SUCCESS and not orphaned and not broken
        model_verification = await self._call_model(
            state,
            stage="verify",
            system=(
                "Summarize this deterministic evidence validation result. You may not override "
                "the supplied pass value and must not include hidden reasoning."
            ),
            payload={
                "pass": deterministic_pass,
                "tool_status": latest.status.value,
                "orphaned_findings": orphaned,
                "broken_evidence_references": broken,
            },
            max_tokens=250,
        )
        state.verification_passed = deterministic_pass
        if deterministic_pass:
            state.last_error = None
            state.decisions.append(
                DecisionRecord(
                    decision="verification_passed",
                    rationale_summary=(
                        model_verification
                        or "All normalized findings reference captured tool evidence."
                    ),
                    evidence_ids=sorted(evidence_ids),
                    policy_ids=["EVIDENCE-REQUIRED-V1"],
                    model_id="managed-llm" if model_verification else "deterministic-verifier",
                    prompt_version="verify-v2",
                )
            )
            if step.step_id not in state.completed_step_ids:
                state.completed_step_ids.append(step.step_id)
            state.current_step_index += 1
            state.active_step_id = None
            route = "next" if state.current_step_index < len(state.plan) else "report"
        else:
            state.last_error = (
                "Verifier rejected the tool result or its evidence references"
            )
            state.decisions.append(
                DecisionRecord(
                    decision="verification_failed",
                    rationale_summary=model_verification or state.last_error,
                    policy_ids=["EVIDENCE-REQUIRED-V1"],
                    model_id="managed-llm" if model_verification else "deterministic-verifier",
                    prompt_version="verify-v2",
                )
            )
            attempts = state.retry_counts.get(step.step_id, 0)
            manifest = self.broker.registry.get(step.tool_candidates[0]).manifest
            can_retry = (
                manifest.idempotent
                and attempts + 1 < step.max_attempts
                and state.budget.steps_used < state.budget.max_steps
                and state.budget.tool_calls_used < state.budget.max_tool_calls
            )
            if can_retry:
                route = "reflect"
            else:
                state.status = RunStatus.PARTIAL
                route = "report"
        return await self._checkpoint(
            state,
            "verification.completed",
            {"step_id": step.step_id, "route": route, "error": state.last_error},
        ), route

    async def node_reflect(self, state: AgentState) -> AgentState:
        step = state.plan[state.current_step_index]
        state.retry_counts[step.step_id] = state.retry_counts.get(step.step_id, 0) + 1
        state.reflection_count += 1
        state.last_error = None
        state.decisions.append(
            DecisionRecord(
                decision="retry_step",
                rationale_summary=(
                    "The idempotent bounded tool call failed and has a remaining retry allowance."
                ),
                policy_ids=["RETRY-IDEMPOTENT-V1"],
                model_id="deterministic-reflector",
            )
        )
        return await self._checkpoint(
            state,
            "reflection.completed",
            {"step_id": step.step_id, "retry": state.retry_counts[step.step_id]},
        )

    async def node_report(self, state: AgentState) -> AgentState:
        successful = any(item.status == ToolStatus.SUCCESS for item in state.observations)
        if state.status in {RunStatus.DENIED, RunStatus.FAILED}:
            final_status = state.status
        elif state.scenario != Scenario.CODE_AUDIT or not successful:
            final_status = RunStatus.PARTIAL
        else:
            final_status = RunStatus.COMPLETED
        limitations: list[str] = []
        if state.scenario != Scenario.CODE_AUDIT:
            limitations.append("The selected scenario is not enabled in the MVP tool chain.")
        if not state.input_artifacts:
            limitations.append(
                "No input artifacts were supplied; the workspace may contain no analyzable code."
            )
        if state.last_error:
            limitations.append(state.last_error)
        fallback = (
            f"Code audit completed with {len(state.findings)} finding(s), supported by "
            f"{len(state.evidence)} evidence record(s)."
            if successful
            else "The task ended without a successful security-tool observation."
        )
        model_summary = await self._call_model(
            state,
            stage="report",
            system=(
                "Write a concise security audit executive summary in Chinese. Use only supplied "
                "evidence, do not invent findings, and do not include hidden reasoning."
            ),
            payload={
                "objective": state.task.objective,
                "status": final_status.value,
                "findings": [item.model_dump(mode="json") for item in state.findings],
                "limitations": limitations,
            },
            max_tokens=400,
        )
        state.status = final_status
        state.completed_at = datetime.now(UTC)
        state.report = AgentReport(
            run_id=state.run_id,
            status=final_status,
            executive_summary=model_summary or fallback,
            findings=state.findings,
            decisions=state.decisions,
            evidence=state.evidence,
            limitations=limitations,
        )
        return await self._checkpoint(
            state,
            "report.generated",
            {
                "status": state.status,
                "finding_count": len(state.findings),
                "evidence_count": len(state.evidence),
            },
        )

    async def node_memory_commit(self, state: AgentState) -> AgentState:
        accepted = state.status == RunStatus.COMPLETED and state.verification_passed is True
        candidate = await self._checkpoint(
            state,
            "memory.candidate",
            {
                "accepted": accepted,
                "reason": (
                    "Verified completed runs are eligible for episodic-memory curation."
                    if accepted
                    else "Only verified completed runs may enter long-term memory."
                ),
            },
        )
        if not accepted or self.knowledge_service is None or state.report is None:
            return candidate

        verification_events = [
            event
            for event in self.ledger.events(state.run_id, limit=1_000_000)
            if event.event_type == "verification.completed"
        ]
        if not verification_events:
            return candidate
        verification_event = verification_events[-1]
        try:
            document = await asyncio.to_thread(
                self.knowledge_service.commit_episodic_memory,
                title=f"Verified run {state.run_id}",
                content=state.report.executive_summary,
                run_id=state.run_id,
                verification=VerifierAttestation(
                    run_id=state.run_id,
                    verification_event_id=verification_event.event_id,
                    verifier_id="langgraph-verifier-v1",
                    verdict="verified",
                    evidence_ids=[item.evidence_id for item in state.evidence],
                ),
                metadata={"finding_count": len(state.findings)},
            )
        except Exception as error:
            return await self._checkpoint(
                state,
                "memory.commit_failed",
                {"error_type": type(error).__name__},
            )
        return await self._checkpoint(
            state,
            "memory.committed",
            {"document_id": document.id, "verification_event_id": verification_event.event_id},
        )

    async def node_preflight_denial(self, state: AgentState) -> AgentState:
        state.status = RunStatus.DENIED
        return await self._checkpoint(
            state,
            "approval.preflight_denied",
            {"reason": "Operator denied the preflight confirmation."},
        )

    def _fallback_plan(self, state: AgentState) -> list[PlanStep]:
        if state.scenario != Scenario.CODE_AUDIT:
            return []
        return [
            PlanStep(
                step_id="audit-python-bandit",
                objective="Scan the controlled workspace for Python security weaknesses.",
                agent_role="executor",
                tool_candidates=["bandit_python_audit"],
                inputs={"target": "."},
                success_criteria=[
                    "Bandit returns a valid structured result",
                    "Every reported finding has an evidence reference",
                ],
                risk_hint=RiskLevel.R1,
                max_attempts=2,
            )
        ]

    @staticmethod
    def _parse_plan(content: str) -> list[PlanStep] | None:
        try:
            cleaned = content.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0]
            body = json.loads(cleaned)
            raw_steps = body.get("steps") if isinstance(body, dict) else body
            if not isinstance(raw_steps, list):
                return None
            return [PlanStep.model_validate(item) for item in raw_steps]
        except (ValueError, TypeError, KeyError):
            return None

    async def _call_model(
        self,
        state: AgentState,
        *,
        stage: str,
        system: str,
        payload: dict[str, Any],
        max_tokens: int,
    ) -> str | None:
        metadata = self.llm_provider.metadata()
        if not metadata.get("configured"):
            return None
        if state.budget.model_calls_used >= state.budget.max_model_calls:
            return None
        state.budget.model_calls_used += 1
        messages = [
            LLMMessage(role="system", content=system, metadata={"stage": stage}),
            LLMMessage(
                role="user",
                content=json.dumps(payload, ensure_ascii=False),
                metadata={"stage": stage},
            ),
        ]
        provider_kwargs: dict[str, Any] = {
            "stage": stage,
            "temperature": 0.1,
            "max_tokens": max_tokens,
        }
        # Keep the existing usage API report-focused while preserving complete
        # stage I/O in explicit graph audit events.
        if stage == "report":
            provider_kwargs["run_id"] = state.run_id
        else:
            await self._event(
                state,
                f"model.{stage}.request",
                {
                    "messages": [item.model_dump(mode="json") for item in messages],
                    "parameters": provider_kwargs,
                },
                actor="llm_provider",
            )
        try:
            response = await self.llm_provider.complete(
                messages,
                **provider_kwargs,
            )
        except Exception as error:
            if stage != "report":
                await self._event(
                    state,
                    f"model.{stage}.error",
                    {"error_type": type(error).__name__, "error": str(error)},
                    actor="llm_provider",
                )
            state.decisions.append(
                DecisionRecord(
                    decision=f"model_{stage}_failed",
                    rationale_summary=(
                        f"Managed model call failed ({type(error).__name__}); fallback used."
                    ),
                    policy_ids=["MODEL-FALLBACK-V1"],
                    model_id=str(metadata.get("model") or metadata.get("name") or "unknown"),
                )
            )
            return None
        if stage != "report":
            await self._event(
                state,
                f"model.{stage}.response",
                {
                    "provider": response.provider,
                    "model": response.model,
                    "content": response.content,
                    "raw": response.raw,
                },
                actor="llm_provider",
            )
        return response.content.strip() or None

    @staticmethod
    def _approval_response(raw: dict[str, Any]) -> ApprovalResponse:
        if "decision" in raw:
            return ApprovalResponse.model_validate(raw)
        return ApprovalResponse(
            decision=(
                ApprovalDecision.APPROVE if bool(raw.get("approved")) else ApprovalDecision.DENY
            ),
            actor=str(raw.get("actor", "operator")),
            reason=str(raw.get("reason", "")),
            edited_parameters=raw.get("edited_parameters"),
        )

    def _completed_execution(
        self,
        run_id: str,
        execution_key: str,
    ) -> RuntimeToolResult | None:
        for event in reversed(self.ledger.events(run_id)):
            if (
                event.event_type == "tool.completed"
                and event.payload.get("execution_key") == execution_key
                and isinstance(event.payload.get("result"), dict)
            ):
                return RuntimeToolResult.model_validate(event.payload["result"])
        return None

    def _event_exists(
        self,
        run_id: str,
        event_type: str,
        field: str,
        value: Any,
    ) -> bool:
        return any(
            event.event_type == event_type and event.payload.get(field) == value
            for event in self.ledger.events(run_id)
        )

    async def _checkpoint(
        self,
        state: AgentState,
        event_type: str,
        payload: dict[str, Any],
        *,
        actor: str = "runtime",
    ) -> AgentState:
        state.state_revision += 1
        state.updated_at = datetime.now(UTC)
        self.ledger.save_state(state)
        await self._event(state, event_type, payload, actor=actor)
        return state

    async def _event(
        self,
        state: AgentState,
        event_type: str,
        payload: dict[str, Any],
        actor: str = "runtime",
    ) -> None:
        event = self.ledger.append(state.run_id, event_type, payload, actor=actor)
        await self.event_hub.publish(event.model_dump(mode="json"))

    def _spawn(self, coroutine: Any) -> None:
        task = asyncio.create_task(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
