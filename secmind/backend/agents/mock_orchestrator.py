from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

from agents.base import BaseOrchestrator
from app.schemas.events import WSMessage
from ledger.jsonl_store import JsonlLedgerStore
from llm.base import LLMProvider
from tools.registry import ToolRegistry


class MockOrchestrator(BaseOrchestrator):
    """Framework-only orchestrator used before real agents/tools are connected."""

    def __init__(
        self,
        *,
        ledger: JsonlLedgerStore,
        tool_registry: ToolRegistry,
        llm_provider: LLMProvider,
        step_delay_seconds: float = 0.02,
    ) -> None:
        self.ledger = ledger
        self.tool_registry = tool_registry
        self.llm_provider = llm_provider
        self.step_delay_seconds = max(step_delay_seconds, 0)

    async def handle_user_message(
        self,
        *,
        flow_id: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> AsyncIterator[WSMessage]:
        metadata = metadata or {}
        user_entry = self.ledger.append(
            flow_id,
            event_type="input.user_message",
            actor="user",
            payload={"content": content, "metadata": metadata},
        )
        yield WSMessage.event(
            "server.ledger_entry",
            flow_id=flow_id,
            payload={"entry": user_entry.model_dump(mode="json")},
        )

        steps = [
            ("orchestrator.received", "Received user input."),
            ("orchestrator.planning", "Created a placeholder execution plan."),
            ("orchestrator.routing", "No real agents or tools are connected yet."),
            ("orchestrator.ready", "Backend framework is ready for future plugin insertion."),
        ]
        for event_type, message in steps:
            await asyncio.sleep(self.step_delay_seconds)
            entry = self.ledger.append(
                flow_id,
                event_type=event_type,
                actor="mock_orchestrator",
                payload={
                    "message": message,
                    "registered_tools": self.tool_registry.list_metadata(),
                    "llm_provider": self.llm_provider.metadata(),
                },
            )
            yield WSMessage.event(
                "server.status",
                flow_id=flow_id,
                payload={"stage": event_type, "message": message},
            )
            yield WSMessage.event(
                "server.ledger_entry",
                flow_id=flow_id,
                payload={"entry": entry.model_dump(mode="json")},
            )

        if self._requires_approval(content):
            approval_id = str(uuid4())
            entry = self.ledger.append(
                flow_id,
                event_type="interrupt.approval_required",
                actor="mock_orchestrator",
                payload={
                    "approval_id": approval_id,
                    "reason": "Input requested an approval checkpoint.",
                },
            )
            yield WSMessage.event(
                "server.interrupt",
                flow_id=flow_id,
                payload={
                    "approval_id": approval_id,
                    "title": "Human confirmation required",
                    "message": "Approve this placeholder checkpoint to continue.",
                    "ledger_entry": entry.model_dump(mode="json"),
                },
            )
            return

        done_entry = self.ledger.append(
            flow_id,
            event_type="flow.mock_completed",
            actor="mock_orchestrator",
            payload={"result": "Mock execution completed."},
        )
        yield WSMessage.event(
            "server.done",
            flow_id=flow_id,
            payload={"result": "Mock execution completed.", "ledger_hash": done_entry.hash},
        )

    async def handle_approval(
        self,
        *,
        flow_id: str,
        approval_id: str,
        approved: bool,
        reason: str | None = None,
    ) -> AsyncIterator[WSMessage]:
        entry = self.ledger.append(
            flow_id,
            event_type="input.approval_response",
            actor="user",
            payload={"approval_id": approval_id, "approved": approved, "reason": reason},
        )
        yield WSMessage.event(
            "server.ledger_entry",
            flow_id=flow_id,
            payload={"entry": entry.model_dump(mode="json")},
        )
        final_entry = self.ledger.append(
            flow_id,
            event_type="flow.approval_completed",
            actor="mock_orchestrator",
            payload={"approval_id": approval_id, "approved": approved},
        )
        yield WSMessage.event(
            "server.done",
            flow_id=flow_id,
            payload={
                "result": "Approval response recorded.",
                "approved": approved,
                "ledger_hash": final_entry.hash,
            },
        )

    @staticmethod
    def _requires_approval(content: str) -> bool:
        lowered = content.lower()
        return (
            "confirm" in lowered
            or "approval" in lowered
            or "\u4eba\u5de5\u786e\u8ba4" in content
        )
