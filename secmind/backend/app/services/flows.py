from __future__ import annotations

from datetime import UTC, datetime
from threading import RLock
from uuid import uuid4

from app.schemas.flow import Flow, FlowStatus


def _now() -> datetime:
    return datetime.now(UTC)


class FlowStore:
    """Small in-memory flow store used until a database is introduced."""

    def __init__(self) -> None:
        self._flows: dict[str, Flow] = {}
        self._lock = RLock()

    def create_flow(self, title: str | None = None, initial_input: str | None = None) -> Flow:
        flow_id = str(uuid4())
        return self.ensure_flow(
            flow_id,
            title=title or self._title_from_input(initial_input) or "Untitled flow",
        )

    def ensure_flow(self, flow_id: str, title: str | None = None) -> Flow:
        with self._lock:
            existing = self._flows.get(flow_id)
            if existing:
                return existing
            timestamp = _now()
            flow = Flow(
                id=flow_id,
                title=title or f"Flow {flow_id}",
                status=FlowStatus.created,
                created_at=timestamp,
                updated_at=timestamp,
            )
            self._flows[flow_id] = flow
            return flow

    def list_flows(self) -> list[Flow]:
        with self._lock:
            return sorted(self._flows.values(), key=lambda flow: flow.created_at, reverse=True)

    def get_flow(self, flow_id: str) -> Flow | None:
        with self._lock:
            return self._flows.get(flow_id)

    def update_status(self, flow_id: str, status: FlowStatus) -> Flow:
        with self._lock:
            flow = self._flows[flow_id]
            updated = flow.model_copy(update={"status": status, "updated_at": _now()})
            self._flows[flow_id] = updated
            return updated

    @staticmethod
    def _title_from_input(initial_input: str | None) -> str | None:
        if not initial_input:
            return None
        compact = " ".join(initial_input.split())
        return compact[:80] if compact else None
