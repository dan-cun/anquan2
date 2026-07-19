from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.schemas.agents import AgentResult

from .native import AgentRunContext, NativeAgent


class AgentGraphState(TypedDict, total=False):
    context: AgentRunContext
    result: AgentResult


class NativeAgentSubgraph:
    """Reusable LangGraph wrapper for every registered native Agent role."""

    def __init__(self, agent: NativeAgent) -> None:
        self.agent = agent
        builder = StateGraph(AgentGraphState)
        builder.add_node("execute_agent", self._execute_agent)
        builder.add_edge(START, "execute_agent")
        builder.add_edge("execute_agent", END)
        self.graph = builder.compile()

    async def invoke(self, context: AgentRunContext) -> AgentResult:
        state: dict[str, Any] = await self.graph.ainvoke({"context": context})
        return AgentResult.model_validate(state["result"])

    async def _execute_agent(self, state: AgentGraphState) -> AgentGraphState:
        return {"result": await self.agent.run(state["context"])}

