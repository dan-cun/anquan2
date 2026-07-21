from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.schemas.agents import AgentResult
from ledger.serialization import checkpoint_roundtrip

from .native import AgentRunContext, NativeAgent
from .runtime_dependencies import AgentRuntimeDependencies


class AgentGraphState(TypedDict, total=False):
    context_id: str
    result: dict[str, Any]


class NativeAgentSubgraph:
    """Reusable LangGraph wrapper for every registered native Agent role."""

    def __init__(
        self,
        agent: NativeAgent,
        runtime_dependencies: AgentRuntimeDependencies,
    ) -> None:
        self.agent = agent
        self.runtime_dependencies = runtime_dependencies
        builder = StateGraph(AgentGraphState)
        builder.add_node("execute_agent", self._execute_agent)
        builder.add_edge(START, "execute_agent")
        builder.add_edge("execute_agent", END)
        self.graph = builder.compile()

    async def invoke(self, context: AgentRunContext) -> AgentResult:
        context_id = self.runtime_dependencies.bind(context)
        try:
            input_state = checkpoint_roundtrip({"context_id": context_id})
            state: dict[str, Any] = await self.graph.ainvoke(input_state)
            return AgentResult.model_validate(state["result"])
        finally:
            self.runtime_dependencies.release(context_id)

    async def _execute_agent(self, state: AgentGraphState) -> AgentGraphState:
        context_id = state["context_id"]
        context = self.runtime_dependencies.resolve(context_id)
        result = await self.agent.run(context)
        return checkpoint_roundtrip({"result": result.model_dump(mode="json")})
