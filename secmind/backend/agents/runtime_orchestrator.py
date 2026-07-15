from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from agents.base import BaseOrchestrator
from app.schemas.events import WSMessage
from app.schemas.runtime import AttachmentRef, TaskRequest
from app.services.runtime import RuntimeRunService
from ledger.jsonl_store import JsonlLedgerStore


class RuntimeOrchestrator(BaseOrchestrator):
    """Adapts the runtime agent kernel to the existing Flow/WebSocket shell."""

    def __init__(self, *, runtime: RuntimeRunService, flow_ledger: JsonlLedgerStore) -> None:
        self.runtime = runtime
        self.flow_ledger = flow_ledger
        self.graph = runtime.graph_runtime

    async def handle_user_message(
        self,
        *,
        flow_id: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> AsyncIterator[WSMessage]:
        metadata = metadata or {}
        user_entry = self.flow_ledger.append(
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
        yield WSMessage.event(
            "server.status",
            flow_id=flow_id,
            payload={"stage": "runtime.started", "message": "Runtime audit started."},
        )
        task = TaskRequest(
            objective=content,
            attachments=self._attachments_from_metadata(metadata),
            target_scope=self._string_list(metadata.get("target_scope")),
            constraints=self._string_list(metadata.get("constraints")),
            expected_outputs=(
                self._string_list(metadata.get("expected_outputs")) or ["security_report"]
            ),
            autonomy_policy=str(metadata.get("autonomy_policy", "graded")),
        )
        confirmation = None
        if self._requires_approval(content):
            confirmation = {
                "approval_id": f"approval-{flow_id}",
                "title": "Human confirmation required",
                "message": "Approve this checkpoint to continue.",
            }

        interrupted = False
        async for update in self.graph.stream_start(
            flow_id=flow_id,
            task=task,
            confirmation=confirmation,
        ):
            if "__interrupt__" in update:
                interrupted = True
                interrupt_value = update["__interrupt__"][0].value
                entry = self.flow_ledger.append(
                    flow_id,
                    event_type="interrupt.approval_required",
                    actor="runtime_orchestrator",
                    payload=interrupt_value,
                )
                interrupt_payload = dict(interrupt_value)
                interrupt_payload["ledger_entry"] = entry.model_dump(mode="json")
                yield WSMessage.event(
                    "server.interrupt",
                    flow_id=flow_id,
                    payload=interrupt_payload,
                )
            else:
                yield WSMessage.event(
                    "server.status",
                    flow_id=flow_id,
                    payload={
                        "stage": "langgraph.node.completed",
                        "node": next(iter(update), "unknown"),
                    },
                )

        if interrupted:
            return

        graph_state = self.graph.snapshot(flow_id)
        state = self.runtime.state(flow_id) if graph_state.get("runtime_state") else None
        if graph_state.get("denied"):
            result = "Approval denied."
            status = "denied"
        else:
            result = (
                state.report.executive_summary
                if state and state.report
                else "Runtime execution completed."
            )
            status = state.status if state else "completed"

        done_event = WSMessage.event(
            "server.done",
            flow_id=flow_id,
            payload={
                "result": result,
                "status": status,
                "run_id": flow_id,
                "finding_count": len(state.findings) if state else 0,
                "report": state.report.model_dump(mode="json") if state and state.report else None,
            },
        )
        async for event in self._mirror_runtime_events(flow_id):
            yield event
        yield done_event

    async def handle_approval(
        self,
        *,
        flow_id: str,
        approval_id: str,
        approved: bool,
        reason: str | None = None,
    ) -> AsyncIterator[WSMessage]:
        entry = self.flow_ledger.append(
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
        active_interrupt = self.graph.active_interrupt(flow_id)
        if active_interrupt is None or active_interrupt.get("approval_id") != approval_id:
            yield WSMessage.event(
                "server.error",
                flow_id=flow_id,
                payload={"message": "approval does not match an active LangGraph interrupt"},
            )
            return

        interrupted = False
        async for update in self.graph.stream_resume(
            flow_id=flow_id,
            response={
                "approval_id": approval_id,
                "approved": approved,
                "reason": reason or "",
            },
        ):
            if "__interrupt__" in update:
                interrupted = True
                interrupt_value = update["__interrupt__"][0].value
                interrupt_entry = self.flow_ledger.append(
                    flow_id,
                    event_type="interrupt.approval_required",
                    actor="runtime_orchestrator",
                    payload=interrupt_value,
                )
                interrupt_payload = dict(interrupt_value)
                interrupt_payload["ledger_entry"] = interrupt_entry.model_dump(mode="json")
                yield WSMessage.event(
                    "server.interrupt",
                    flow_id=flow_id,
                    payload=interrupt_payload,
                )
            else:
                yield WSMessage.event(
                    "server.status",
                    flow_id=flow_id,
                    payload={
                        "stage": "langgraph.node.completed",
                        "node": next(iter(update), "unknown"),
                    },
                )

        if interrupted:
            return

        graph_state = self.graph.snapshot(flow_id)
        state = self.runtime.state(flow_id) if graph_state.get("runtime_state") else None
        yield WSMessage.event(
            "server.done",
            flow_id=flow_id,
            payload={
                "result": (
                    state.report.executive_summary
                    if state and state.report
                    else "Approval response recorded."
                ),
                "approved": approved,
                "run_id": flow_id,
                "status": state.status if state else ("completed" if approved else "denied"),
                "report": state.report.model_dump(mode="json") if state and state.report else None,
            },
        )
        async for event in self._mirror_runtime_events(flow_id):
            yield event

    async def _mirror_runtime_events(self, flow_id: str) -> AsyncIterator[WSMessage]:
        after_sequence = self._last_mirrored_runtime_sequence(flow_id)
        for event in self.runtime.ledger.events(flow_id, after_sequence=after_sequence):
            flow_entry = self.flow_ledger.append(
                flow_id,
                event_type=f"runtime.{event.event_type}",
                actor=event.actor,
                payload=event.model_dump(mode="json"),
            )
            yield WSMessage.event(
                "server.ledger_entry",
                flow_id=flow_id,
                payload={"entry": flow_entry.model_dump(mode="json")},
            )

    def _last_mirrored_runtime_sequence(self, flow_id: str) -> int:
        sequences = [
            int(entry.payload["sequence"])
            for entry in self.flow_ledger.list_entries(flow_id)
            if entry.event_type.startswith("runtime.")
            and isinstance(entry.payload.get("sequence"), int)
        ]
        return max(sequences, default=0)

    @staticmethod
    def _attachments_from_metadata(metadata: dict[str, Any]) -> list[AttachmentRef]:
        raw = metadata.get("attachments")
        if raw is None and metadata.get("ref"):
            raw = [{"ref": metadata["ref"], "name": metadata.get("name")}]
        if raw is None:
            return []
        if not isinstance(raw, list):
            raw = [raw]
        attachments: list[AttachmentRef] = []
        for item in raw:
            if isinstance(item, str):
                attachments.append(AttachmentRef(ref=item))
            elif isinstance(item, dict):
                attachments.append(AttachmentRef.model_validate(item))
        return attachments

    @staticmethod
    def _requires_approval(content: str) -> bool:
        lowered = content.lower()
        return (
            "confirm" in lowered
            or "approval" in lowered
            or "\u4eba\u5de5\u786e\u8ba4" in content
        )

    @staticmethod
    def _string_list(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            return [str(item) for item in value]
        return [str(value)]
