from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from app.schemas.runtime import AgentState, LedgerEvent, RunStatus

ZERO_HASH = "0" * 64
SECRET_KEYS = {"api_key", "apikey", "authorization", "password", "secret", "token"}
SECRET_PATTERN = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{8,}")
logger = logging.getLogger(__name__)
EventListener = Callable[[LedgerEvent], None]


class Base(DeclarativeBase):
    pass


class RuntimeEventRow(Base):
    __tablename__ = "runtime_ledger_events"
    __table_args__ = (UniqueConstraint("run_id", "sequence"),)

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    actor: Mapped[str] = mapped_column(String(100))
    payload_json: Mapped[str] = mapped_column(Text)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))


class RuntimeRunRow(Base):
    __tablename__ = "runtime_runs"

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[str] = mapped_column(String(30), index=True)
    state_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LedgerIntegrityError(RuntimeError):
    """Raised when an audit replay is requested for a damaged hash chain."""


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if key.lower() in SECRET_KEYS else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return SECRET_PATTERN.sub(r"\1[REDACTED]", value)
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


class RuntimeLedgerStore:
    """Append-only hash-chained event store plus persisted run snapshots."""

    def __init__(
        self,
        database_url: str,
        *,
        auto_create_schema: bool | None = None,
    ) -> None:
        connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
        self.engine = create_engine(database_url, future=True, connect_args=connect_args)
        self._locks: dict[str, threading.RLock] = {}
        self._locks_guard = threading.Lock()
        self._event_listeners: list[EventListener] = []
        self._listeners_lock = threading.RLock()
        if auto_create_schema is None:
            auto_create_schema = database_url.startswith("sqlite")
        if auto_create_schema:
            # Local SQLite and isolated tests retain zero-config startup. PostgreSQL never
            # reaches this branch and must be migrated with Alembic before the app starts.
            from ledger import projections as _projections  # noqa: F401

            Base.metadata.create_all(self.engine)

    def _lock_for(self, run_id: str) -> threading.RLock:
        with self._locks_guard:
            return self._locks.setdefault(run_id, threading.RLock())

    def add_event_listener(self, listener: EventListener) -> None:
        with self._listeners_lock:
            if listener not in self._event_listeners:
                self._event_listeners.append(listener)

    def remove_event_listener(self, listener: EventListener) -> None:
        with self._listeners_lock:
            if listener in self._event_listeners:
                self._event_listeners.remove(listener)

    def append(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
        actor: str = "system",
    ) -> LedgerEvent:
        safe_payload = redact(payload)
        with self._lock_for(run_id), Session(self.engine) as session:
            previous = session.scalars(
                select(RuntimeEventRow)
                .where(RuntimeEventRow.run_id == run_id)
                .order_by(RuntimeEventRow.sequence.desc())
                .limit(1)
            ).first()
            sequence = 1 if previous is None else previous.sequence + 1
            prev_hash = ZERO_HASH if previous is None else previous.hash
            timestamp = datetime.now(UTC)
            event_id = str(uuid4())
            digest_input = {
                "event_id": event_id,
                "run_id": run_id,
                "sequence": sequence,
                "event_type": event_type,
                "timestamp": timestamp.isoformat(),
                "actor": actor,
                "payload": safe_payload,
                "prev_hash": prev_hash,
            }
            digest = hashlib.sha256(canonical_json(digest_input).encode()).hexdigest()
            row = RuntimeEventRow(
                event_id=event_id,
                run_id=run_id,
                sequence=sequence,
                event_type=event_type,
                timestamp=timestamp,
                actor=actor,
                payload_json=canonical_json(safe_payload),
                prev_hash=prev_hash,
                hash=digest,
            )
            session.add(row)
            session.commit()
            event = self._to_event(row)
        self._notify_event_listeners(event)
        return event

    def _notify_event_listeners(self, event: LedgerEvent) -> None:
        with self._listeners_lock:
            listeners = tuple(self._event_listeners)
        for listener in listeners:
            try:
                listener(event)
            except Exception:
                # The event is committed. Projection offsets make a later retry safe.
                logger.exception(
                    "Runtime ledger listener failed for run_id=%s sequence=%s",
                    event.run_id,
                    event.sequence,
                )

    def events(self, run_id: str, after_sequence: int = 0, limit: int = 1000) -> list[LedgerEvent]:
        with Session(self.engine) as session:
            rows = session.scalars(
                select(RuntimeEventRow)
                .where(RuntimeEventRow.run_id == run_id, RuntimeEventRow.sequence > after_sequence)
                .order_by(RuntimeEventRow.sequence)
                .limit(limit)
            ).all()
            return [self._to_event(row) for row in rows]

    def replay_events(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 1000,
    ) -> list[LedgerEvent]:
        """Read audit events only after validating the complete run hash chain."""
        if not self.verify(run_id):
            raise LedgerIntegrityError(f"hash-chain verification failed for run {run_id}")
        return self.events(run_id, after_sequence=after_sequence, limit=limit)

    def run_ids(self) -> list[str]:
        with Session(self.engine) as session:
            statement = select(RuntimeEventRow.run_id).distinct().order_by(RuntimeEventRow.run_id)
            return list(session.scalars(statement).all())

    def verify(self, run_id: str) -> bool:
        previous = ZERO_HASH
        for expected_sequence, event in enumerate(
            self.events(run_id, limit=1_000_000),
            start=1,
        ):
            if event.sequence != expected_sequence:
                return False
            if event.prev_hash != previous:
                return False
            digest_input = {
                "event_id": event.event_id,
                "run_id": event.run_id,
                "sequence": event.sequence,
                "event_type": event.event_type,
                "timestamp": event.timestamp.isoformat(),
                "actor": event.actor,
                "payload": event.payload,
                "prev_hash": event.prev_hash,
            }
            expected = hashlib.sha256(canonical_json(digest_input).encode()).hexdigest()
            if expected != event.hash:
                return False
            previous = event.hash
        return True

    def save_state(self, state: AgentState) -> None:
        now = datetime.now(UTC)
        state_json = state.model_dump_json()
        with self._lock_for(state.run_id), Session(self.engine) as session:
            row = session.get(RuntimeRunRow, state.run_id)
            if row is None:
                row = RuntimeRunRow(
                    run_id=state.run_id,
                    status=state.status.value,
                    state_json=state_json,
                    created_at=now,
                    updated_at=now,
                )
                session.add(row)
            else:
                row.status = state.status.value
                row.state_json = state_json
                row.updated_at = now
            session.commit()

    def load_state(self, run_id: str) -> AgentState | None:
        with Session(self.engine) as session:
            row = session.get(RuntimeRunRow, run_id)
            return None if row is None else AgentState.model_validate_json(row.state_json)

    def incomplete_run_ids(self) -> list[str]:
        terminal = {
            RunStatus.COMPLETED.value,
            RunStatus.PARTIAL.value,
            RunStatus.DENIED.value,
            RunStatus.FAILED.value,
        }
        with Session(self.engine) as session:
            statement = select(RuntimeRunRow.run_id).where(
                RuntimeRunRow.status.not_in(terminal)
            )
            return list(session.scalars(statement).all())

    def model_usage(self, period: str = "total") -> dict[str, Any]:
        totals = {
            "request_count": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
        by_model: dict[tuple[str, str], dict[str, Any]] = {}
        by_conversation: dict[str, dict[str, Any]] = {}
        last_request_at: datetime | None = None
        now = datetime.now(UTC)
        cutoff = None
        if period == "day":
            cutoff = datetime(now.year, now.month, now.day, tzinfo=UTC)
        elif period == "month":
            cutoff = datetime(now.year, now.month, 1, tzinfo=UTC)
        elif period != "total":
            raise ValueError(f"Unsupported model usage period: {period}")

        with Session(self.engine) as session:
            statement = select(
                RuntimeEventRow.run_id,
                RuntimeEventRow.payload_json,
                RuntimeEventRow.timestamp,
            ).where(RuntimeEventRow.event_type == "llm.response")
            if cutoff is not None:
                statement = statement.where(RuntimeEventRow.timestamp >= cutoff)
            rows = session.execute(statement.order_by(RuntimeEventRow.timestamp)).all()

        for run_id, payload_json, timestamp in rows:
            timestamp = timestamp.replace(tzinfo=timestamp.tzinfo or UTC)
            payload = json.loads(payload_json)
            raw = payload.get("raw") if isinstance(payload.get("raw"), dict) else {}
            usage = raw.get("usage") if isinstance(raw.get("usage"), dict) else {}
            prompt_tokens = self._usage_int(usage, "prompt_tokens", "input_tokens")
            completion_tokens = self._usage_int(
                usage,
                "completion_tokens",
                "output_tokens",
            )
            total_tokens = self._usage_int(usage, "total_tokens")
            if total_tokens == 0:
                total_tokens = prompt_tokens + completion_tokens
            provider = str(payload.get("provider") or "unknown")
            model = str(payload.get("model") or "unknown")
            item = by_model.setdefault(
                (provider, model),
                {
                    "provider": provider,
                    "model": model,
                    "request_count": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "last_request_at": timestamp,
                },
            )
            conversation = by_conversation.setdefault(
                run_id,
                {
                    "flow_id": run_id,
                    "title": None,
                    "models": set(),
                    "request_count": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "last_request_at": timestamp,
                },
            )
            conversation["models"].add(model)
            for target in (totals, item, conversation):
                target["request_count"] += 1
                target["prompt_tokens"] += prompt_tokens
                target["completion_tokens"] += completion_tokens
                target["total_tokens"] += total_tokens
                if "last_request_at" in target:
                    target["last_request_at"] = max(target["last_request_at"], timestamp)
            last_request_at = timestamp

        conversation_items = []
        for item in by_conversation.values():
            item["models"] = sorted(item["models"])
            conversation_items.append(item)

        return {
            **totals,
            "period": period,
            "estimated_cost": None,
            "currency": None,
            "last_request_at": last_request_at,
            "by_model": sorted(
                by_model.values(),
                key=lambda item: (-item["total_tokens"], item["provider"], item["model"]),
            ),
            "by_conversation": sorted(
                conversation_items,
                key=lambda item: (-item["total_tokens"], item["flow_id"]),
            ),
        }

    def export_jsonl(self, run_id: str, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("w", encoding="utf-8", newline="\n") as output:
            for event in self.events(run_id, limit=1_000_000):
                output.write(event.model_dump_json() + "\n")
        return destination

    @staticmethod
    def _to_event(row: RuntimeEventRow) -> LedgerEvent:
        return LedgerEvent(
            event_id=row.event_id,
            run_id=row.run_id,
            sequence=row.sequence,
            event_type=row.event_type,
            timestamp=row.timestamp.replace(tzinfo=row.timestamp.tzinfo or UTC),
            actor=row.actor,
            payload=json.loads(row.payload_json),
            prev_hash=row.prev_hash,
            hash=row.hash,
        )

    @staticmethod
    def _usage_int(usage: dict[str, Any], *keys: str) -> int:
        for key in keys:
            value = usage.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                return max(value, 0)
        return 0
