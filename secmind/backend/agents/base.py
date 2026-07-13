from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from app.schemas.events import WSMessage


class BaseOrchestrator(ABC):
    @abstractmethod
    async def handle_user_message(
        self,
        *,
        flow_id: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> AsyncIterator[WSMessage]:
        """Turn user input into streamable backend events."""

    @abstractmethod
    async def handle_approval(
        self,
        *,
        flow_id: str,
        approval_id: str,
        approved: bool,
        reason: str | None = None,
    ) -> AsyncIterator[WSMessage]:
        """Resume an interrupted flow after human approval."""


class AgentPlugin(ABC):
    name: str
    description: str

    @abstractmethod
    async def run(self, goal: str, context: dict[str, Any]) -> dict[str, Any]:
        """Execute an agent task and return structured output."""

