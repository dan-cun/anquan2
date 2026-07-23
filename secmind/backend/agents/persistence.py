from __future__ import annotations

import asyncio

from app.database.repositories import AgentRepository
from app.schemas.agents import AgentRole
from llm.base import LLMMessage

from .chains import AgentMessageChain, MessageChainStore


class PersistentMessageChainStore(MessageChainStore):
    """Persists every native Agent chain while retaining active objects in memory."""

    def __init__(self, repository: AgentRepository, *, provider: str, model: str) -> None:
        self.repository = repository
        self.provider = provider
        self.model = model
        self._chains: dict[str, AgentMessageChain] = {}
        self._instance_index: dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def create(
        self,
        *,
        run_id: str,
        flow_id: str,
        agent_instance_id: str,
        agent_role: AgentRole,
    ) -> AgentMessageChain:
        chain = AgentMessageChain(
            run_id=run_id,
            flow_id=flow_id,
            agent_instance_id=agent_instance_id,
            agent_role=agent_role,
        )
        self.repository.create_chain(
            chain_id=chain.chain_id,
            run_id=run_id,
            flow_id=flow_id,
            agent_instance_id=agent_instance_id,
            agent_role=agent_role,
            model_provider=self.provider,
            model=self.model,
        )

        def persist(message: LLMMessage, sequence: int) -> None:
            content_data = dict(message.metadata)
            if message.tool_calls:
                content_data["tool_calls"] = [
                    item.model_dump(mode="json") for item in message.tool_calls
                ]
            if message.name is not None:
                content_data["name"] = message.name
            self.repository.append_chain_entry(
                chain_id=chain.chain_id,
                role=message.role,
                content=message.content or "",
                content_data=content_data,
                tool_call_id=message.tool_call_id,
                sequence=sequence,
            )

        chain.on_append = persist
        async with self._lock:
            self._chains[chain.chain_id] = chain
            self._instance_index[agent_instance_id] = chain.chain_id
        return chain

    async def for_instance(self, agent_instance_id: str) -> AgentMessageChain:
        async with self._lock:
            chain_id = self._instance_index.get(agent_instance_id)
            if chain_id is None:
                raise KeyError(agent_instance_id)
            return self._chains[chain_id]

    async def list_for_run(self, run_id: str) -> list[AgentMessageChain]:
        async with self._lock:
            return [chain for chain in self._chains.values() if chain.run_id == run_id]
