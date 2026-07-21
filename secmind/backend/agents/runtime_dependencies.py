from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .native import AgentRunContext


class AgentRuntimeDependencies:
    """Process-local handles that must never enter LangGraph state or checkpoints."""

    def __init__(self) -> None:
        self._contexts: dict[str, AgentRunContext] = {}

    def bind(self, context: AgentRunContext) -> str:
        agent_instance_id = context.instance.instance_id
        if agent_instance_id in self._contexts:
            raise RuntimeError(f"Agent context is already active: {agent_instance_id}")
        self._contexts[agent_instance_id] = context
        return agent_instance_id

    def resolve(self, agent_instance_id: str) -> AgentRunContext:
        try:
            return self._contexts[agent_instance_id]
        except KeyError as error:
            raise RuntimeError(
                f"Agent runtime context is unavailable: {agent_instance_id}"
            ) from error

    def release(self, agent_instance_id: str) -> None:
        self._contexts.pop(agent_instance_id, None)

    def active_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._contexts))
