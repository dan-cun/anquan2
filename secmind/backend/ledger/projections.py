from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String, Text, delete, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.schemas.runtime import LedgerEvent, RunStatus, Scenario
from ledger.runtime_store import Base, LedgerIntegrityError, RuntimeLedgerStore, canonical_json

PROJECTOR_NAME = "runtime-v1"
TERMINAL_RUN_STATUSES = {
    RunStatus.COMPLETED.value,
    RunStatus.PARTIAL.value,
    RunStatus.DENIED.value,
    RunStatus.FAILED.value,
}


class ProjectionRunRow(Base):
    __tablename__ = "projection_runs"

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[str] = mapped_column(String(30), index=True)
    scenario: Mapped[str] = mapped_column(String(50), index=True)
    objective: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_step: Mapped[int] = mapped_column(Integer)
    total_steps: Mapped[int] = mapped_column(Integer)
    active_step_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    finding_count: Mapped[int] = mapped_column(Integer)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_sequence: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProjectionStepRow(Base):
    __tablename__ = "projection_steps"

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    step_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    step_index: Mapped[int] = mapped_column(Integer)
    objective: Mapped[str] = mapped_column(Text)
    agent_role: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(30), index=True)
    risk_level: Mapped[int] = mapped_column(Integer)
    attempt_count: Mapped[int] = mapped_column(Integer)
    finding_count: Mapped[int] = mapped_column(Integer)
    last_sequence: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProjectionApprovalRow(Base):
    __tablename__ = "projection_approvals"

    request_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    step_id: Mapped[str] = mapped_column(String(100), index=True)
    tool_name: Mapped[str] = mapped_column(String(100))
    risk_level: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), index=True)
    reason: Mapped[str] = mapped_column(Text)
    decision: Mapped[str | None] = mapped_column(String(30), nullable=True)
    actor: Mapped[str | None] = mapped_column(String(100), nullable=True)
    response_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_sequence: Mapped[int] = mapped_column(Integer)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProjectionFindingRow(Base):
    __tablename__ = "projection_findings"

    finding_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    step_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    rule_id: Mapped[str] = mapped_column(String(150), index=True)
    severity: Mapped[str] = mapped_column(String(20), index=True)
    confidence: Mapped[str] = mapped_column(String(20))
    path: Mapped[str] = mapped_column(Text)
    line: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    remediation: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload_json: Mapped[str] = mapped_column(Text)
    last_sequence: Mapped[int] = mapped_column(Integer)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ProjectionLLMUsageRow(Base):
    __tablename__ = "projection_llm_usage"

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    provider: Mapped[str] = mapped_column(String(80), primary_key=True)
    model: Mapped[str] = mapped_column(String(120), primary_key=True)
    request_count: Mapped[int] = mapped_column(Integer)
    prompt_tokens: Mapped[int] = mapped_column(Integer)
    completion_tokens: Mapped[int] = mapped_column(Integer)
    total_tokens: Mapped[int] = mapped_column(Integer)
    last_sequence: Mapped[int] = mapped_column(Integer)
    last_request_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ProjectionOffsetRow(Base):
    __tablename__ = "projection_offsets"

    projector_name: Mapped[str] = mapped_column(String(100), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    last_sequence: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ProjectionReducer:
    """Build disposable query models from the verified append-only event ledger."""

    def __init__(
        self,
        ledger: RuntimeLedgerStore,
        *,
        projector_name: str = PROJECTOR_NAME,
        batch_size: int = 500,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        self.ledger = ledger
        self.projector_name = projector_name
        self.batch_size = batch_size

    def project_run(self, run_id: str) -> int:
        if not self.ledger.verify(run_id):
            raise LedgerIntegrityError(f"hash-chain verification failed for run {run_id}")
        return self._project_verified_run(run_id)

    def rebuild(self, run_id: str | None = None) -> int:
        run_ids = [run_id] if run_id is not None else self.ledger.run_ids()
        invalid = [item for item in run_ids if not self.ledger.verify(item)]
        if invalid:
            joined = ", ".join(invalid)
            raise LedgerIntegrityError(f"hash-chain verification failed for run(s): {joined}")

        self.clear(run_id)
        return sum(self._project_verified_run(item) for item in run_ids)

    def clear(self, run_id: str | None = None) -> None:
        models = (
            ProjectionFindingRow,
            ProjectionApprovalRow,
            ProjectionStepRow,
            ProjectionLLMUsageRow,
            ProjectionRunRow,
            ProjectionOffsetRow,
        )
        with Session(self.ledger.engine) as session, session.begin():
            for model in models:
                statement = delete(model)
                if run_id is not None:
                    statement = statement.where(model.run_id == run_id)
                session.execute(statement)

    def offset(self, run_id: str) -> int:
        with Session(self.ledger.engine) as session:
            row = session.get(ProjectionOffsetRow, (self.projector_name, run_id))
            return 0 if row is None else row.last_sequence

    def _project_verified_run(self, run_id: str) -> int:
        processed = 0
        while True:
            after_sequence = self.offset(run_id)
            events = self.ledger.events(
                run_id,
                after_sequence=after_sequence,
                limit=self.batch_size,
            )
            if not events:
                return processed

            with Session(self.ledger.engine) as session, session.begin():
                offset = session.get(
                    ProjectionOffsetRow,
                    (self.projector_name, run_id),
                )
                current_sequence = 0 if offset is None else offset.last_sequence
                applied = [event for event in events if event.sequence > current_sequence]
                for event in applied:
                    self._apply(session, event)
                if applied:
                    last_event = applied[-1]
                    if offset is None:
                        offset = ProjectionOffsetRow(
                            projector_name=self.projector_name,
                            run_id=run_id,
                            last_sequence=last_event.sequence,
                            updated_at=last_event.timestamp,
                        )
                        session.add(offset)
                    else:
                        offset.last_sequence = last_event.sequence
                        offset.updated_at = last_event.timestamp
                    processed += len(applied)

            if len(events) < self.batch_size:
                return processed

    def _apply(self, session: Session, event: LedgerEvent) -> None:
        run = self._run(session, event)
        payload = event.payload
        event_type = event.event_type

        run.last_sequence = event.sequence
        run.updated_at = event.timestamp
        if event_type == "run.queued":
            run.status = RunStatus.PENDING.value
            run.objective = self._optional_string(payload.get("objective"))
        elif event_type == "scenario.classified":
            run.status = RunStatus.RUNNING.value
            run.scenario = self._string(payload.get("scenario"), Scenario.UNKNOWN.value)
        elif event_type == "plan.created":
            run.status = RunStatus.RUNNING.value
            self._apply_plan(session, run, event)
        elif event_type == "step.selected":
            self._select_step(session, run, event)
        elif event_type == "approval.requested":
            self._request_approval(session, run, event)
        elif event_type == "approval.resolved":
            self._resolve_approval(session, run, event)
        elif event_type == "tool.started":
            self._update_active_step(session, run, event, status="running", increment=True)
        elif event_type == "tool.completed":
            status = self._string(payload.get("status"), "completed")
            self._update_active_step(session, run, event, status=status)
        elif event_type == "verification.completed":
            status = "completed" if not payload.get("error") else "retrying"
            self._update_active_step(
                session,
                run,
                event,
                status=status,
                complete=not payload.get("error"),
            )
        elif event_type in {"finding.recorded", "analysis.completed", "report.generated"}:
            self._apply_findings(session, run, event)
        elif event_type == "llm.response":
            self._apply_llm_usage(session, event)

        if event_type in {"input.ingested", "run.started"}:
            run.status = RunStatus.RUNNING.value
        elif event_type in {"guardrail.denied"}:
            run.status = RunStatus.DENIED.value
            run.completed_at = event.timestamp
        elif event_type == "budget.exhausted":
            run.status = RunStatus.PARTIAL.value
        elif event_type == "run.failed":
            run.status = RunStatus.FAILED.value
            run.last_error = self._optional_string(payload.get("error"))
            run.completed_at = event.timestamp
        elif event_type in {"run.completed", "report.generated"}:
            status = self._string(payload.get("status"), RunStatus.COMPLETED.value)
            run.status = status
            if status in TERMINAL_RUN_STATUSES:
                run.completed_at = event.timestamp

    @staticmethod
    def _run(session: Session, event: LedgerEvent) -> ProjectionRunRow:
        row = session.get(ProjectionRunRow, event.run_id)
        if row is None:
            row = ProjectionRunRow(
                run_id=event.run_id,
                status=RunStatus.PENDING.value,
                scenario=Scenario.UNKNOWN.value,
                objective=None,
                current_step=0,
                total_steps=0,
                active_step_id=None,
                finding_count=0,
                last_error=None,
                last_sequence=0,
                created_at=event.timestamp,
                updated_at=event.timestamp,
                completed_at=None,
            )
            session.add(row)
        return row

    @staticmethod
    def _apply_plan(session: Session, run: ProjectionRunRow, event: LedgerEvent) -> None:
        steps = event.payload.get("steps")
        if not isinstance(steps, list):
            return
        run.total_steps = len(steps)
        for index, value in enumerate(steps):
            if not isinstance(value, dict):
                continue
            step_id = str(value.get("step_id") or f"step-{index}")
            row = session.get(ProjectionStepRow, (event.run_id, step_id))
            if row is None:
                row = ProjectionStepRow(
                    run_id=event.run_id,
                    step_id=step_id,
                    step_index=index,
                    objective=str(value.get("objective") or ""),
                    agent_role=str(value.get("agent_role") or "unknown"),
                    status="pending",
                    risk_level=ProjectionReducer._integer(value.get("risk_hint")),
                    attempt_count=0,
                    finding_count=0,
                    last_sequence=event.sequence,
                    started_at=None,
                    completed_at=None,
                )
                session.add(row)
            else:
                row.step_index = index
                row.objective = str(value.get("objective") or "")
                row.agent_role = str(value.get("agent_role") or "unknown")
                row.risk_level = ProjectionReducer._integer(value.get("risk_hint"))
                row.last_sequence = event.sequence

    @staticmethod
    def _select_step(session: Session, run: ProjectionRunRow, event: LedgerEvent) -> None:
        step_id = str(event.payload.get("step_id") or "")
        if not step_id:
            return
        run.active_step_id = step_id
        run.current_step = ProjectionReducer._integer(event.payload.get("index"))
        run.status = RunStatus.RUNNING.value
        row = session.get(ProjectionStepRow, (event.run_id, step_id))
        if row is not None:
            row.status = "running"
            row.started_at = row.started_at or event.timestamp
            row.last_sequence = event.sequence

    @staticmethod
    def _request_approval(session: Session, run: ProjectionRunRow, event: LedgerEvent) -> None:
        payload = event.payload
        request_id = str(payload.get("request_id") or event.event_id)
        row = session.get(ProjectionApprovalRow, request_id)
        if row is None:
            row = ProjectionApprovalRow(
                request_id=request_id,
                run_id=event.run_id,
                step_id=str(payload.get("step_id") or run.active_step_id or ""),
                tool_name=str(payload.get("tool_name") or "unknown"),
                risk_level=ProjectionReducer._integer(payload.get("risk_level")),
                status="pending",
                reason=str(payload.get("reason") or ""),
                decision=None,
                actor=None,
                response_reason=None,
                last_sequence=event.sequence,
                requested_at=event.timestamp,
                resolved_at=None,
            )
            session.add(row)
        run.status = RunStatus.WAITING_APPROVAL.value

    @staticmethod
    def _resolve_approval(session: Session, run: ProjectionRunRow, event: LedgerEvent) -> None:
        request_id = event.payload.get("request_id")
        row = session.get(ProjectionApprovalRow, str(request_id)) if request_id else None
        if row is None:
            row = session.scalars(
                select(ProjectionApprovalRow)
                .where(
                    ProjectionApprovalRow.run_id == event.run_id,
                    ProjectionApprovalRow.status == "pending",
                )
                .order_by(ProjectionApprovalRow.requested_at.desc())
                .limit(1)
            ).first()
        decision = ProjectionReducer._string(event.payload.get("decision"), "deny")
        if row is not None:
            row.status = "resolved"
            row.decision = decision
            row.actor = event.actor
            row.response_reason = ProjectionReducer._optional_string(event.payload.get("reason"))
            row.last_sequence = event.sequence
            row.resolved_at = event.timestamp
        run.status = RunStatus.DENIED.value if decision == "deny" else RunStatus.RUNNING.value

    @staticmethod
    def _update_active_step(
        session: Session,
        run: ProjectionRunRow,
        event: LedgerEvent,
        *,
        status: str,
        increment: bool = False,
        complete: bool = False,
    ) -> None:
        step_id = str(event.payload.get("step_id") or run.active_step_id or "")
        if not step_id:
            return
        row = session.get(ProjectionStepRow, (event.run_id, step_id))
        if row is None:
            return
        row.status = status
        row.last_sequence = event.sequence
        if increment:
            row.attempt_count += 1
            row.started_at = row.started_at or event.timestamp
        if complete:
            row.completed_at = event.timestamp

    @staticmethod
    def _apply_findings(session: Session, run: ProjectionRunRow, event: LedgerEvent) -> None:
        payload = event.payload
        values: list[Any]
        if isinstance(payload.get("findings"), list):
            values = payload["findings"]
        elif isinstance(payload.get("finding"), dict):
            values = [payload["finding"]]
        elif event.event_type == "finding.recorded":
            values = [payload]
        else:
            values = []

        for index, value in enumerate(values):
            if not isinstance(value, dict):
                continue
            finding_id = str(value.get("finding_id") or "")
            if not finding_id:
                seed = f"{event.event_id}:{index}".encode()
                finding_id = hashlib.sha256(seed).hexdigest()
            row = session.get(ProjectionFindingRow, finding_id)
            if row is None:
                row = ProjectionFindingRow(
                    finding_id=finding_id,
                    run_id=event.run_id,
                    step_id=ProjectionReducer._optional_string(
                        value.get("step_id") or run.active_step_id
                    ),
                    rule_id=str(value.get("rule_id") or "unknown"),
                    severity=ProjectionReducer._string(value.get("severity"), "UNKNOWN"),
                    confidence=ProjectionReducer._string(value.get("confidence"), "UNKNOWN"),
                    path=str(value.get("path") or ""),
                    line=ProjectionReducer._optional_integer(value.get("line")),
                    title=str(value.get("title") or "Untitled finding"),
                    description=str(value.get("description") or ""),
                    remediation=ProjectionReducer._optional_string(value.get("remediation")),
                    payload_json=canonical_json(value),
                    last_sequence=event.sequence,
                    recorded_at=event.timestamp,
                )
                session.add(row)
                run.finding_count += 1
                if run.active_step_id:
                    step = session.get(
                        ProjectionStepRow,
                        (event.run_id, run.active_step_id),
                    )
                    if step is not None:
                        step.finding_count += 1

    @staticmethod
    def _apply_llm_usage(session: Session, event: LedgerEvent) -> None:
        payload = event.payload
        raw = payload.get("raw") if isinstance(payload.get("raw"), dict) else {}
        usage = raw.get("usage") if isinstance(raw.get("usage"), dict) else {}
        prompt_tokens = ProjectionReducer._usage_int(usage, "prompt_tokens", "input_tokens")
        completion_tokens = ProjectionReducer._usage_int(
            usage,
            "completion_tokens",
            "output_tokens",
        )
        total_tokens = ProjectionReducer._usage_int(usage, "total_tokens")
        if total_tokens == 0:
            total_tokens = prompt_tokens + completion_tokens
        provider = str(payload.get("provider") or "unknown")
        model = str(payload.get("model") or "unknown")
        row = session.get(ProjectionLLMUsageRow, (event.run_id, provider, model))
        if row is None:
            row = ProjectionLLMUsageRow(
                run_id=event.run_id,
                provider=provider,
                model=model,
                request_count=0,
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                last_sequence=event.sequence,
                last_request_at=event.timestamp,
            )
            session.add(row)
        row.request_count += 1
        row.prompt_tokens += prompt_tokens
        row.completion_tokens += completion_tokens
        row.total_tokens += total_tokens
        row.last_sequence = event.sequence
        row.last_request_at = event.timestamp

    @staticmethod
    def _string(value: Any, default: str) -> str:
        if hasattr(value, "value"):
            value = value.value
        text = str(value or "").strip()
        return text or default

    @staticmethod
    def _optional_string(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _integer(value: Any) -> int:
        return ProjectionReducer._optional_integer(value) or 0

    @staticmethod
    def _optional_integer(value: Any) -> int | None:
        if isinstance(value, bool) or value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _usage_int(usage: dict[str, Any], *keys: str) -> int:
        for key in keys:
            value = usage.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                return max(value, 0)
        return 0


def projection_snapshot(ledger: RuntimeLedgerStore, run_id: str) -> dict[str, Any]:
    """Return a deterministic snapshot used by replay verification and tests."""
    with Session(ledger.engine) as session:
        run = session.get(ProjectionRunRow, run_id)
        steps = session.scalars(
            select(ProjectionStepRow)
            .where(ProjectionStepRow.run_id == run_id)
            .order_by(ProjectionStepRow.step_index, ProjectionStepRow.step_id)
        ).all()
        approvals = session.scalars(
            select(ProjectionApprovalRow)
            .where(ProjectionApprovalRow.run_id == run_id)
            .order_by(ProjectionApprovalRow.requested_at, ProjectionApprovalRow.request_id)
        ).all()
        findings = session.scalars(
            select(ProjectionFindingRow)
            .where(ProjectionFindingRow.run_id == run_id)
            .order_by(ProjectionFindingRow.finding_id)
        ).all()
        usage = session.scalars(
            select(ProjectionLLMUsageRow)
            .where(ProjectionLLMUsageRow.run_id == run_id)
            .order_by(ProjectionLLMUsageRow.provider, ProjectionLLMUsageRow.model)
        ).all()

        def values(row: Any, columns: tuple[str, ...]) -> dict[str, Any]:
            return {column: getattr(row, column) for column in columns}

        payload = {
            "run": None
            if run is None
            else values(
                run,
                (
                    "run_id",
                    "status",
                    "scenario",
                    "objective",
                    "current_step",
                    "total_steps",
                    "active_step_id",
                    "finding_count",
                    "last_error",
                    "last_sequence",
                ),
            ),
            "steps": [
                values(
                    row,
                    (
                        "step_id",
                        "step_index",
                        "status",
                        "attempt_count",
                        "finding_count",
                        "last_sequence",
                    ),
                )
                for row in steps
            ],
            "approvals": [
                values(row, ("request_id", "step_id", "status", "decision", "last_sequence"))
                for row in approvals
            ],
            "findings": [
                values(row, ("finding_id", "rule_id", "severity", "last_sequence"))
                for row in findings
            ],
            "llm_usage": [
                values(
                    row,
                    (
                        "provider",
                        "model",
                        "request_count",
                        "prompt_tokens",
                        "completion_tokens",
                        "total_tokens",
                        "last_sequence",
                    ),
                )
                for row in usage
            ],
        }
        return json.loads(json.dumps(payload, default=str))
