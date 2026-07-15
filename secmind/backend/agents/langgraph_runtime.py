from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from app.schemas.runtime import AgentState, RunStatus, TaskRequest
from app.services.runtime import RuntimeRunService
from ledger.checkpoints import checkpoint_config


class RuntimeGraphState(TypedDict, total=False):
    flow_id: str
    runtime_state: dict[str, Any]
    confirmation: dict[str, Any]
    route: str
    denied: bool


class LangGraphRuntime:
    """Complete SecMind graph with injectable checkpoint storage."""

    NODE_NAMES = (
        "confirmation_gate",
        "ingest",
        "classify",
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
                "retrieve_context": "retrieve_context",
                "select_step": "select_step",
                "approval": "approval",
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
        builder.add_edge("classify", "retrieve_context")
        builder.add_edge("retrieve_context", "plan")
        builder.add_edge("plan", "validate_plan")
        builder.add_conditional_edges(
            "validate_plan",
            self._route,
            {"select_step": "select_step", "report": "report"},
        )
        builder.add_conditional_edges(
            "select_step",
            self._route,
            {"guardrail": "guardrail", "report": "report"},
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
            {"observe": "observe", "report": "report"},
        )
        builder.add_edge("observe", "analyze")
        builder.add_edge("analyze", "verify")
        builder.add_conditional_edges(
            "verify",
            self._route,
            {"next": "select_step", "reflect": "reflect", "report": "report"},
        )
        builder.add_edge("reflect", "select_step")
        builder.add_edge("report", "memory_commit")
        builder.add_edge("memory_commit", END)
        self.graph = builder.compile(checkpointer=self.checkpointer)

    async def stream_start(
        self,
        *,
        flow_id: str,
        task: TaskRequest,
        confirmation: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        state = await self.runtime.prepare_run(task, flow_id)
        input_state: RuntimeGraphState = {
            "flow_id": flow_id,
            "runtime_state": state.model_dump(mode="json"),
        }
        if confirmation is not None:
            input_state["confirmation"] = confirmation
        async for update in self.graph.astream(
            input_state,
            config=self._config(flow_id),
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
            {
                "flow_id": state.run_id,
                "runtime_state": state.model_dump(mode="json"),
            },
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

    async def _retrieve_context(self, value: RuntimeGraphState) -> RuntimeGraphState:
        return self._update(await self.runtime.node_retrieve_context(self._state(value)))

    async def _plan(self, value: RuntimeGraphState) -> RuntimeGraphState:
        return self._update(await self.runtime.node_plan(self._state(value)))

    async def _validate_plan(self, value: RuntimeGraphState) -> RuntimeGraphState:
        state = await self.runtime.node_validate_plan(self._state(value))
        route = "report" if state.status == RunStatus.FAILED or not state.plan else "select_step"
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
        route = (
            "report"
            if state.status in {RunStatus.PARTIAL, RunStatus.DENIED, RunStatus.FAILED}
            or len(state.observations) <= before
            else "observe"
        )
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

    async def _report(self, value: RuntimeGraphState) -> RuntimeGraphState:
        return self._update(await self.runtime.node_report(self._state(value)))

    async def _memory_commit(self, value: RuntimeGraphState) -> RuntimeGraphState:
        return self._update(await self.runtime.node_memory_commit(self._state(value)))

    @staticmethod
    def _state(value: RuntimeGraphState) -> AgentState:
        return AgentState.model_validate(value["runtime_state"])

    @staticmethod
    def _update(
        state: AgentState,
        route: str | None = None,
        *,
        denied: bool | None = None,
    ) -> RuntimeGraphState:
        update: RuntimeGraphState = {"runtime_state": state.model_dump(mode="json")}
        if route is not None:
            update["route"] = route
        if denied is not None:
            update["denied"] = denied
        return update

    @staticmethod
    def _start_route(state: RuntimeGraphState) -> str:
        if state.get("confirmation"):
            return "confirmation_gate"
        runtime_state = AgentState.model_validate(state["runtime_state"])
        if runtime_state.pending_approval is not None:
            return "approval"
        if not runtime_state.workspace:
            return "ingest"
        if runtime_state.scenario.value == "unknown":
            return "classify"
        if not runtime_state.plan:
            return "retrieve_context"
        return "select_step"

    @staticmethod
    def _route(state: RuntimeGraphState) -> str:
        return state.get("route", "report")

    def _config(self, flow_id: str) -> dict[str, Any]:
        return checkpoint_config(flow_id, self.checkpoint_namespace)
