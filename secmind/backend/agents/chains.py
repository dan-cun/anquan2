from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from app.schemas.agents import AgentRole
from llm.base import LLMMessage


@dataclass(slots=True)
class AgentMessageChain:
    """One private model conversation owned by one Agent instance."""

    run_id: str
    flow_id: str
    agent_instance_id: str
    agent_role: AgentRole
    chain_id: str = field(default_factory=lambda: str(uuid4()))
    messages: list[LLMMessage] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def append(self, role: str, content: str, **metadata: object) -> LLMMessage:
        message = LLMMessage(role=role, content=content, metadata=dict(metadata))
        self.messages.append(message)
        self.updated_at = datetime.now(UTC)
        return message


class MessageChainStore(Protocol):
    async def create(
        self,
        *,
        run_id: str,
        flow_id: str,
        agent_instance_id: str,
        agent_role: AgentRole,
    ) -> AgentMessageChain: ...

    async def for_instance(self, agent_instance_id: str) -> AgentMessageChain: ...

    async def list_for_run(self, run_id: str) -> list[AgentMessageChain]: ...


class InMemoryMessageChainStore:
    """Default chain store; integration may replace it with a durable repository adapter."""

    def __init__(self) -> None:
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
        async with self._lock:
            if agent_instance_id in self._instance_index:
                raise ValueError(f"Agent instance already owns a chain: {agent_instance_id}")
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
