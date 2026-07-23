from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from app.schemas.runtime import AgentState, CapabilityStatus, RunStatus, TaskRequest
from app.services.runtime import RuntimeRunService
from ledger.checkpoints import checkpoint_config
from ledger.serialization import checkpoint_roundtrip


class RuntimeGraphState(TypedDict, total=False):
    run_id: str
    flow_id: str
    state_revision: int
    confirmation: dict[str, Any]
    route: str
    denied: bool


class LangGraphRuntime:
    """Complete SecMind graph with injectable checkpoint storage."""

    NODE_NAMES = (
        "confirmation_gate",
        "ingest",
        "classify",
        "capability_route",
        "universal_primary",
        "collaborate",
        "retrieve_context",
        "plan",
        "validate_plan",
        "select_step",
        "guardrail",
        "approval",
        "record_denial",
        "execute",
        "observe",
        "analyze",
        "verify",
        "reflect",
        "secondary_review",
        "completion_gate",
        "report",
        "memory_commit",
    )

    def __init__(
        self,
        runtime: RuntimeRunService,
        *,
        checkpointer: Any | None = None,
        checkpoint_namespace: str = "",
    ) -> None:
        self.runtime = runtime
        self.checkpointer = checkpointer if checkpointer is not None else MemorySaver()
        self.checkpoint_namespace = checkpoint_namespace
        builder = StateGraph(RuntimeGraphState)
        for name in self.NODE_NAMES:
            builder.add_node(name, getattr(self, f"_{name}"))

        builder.add_conditional_edges(
            START,
            self._start_route,
            {
                "confirmation_gate": "confirmation_gate",
                "ingest": "ingest",
                "classify": "classify",
                "capability_route": "capability_route",
                "universal_primary": "universal_primary",
                "collaborate": "collaborate",
                "retrieve_context": "retrieve_context",
                "select_step": "select_step",
                "approval": "approval",
                "report": "report",
            },
        )
        builder.add_conditional_edges(
            "confirmation_gate",
            self._route,
            {"ingest": "ingest", "deny": "record_denial"},
        )
        builder.add_conditional_edges(
            "ingest",
            self._route,
            {"classify": "classify", "report": "report"},
        )
        builder.add_edge("classify", "capability_route")
        builder.add_edge("capability_route", "universal_primary")
        builder.add_conditional_edges(
            "universal_primary",
            self._route,
            {"collaborate": "collaborate", "report": "report"},
        )
        builder.add_edge("collaborate", "retrieve_context")
        builder.add_edge("retrieve_context", "plan")
        builder.add_edge("plan", "validate_plan")
        builder.add_conditional_edges(
            "validate_plan",
            self._route,
            {
                "select_step": "select_step",
                "secondary_review": "secondary_review",
                "report": "report",
            },
        )
        builder.add_conditional_edges(
            "select_step",
            self._route,
            {
                "guardrail": "guardrail",
                "secondary_review": "secondary_review",
                "report": "report",
            },
        )
        builder.add_conditional_edges(
            "guardrail",
            self._route,
            {
                "approval": "approval",
                "execute": "execute",
                "deny": "record_denial",
            },
        )
        builder.add_conditional_edges(
            "approval",
            self._route,
            {"execute": "execute", "deny": "record_denial"},
        )
        builder.add_edge("record_denial", "report")
        builder.add_conditional_edges(
            "execute",
            self._route,
            {
                "observe": "observe",
                "secondary_review": "secondary_review",
                "report": "report",
            },
        )
        builder.add_edge("observe", "analyze")
        builder.add_edge("analyze", "verify")
        builder.add_conditional_edges(
            "verify",
            self._route,
            {
                "next": "select_step",
                "reflect": "reflect",
                "secondary_review": "secondary_review",
                "report": "report",
            },
        )
        builder.add_edge("reflect", "select_step")
        builder.add_edge("secondary_review", "completion_gate")
        builder.add_edge("completion_gate", "report")
        builder.add_edge("report", "memory_commit")
        builder.add_edge("memory_commit", END)
        self.graph = builder.compile(checkpointer=self.checkpointer)

    async def stream_start(
        self,
        *,
        flow_id: str,
        task: TaskRequest,
        run_id: str | None = None,
        task_id: str | None = None,
        confirmation: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        resolved_run_id = run_id or flow_id
        state = await self.runtime.prepare_run(
            task,
            resolved_run_id,
            flow_id=flow_id,
            task_id=task_id,
        )
        input_state: RuntimeGraphState = checkpoint_roundtrip(
            {
                "run_id": state.run_id,
                "flow_id": flow_id,
                "state_revision": state.state_revision,
            }
        )
        if confirmation is not None:
            input_state["confirmation"] = confirmation
        async for update in self.graph.astream(
            input_state,
            config=self._config(resolved_run_id),
            stream_mode="updates",
        ):
            yield update

    async def stream_resume(
        self,
        *,
        flow_id: str,
        response: dict[str, Any],
    ) -> AsyncIterator[dict[str, Any]]:
        async for update in self.graph.astream(
            Command(resume=response),
            config=self._config(flow_id),
            stream_mode="updates",
        ):
            yield update

    async def invoke_state(self, state: AgentState) -> AgentState:
        result = await self.graph.ainvoke(
            checkpoint_roundtrip(
                {
                    "run_id": state.run_id,
                    "flow_id": state.flow_id or state.run_id,
                    "state_revision": state.state_revision,
                }
            ),
            config=self._config(state.run_id),
        )
        return self._state(result)

    async def invoke_resume(self, *, run_id: str, response: dict[str, Any]) -> AgentState:
        result = await self.graph.ainvoke(
            Command(resume=response),
            config=self._config(run_id),
        )
        return self._state(result)

    async def snapshot(self, flow_id: str) -> dict[str, Any]:
        return dict((await self.graph.aget_state(self._config(flow_id))).values)

    async def active_interrupt(self, flow_id: str) -> dict[str, Any] | None:
        snapshot = await self.graph.aget_state(self._config(flow_id))
        if not snapshot.interrupts:
            return None
        value = snapshot.interrupts[0].value
        return value if isinstance(value, dict) else {"message": str(value)}

    async def _confirmation_gate(self, value: RuntimeGraphState) -> RuntimeGraphState:
        response = interrupt(value["confirmation"])
        approved = bool(response.get("approved")) if isinstance(response, dict) else False
        if approved:
            return {"route": "ingest", "denied": False}
        state = await self.runtime.node_preflight_denial(self._state(value))
        return self._update(state, "deny", denied=True)

    async def _ingest(self, value: RuntimeGraphState) -> RuntimeGraphState:
        state = await self.runtime.node_ingest(self._state(value))
        route = "report" if state.status == RunStatus.FAILED else "classify"
        return self._update(state, route)

    async def _classify(self, value: RuntimeGraphState) -> RuntimeGraphState:
        return self._update(await self.runtime.node_classify(self._state(value)))

    async def _capability_route(self, value: RuntimeGraphState) -> RuntimeGraphState:
        return self._update(await self.runtime.node_capability_route(self._state(value)))

    async def _universal_primary(self, value: RuntimeGraphState) -> RuntimeGraphState:
        state = await self.runtime.node_universal_primary(self._state(value))
        route = (
            "report"
            if state.capability_plan is not None
            and state.capability_plan.status == CapabilityStatus.UNAVAILABLE
            else "collaborate"
        )
        return self._update(state, route)

    async def _collaborate(self, value: RuntimeGraphState) -> RuntimeGraphState:
        return self._update(await self.runtime.node_collaborate(self._state(value)))

    async def _retrieve_context(self, value: RuntimeGraphState) -> RuntimeGraphState:
        return self._update(await self.runtime.node_retrieve_context(self._state(value)))

    async def _plan(self, value: RuntimeGraphState) -> RuntimeGraphState:
        return self._update(await self.runtime.node_plan(self._state(value)))

    async def _validate_plan(self, value: RuntimeGraphState) -> RuntimeGraphState:
        state = await self.runtime.node_validate_plan(self._state(value))
        route = (
            "report"
            if state.status in {RunStatus.DENIED, RunStatus.FAILED}
            else "select_step" if state.plan else "secondary_review"
        )
        return self._update(state, route)

    async def _select_step(self, value: RuntimeGraphState) -> RuntimeGraphState:
        state, route = await self.runtime.node_select_step(self._state(value))
        return self._update(state, route)

    async def _guardrail(self, value: RuntimeGraphState) -> RuntimeGraphState:
        state, route = await self.runtime.node_guardrail(self._state(value))
        return self._update(state, route)

    async def _approval(self, value: RuntimeGraphState) -> RuntimeGraphState:
        state = await self.runtime.node_request_approval(self._state(value))
        pending = state.pending_approval
        if pending is None:
            return self._update(state, "deny")
        response = interrupt(
            {
                "approval_id": pending.request_id,
                "title": "Human confirmation required",
                "message": pending.reason,
                "request": pending.model_dump(mode="json"),
            }
        )
        raw = response if isinstance(response, dict) else {}
        state, route = await self.runtime.node_resolve_approval(state, raw)
        return self._update(state, route)

    async def _record_denial(self, value: RuntimeGraphState) -> RuntimeGraphState:
        return self._update(await self.runtime.node_record_denial(self._state(value)))

    async def _execute(self, value: RuntimeGraphState) -> RuntimeGraphState:
        before = len(self._state(value).observations)
        state = await self.runtime.node_execute(self._state(value))
        if state.status in {RunStatus.DENIED, RunStatus.FAILED}:
            route = "report"
        elif len(state.observations) <= before:
            route = "secondary_review"
        else:
            route = "observe"
        return self._update(state, route)

    async def _observe(self, value: RuntimeGraphState) -> RuntimeGraphState:
        return self._update(await self.runtime.node_observe(self._state(value)))

    async def _analyze(self, value: RuntimeGraphState) -> RuntimeGraphState:
        return self._update(await self.runtime.node_analyze(self._state(value)))

    async def _verify(self, value: RuntimeGraphState) -> RuntimeGraphState:
        state, route = await self.runtime.node_verify(self._state(value))
        return self._update(state, route)

    async def _reflect(self, value: RuntimeGraphState) -> RuntimeGraphState:
        return self._update(await self.runtime.node_reflect(self._state(value)))

    async def _secondary_review(self, value: RuntimeGraphState) -> RuntimeGraphState:
        return self._update(await self.runtime.node_secondary_review(self._state(value)))

    async def _completion_gate(self, value: RuntimeGraphState) -> RuntimeGraphState:
        return self._update(await self.runtime.node_completion_gate(self._state(value)))

    async def _report(self, value: RuntimeGraphState) -> RuntimeGraphState:
        return self._update(await self.runtime.node_report(self._state(value)))

    async def _memory_commit(self, value: RuntimeGraphState) -> RuntimeGraphState:
        return self._update(await self.runtime.node_memory_commit(self._state(value)))

    def _state(self, value: RuntimeGraphState) -> AgentState:
        return self.runtime.state(value["run_id"])

    def _update(
        self,
        state: AgentState,
        route: str | None = None,
        *,
        denied: bool | None = None,
    ) -> RuntimeGraphState:
        update: RuntimeGraphState = {
            "run_id": state.run_id,
            "flow_id": state.flow_id or state.run_id,
            "state_revision": state.state_revision,
        }
        if route is not None:
            update["route"] = route
        if denied is not None:
            update["denied"] = denied
        return checkpoint_roundtrip(update)

    def _start_route(self, state: RuntimeGraphState) -> str:
        if state.get("confirmation"):
            return "confirmation_gate"
        runtime_state = self._state(state)
        if runtime_state.pending_approval is not None:
            return "approval"
        if not runtime_state.workspace:
            return "ingest"
        if not runtime_state.classification_completed:
            return "classify"
        if runtime_state.capability_plan is None:
            return "capability_route"
        if not runtime_state.primary_persisted:
            return "universal_primary"
        if runtime_state.capability_plan.status == CapabilityStatus.UNAVAILABLE:
            return "report"
        if not runtime_state.collaboration_completed:
            return "collaborate"
        if not runtime_state.plan:
            return "retrieve_context"
        return "select_step"

    @staticmethod
    def _route(state: RuntimeGraphState) -> str:
        return state.get("route", "report")

    def _config(self, flow_id: str) -> dict[str, Any]:
        return checkpoint_config(flow_id, self.checkpoint_namespace)
