from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from agents.base import BaseOrchestrator
from app.schemas.events import WSMessage
from app.schemas.runtime import AttachmentRef, LedgerEvent, TaskRequest
from app.services.event_stream import RuntimeEventStream
from app.services.execution import UnifiedExecutionService
from app.services.runtime import RuntimeRunService
from ledger.jsonl_store import JsonlLedgerStore


class RuntimeOrchestrator(BaseOrchestrator):
    """Adapts the runtime agent kernel to the existing Flow/WebSocket shell."""

    def __init__(
        self,
        *,
        runtime: RuntimeRunService,
        execution: UnifiedExecutionService,
        flow_ledger: JsonlLedgerStore,
        event_stream: RuntimeEventStream,
    ) -> None:
        self.runtime = runtime
        self.execution = execution
        self.flow_ledger = flow_ledger
        self.event_stream = event_stream
        self.graph = runtime.graph_runtime
        self._active_runs: dict[str, str] = {}

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
            expected_outputs=self._string_list(metadata.get("expected_outputs")),
            completion_mode=metadata.get("completion_mode"),
            evaluator=metadata.get("evaluator"),
            required_evidence=self._string_list(metadata.get("required_evidence")),
            metadata=metadata,
            autonomy_policy=str(metadata.get("autonomy_policy", "graded")),
        )
        identity = self.execution.prepare_identity(task, flow_id=flow_id)
        self._active_runs[flow_id] = identity.run_id
        self.execution.repositories.tasks.update_task(identity.task_id, status="running")
        yield WSMessage.event(
            "server.status",
            flow_id=flow_id,
            payload={
                "stage": "execution.identity.created",
                **identity.model_dump(mode="json"),
            },
        )
        confirmation = None
        if self._requires_approval(content):
            confirmation = {
                "approval_id": f"approval-{identity.run_id}",
                "title": "Human confirmation required",
                "message": "Approve this checkpoint to continue.",
            }

        interrupted = False
        updates = self.graph.stream_start(
            flow_id=flow_id,
            task=task,
            run_id=identity.run_id,
            task_id=identity.task_id,
            confirmation=confirmation,
        )
        async for source, value in self._stream_graph_updates(
            flow_id,
            identity.run_id,
            updates,
        ):
            if source == "runtime":
                yield value
                continue
            update = value
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

        graph_state = await self.graph.snapshot(identity.run_id)
        state = self.runtime.state(identity.run_id) if graph_state.get("run_id") else None
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
                "run_id": identity.run_id,
                "task_id": identity.task_id,
                "finding_count": len(state.findings) if state else 0,
                "report": state.report.model_dump(mode="json") if state and state.report else None,
            },
        )
        self._record_completion(flow_id, done_event)
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
        run_id = self._active_runs.get(flow_id) or self._latest_run_for_flow(flow_id)
        if run_id is None:
            yield WSMessage.event(
                "server.error",
                flow_id=flow_id,
                payload={"message": "flow has no active runtime execution"},
            )
            return
        active_interrupt = await self.graph.active_interrupt(run_id)
        if active_interrupt is None or active_interrupt.get("approval_id") != approval_id:
            yield WSMessage.event(
                "server.error",
                flow_id=flow_id,
                payload={"message": "approval does not match an active LangGraph interrupt"},
            )
            return

        interrupted = False
        updates = self.graph.stream_resume(
            flow_id=run_id,
            response={
                "approval_id": approval_id,
                "approved": approved,
                "reason": reason or "",
            },
        )
        async for source, value in self._stream_graph_updates(flow_id, run_id, updates):
            if source == "runtime":
                yield value
                continue
            update = value
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

        graph_state = await self.graph.snapshot(run_id)
        state = self.runtime.state(run_id) if graph_state.get("run_id") else None
        done_event = WSMessage.event(
            "server.done",
            flow_id=flow_id,
            payload={
                "result": (
                    state.report.executive_summary
                    if state and state.report
                    else "Approval response recorded."
                ),
                "approved": approved,
                "run_id": run_id,
                "task_id": state.task_id if state else None,
                "status": state.status if state else ("completed" if approved else "denied"),
                "report": state.report.model_dump(mode="json") if state and state.report else None,
            },
        )
        self._record_completion(flow_id, done_event)
        yield done_event

    def _record_completion(self, flow_id: str, event: WSMessage) -> None:
        self.flow_ledger.append(
            flow_id,
            event_type="flow.completed",
            actor="runtime_orchestrator",
            payload=event.payload,
        )

    async def _mirror_runtime_events(
        self,
        flow_id: str,
        run_id: str,
    ) -> AsyncIterator[WSMessage]:
        after_sequence = self._last_mirrored_runtime_sequence(flow_id, run_id)
        for event in self.runtime.ledger.events(run_id, after_sequence=after_sequence):
            yield self._mirror_runtime_event(flow_id, event)

    def _mirror_runtime_event(self, flow_id: str, event: LedgerEvent) -> WSMessage:
        flow_entry = self.flow_ledger.append(
            flow_id,
            event_type=f"runtime.{event.event_type}",
            actor=event.actor,
            payload=event.model_dump(mode="json"),
        )
        return WSMessage.event(
            "server.ledger_entry",
            flow_id=flow_id,
            sequence=flow_entry.seq,
            request_id=f"runtime-{event.event_id}",
            payload={"entry": flow_entry.model_dump(mode="json")},
        )

    async def _stream_graph_updates(
        self,
        flow_id: str,
        run_id: str,
        updates: AsyncIterator[dict[str, Any]],
    ) -> AsyncIterator[tuple[str, Any]]:
        after_sequence = self._last_mirrored_runtime_sequence(flow_id, run_id)
        runtime_events = self.event_stream.subscribe(
            run_id,
            after_sequence=after_sequence,
        )
        update_iterator = updates.__aiter__()
        event_iterator = runtime_events.__aiter__()
        update_task: asyncio.Task[Any] | None = asyncio.create_task(anext(update_iterator))
        event_task: asyncio.Task[Any] | None = asyncio.create_task(anext(event_iterator))

        try:
            while update_task is not None:
                active = {task for task in (event_task, update_task) if task is not None}
                completed, _ = await asyncio.wait(active, return_when=asyncio.FIRST_COMPLETED)

                if event_task is not None and event_task in completed:
                    event = event_task.result()
                    yield "runtime", self._mirror_runtime_event(flow_id, event)
                    event_task = asyncio.create_task(anext(event_iterator))

                if update_task in completed:
                    try:
                        update = update_task.result()
                    except StopAsyncIteration:
                        update_task = None
                    else:
                        yield "graph", update
                        update_task = asyncio.create_task(anext(update_iterator))
        finally:
            pending = [task for task in (event_task, update_task) if task is not None]
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            await runtime_events.aclose()
            close_updates = getattr(updates, "aclose", None)
            if callable(close_updates):
                await close_updates()

        async for event in self._mirror_runtime_events(flow_id, run_id):
            yield "runtime", event

    def _last_mirrored_runtime_sequence(self, flow_id: str, run_id: str) -> int:
        sequences = [
            int(entry.payload["sequence"])
            for entry in self.flow_ledger.list_entries(flow_id)
            if entry.event_type.startswith("runtime.")
            and entry.payload.get("run_id") == run_id
            and isinstance(entry.payload.get("sequence"), int)
        ]
        return max(sequences, default=0)

    def _latest_run_for_flow(self, flow_id: str) -> str | None:
        candidates = []
        for run_id in self.runtime.ledger.run_ids():
            state = self.runtime.ledger.load_state(run_id)
            if state is not None and state.flow_id == flow_id:
                candidates.append((state.updated_at, run_id))
        return max(candidates, default=(None, None))[1]

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
