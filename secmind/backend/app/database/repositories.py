from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy import Engine, create_engine, func, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.database.models import (
    AgentDelegationRow,
    AgentInstanceRow,
    AgentMessageRow,
    ApprovalRow,
    ArtifactRow,
    ContextSnapshotRow,
    EvidenceRow,
    FindingRow,
    FlowRow,
    LLMCallRow,
    LLMUsageRow,
    MCPCapabilityRow,
    MCPServerRow,
    MessageChainRow,
    MessageEntryRow,
    NoteRow,
    PromptRow,
    PromptVersionRow,
    ReportRow,
    SkillLoadRow,
    SkillRow,
    SubtaskRow,
    TaskRow,
    TodoRow,
    ToolCallRow,
)
from app.schemas.agents import (
    AgentDelegation,
    AgentInstance,
    AgentMessage,
    AgentRole,
    AgentStatus,
)
from app.schemas.flow import Flow, FlowStatus
from app.schemas.long_term import (
    ContextSnapshot,
    NoteRecord,
    NoteStatus,
    SkillDefinition,
    SkillLoad,
    StructuredContext,
    TodoItem,
)
from app.schemas.mcp import (
    MCPCapability,
    MCPServerConfig,
    MCPServerSnapshot,
    MCPServerStatus,
)
from app.schemas.prompts import (
    PromptMessageRole,
    PromptTemplateRecord,
    PromptVersionRecord,
    PromptVersionStatus,
)
from app.schemas.tools import (
    CapabilityKind,
    ToolExecutionStatus,
    ToolOrigin,
    UnifiedToolInvocation,
    UnifiedToolResult,
)

SessionFactory = sessionmaker[Session]


def utc_now() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class FlowRepository:
    """Persistent replacement for the in-memory FlowStore."""

    def __init__(self, sessions: SessionFactory) -> None:
        self.sessions = sessions

    def create_flow(self, title: str | None = None, initial_input: str | None = None) -> Flow:
        flow_id = str(uuid4())
        resolved_title = title or self._title_from_input(initial_input) or "Untitled flow"
        now = utc_now()
        row = FlowRow(
            id=flow_id,
            title=resolved_title,
            status=FlowStatus.created.value,
            created_at=now,
            updated_at=now,
        )
        with self.sessions.begin() as session:
            session.add(row)
        return self._to_schema(row)

    def ensure_flow(self, flow_id: str, title: str | None = None) -> Flow:
        with self.sessions.begin() as session:
            row = session.get(FlowRow, flow_id)
            if row is not None:
                if row.deleted_at is not None:
                    raise ValueError(f"flow {flow_id} is deleted")
                return self._to_schema(row)
            now = utc_now()
            row = FlowRow(
                id=flow_id,
                title=title or f"Flow {flow_id}",
                status=FlowStatus.created.value,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
        return self._to_schema(row)

    def list_flows(self) -> list[Flow]:
        with self.sessions() as session:
            rows = session.scalars(
                select(FlowRow)
                .where(FlowRow.deleted_at.is_(None))
                .order_by(FlowRow.created_at.desc())
            ).all()
            return [self._to_schema(row) for row in rows]

    def get_flow(self, flow_id: str) -> Flow | None:
        with self.sessions() as session:
            row = session.scalar(
                select(FlowRow).where(
                    FlowRow.id == flow_id,
                    FlowRow.deleted_at.is_(None),
                )
            )
            return None if row is None else self._to_schema(row)

    def update_status(self, flow_id: str, status: FlowStatus) -> Flow:
        with self.sessions.begin() as session:
            row = session.get(FlowRow, flow_id)
            if row is None or row.deleted_at is not None:
                raise KeyError(flow_id)
            row.status = status.value
            row.updated_at = utc_now()
        return self._to_schema(row)

    def rename_flow(self, flow_id: str, title: str) -> Flow:
        normalized = title.strip()
        if not normalized:
            raise ValueError("flow title must not be blank")
        with self.sessions.begin() as session:
            row = session.get(FlowRow, flow_id)
            if row is None or row.deleted_at is not None:
                raise KeyError(flow_id)
            row.title = normalized[:200]
            row.updated_at = utc_now()
        return self._to_schema(row)

    def delete_flow(self, flow_id: str) -> Flow:
        with self.sessions.begin() as session:
            row = session.get(FlowRow, flow_id)
            if row is None or row.deleted_at is not None:
                raise KeyError(flow_id)
            row.deleted_at = utc_now()
            row.updated_at = row.deleted_at
        return self._to_schema(row)

    @staticmethod
    def _title_from_input(initial_input: str | None) -> str | None:
        if not initial_input:
            return None
        compact = " ".join(initial_input.split())
        return compact[:80] if compact else None

    @staticmethod
    def _to_schema(row: FlowRow) -> Flow:
        return Flow(
            id=row.id,
            title=row.title,
            status=FlowStatus(row.status),
            created_at=as_utc(row.created_at),
            updated_at=as_utc(row.updated_at),
        )


class TaskRepository:
    def __init__(self, sessions: SessionFactory) -> None:
        self.sessions = sessions

    def create_task(
        self,
        *,
        flow_id: str,
        title: str,
        objective: str,
        status: str = "created",
        task_id: str | None = None,
    ) -> TaskRow:
        now = utc_now()
        row = TaskRow(
            id=task_id or str(uuid4()),
            flow_id=flow_id,
            title=title,
            objective=objective,
            status=status,
            result_json={},
            created_at=now,
            updated_at=now,
        )
        with self.sessions.begin() as session:
            session.add(row)
        return row

    def list_tasks(self, flow_id: str) -> list[TaskRow]:
        with self.sessions() as session:
            return list(
                session.scalars(
                    select(TaskRow).where(TaskRow.flow_id == flow_id).order_by(TaskRow.created_at)
                ).all()
            )

    def get_task(self, task_id: str) -> TaskRow | None:
        with self.sessions() as session:
            return session.get(TaskRow, task_id)

    def update_task(
        self,
        task_id: str,
        *,
        status: str | None = None,
        result: dict[str, Any] | None = None,
    ) -> TaskRow:
        with self.sessions.begin() as session:
            row = session.get(TaskRow, task_id)
            if row is None:
                raise KeyError(task_id)
            if status is not None:
                row.status = status
            if result is not None:
                row.result_json = result
            row.updated_at = utc_now()
        return row

    def create_subtask(
        self,
        *,
        task_id: str,
        title: str,
        description: str,
        position: int,
        agent_role: str | None = None,
        dependencies: Sequence[str] = (),
        status: str = "created",
        subtask_id: str | None = None,
    ) -> SubtaskRow:
        now = utc_now()
        row = SubtaskRow(
            id=subtask_id or str(uuid4()),
            task_id=task_id,
            title=title,
            description=description,
            status=status,
            agent_role=agent_role,
            position=position,
            dependencies_json=list(dependencies),
            result_json={},
            created_at=now,
            updated_at=now,
        )
        with self.sessions.begin() as session:
            session.add(row)
        return row

    def list_subtasks(self, task_id: str) -> list[SubtaskRow]:
        with self.sessions() as session:
            return list(
                session.scalars(
                    select(SubtaskRow)
                    .where(SubtaskRow.task_id == task_id)
                    .order_by(SubtaskRow.position)
                ).all()
            )

    def update_subtask(
        self,
        subtask_id: str,
        *,
        status: str | None = None,
        result: dict[str, Any] | None = None,
    ) -> SubtaskRow:
        with self.sessions.begin() as session:
            row = session.get(SubtaskRow, subtask_id)
            if row is None:
                raise KeyError(subtask_id)
            if status is not None:
                row.status = status
            if result is not None:
                row.result_json = result
            row.updated_at = utc_now()
        return row


class AgentRepository:
    def __init__(self, sessions: SessionFactory) -> None:
        self.sessions = sessions

    def create_instance(self, instance: AgentInstance) -> AgentInstance:
        row = AgentInstanceRow(
            instance_id=instance.instance_id,
            run_id=instance.run_id,
            flow_id=instance.flow_id,
            role=instance.role.value,
            status=instance.status.value,
            task_id=instance.task_id,
            parent_instance_id=instance.parent_instance_id,
            prompt_version_id=instance.prompt_version_id,
            model_profile=instance.model_profile,
            metadata_json=instance.metadata,
            started_at=instance.started_at,
            updated_at=instance.updated_at,
            completed_at=instance.completed_at,
        )
        with self.sessions.begin() as session:
            session.add(row)
        return self._instance_schema(row)

    def get_instance(self, instance_id: str) -> AgentInstance | None:
        with self.sessions() as session:
            row = session.get(AgentInstanceRow, instance_id)
            return None if row is None else self._instance_schema(row)

    def list_instances(self, flow_id: str, run_id: str | None = None) -> list[AgentInstance]:
        statement = select(AgentInstanceRow).where(AgentInstanceRow.flow_id == flow_id)
        if run_id is not None:
            statement = statement.where(AgentInstanceRow.run_id == run_id)
        statement = statement.order_by(AgentInstanceRow.started_at, AgentInstanceRow.updated_at)
        with self.sessions() as session:
            return [self._instance_schema(row) for row in session.scalars(statement).all()]

    def update_instance_status(
        self,
        instance_id: str,
        status: AgentStatus,
        *,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        prompt_version_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AgentInstance:
        with self.sessions.begin() as session:
            row = session.get(AgentInstanceRow, instance_id)
            if row is None:
                raise KeyError(instance_id)
            row.status = status.value
            row.updated_at = utc_now()
            if started_at is not None:
                row.started_at = started_at
            if completed_at is not None:
                row.completed_at = completed_at
            if prompt_version_id is not None:
                row.prompt_version_id = prompt_version_id
            if metadata is not None:
                row.metadata_json = metadata
        return self._instance_schema(row)

    def create_delegation(self, delegation: AgentDelegation) -> AgentDelegation:
        row = AgentDelegationRow(
            delegation_id=delegation.delegation_id,
            run_id=delegation.run_id,
            flow_id=delegation.flow_id,
            from_agent_instance_id=delegation.from_agent_instance_id,
            to_role=delegation.to_role.value,
            to_agent_instance_id=delegation.to_agent_instance_id,
            agent_task_json=delegation.task.model_dump(mode="json"),
            status=delegation.status.value,
            result_summary=delegation.result_summary,
            created_at=delegation.created_at,
            completed_at=delegation.completed_at,
        )
        with self.sessions.begin() as session:
            session.add(row)
        return self._delegation_schema(row)

    def complete_delegation(
        self,
        delegation_id: str,
        *,
        status: AgentStatus,
        result_summary: str | None,
        to_agent_instance_id: str | None = None,
    ) -> AgentDelegation:
        with self.sessions.begin() as session:
            row = session.get(AgentDelegationRow, delegation_id)
            if row is None:
                raise KeyError(delegation_id)
            row.status = status.value
            row.result_summary = result_summary
            row.completed_at = utc_now()
            if to_agent_instance_id is not None:
                row.to_agent_instance_id = to_agent_instance_id
        return self._delegation_schema(row)

    def list_delegations(self, run_id: str) -> list[AgentDelegation]:
        with self.sessions() as session:
            rows = session.scalars(
                select(AgentDelegationRow)
                .where(AgentDelegationRow.run_id == run_id)
                .order_by(AgentDelegationRow.created_at)
            ).all()
            return [self._delegation_schema(row) for row in rows]

    def append_message(self, message: AgentMessage) -> AgentMessage:
        row = AgentMessageRow(
            message_id=message.message_id,
            run_id=message.run_id,
            flow_id=message.flow_id,
            from_agent_instance_id=message.from_agent_instance_id,
            to_agent_instance_id=message.to_agent_instance_id,
            to_role=None if message.to_role is None else message.to_role.value,
            kind=message.kind.value,
            summary=message.summary,
            payload_ref=message.payload_ref,
            metadata_json=message.metadata,
            sequence=message.sequence,
            timestamp=message.timestamp,
        )
        with self.sessions.begin() as session:
            session.add(row)
        return self._message_schema(row)

    def list_messages(self, run_id: str, after_sequence: int = 0) -> list[AgentMessage]:
        statement = select(AgentMessageRow).where(AgentMessageRow.run_id == run_id)
        if after_sequence > 0:
            statement = statement.where(AgentMessageRow.sequence > after_sequence)
        statement = statement.order_by(
            AgentMessageRow.sequence.asc().nulls_last(), AgentMessageRow.timestamp
        )
        with self.sessions() as session:
            return [self._message_schema(row) for row in session.scalars(statement).all()]

    def create_chain(
        self,
        *,
        run_id: str,
        flow_id: str,
        agent_instance_id: str,
        agent_role: AgentRole,
        model_provider: str,
        model: str,
        task_id: str | None = None,
        subtask_id: str | None = None,
        chain_id: str | None = None,
    ) -> MessageChainRow:
        now = utc_now()
        row = MessageChainRow(
            chain_id=chain_id or str(uuid4()),
            run_id=run_id,
            flow_id=flow_id,
            task_id=task_id,
            subtask_id=subtask_id,
            agent_instance_id=agent_instance_id,
            agent_role=agent_role.value,
            model_provider=model_provider,
            model=model,
            created_at=now,
            updated_at=now,
        )
        with self.sessions.begin() as session:
            session.add(row)
        return row

    def append_chain_entry(
        self,
        *,
        chain_id: str,
        role: str,
        content: str,
        content_data: dict[str, Any] | None = None,
        tool_call_id: str | None = None,
        sequence: int | None = None,
    ) -> MessageEntryRow:
        with self.sessions.begin() as session:
            if sequence is None:
                maximum = session.scalar(
                    select(func.max(MessageEntryRow.sequence)).where(
                        MessageEntryRow.chain_id == chain_id
                    )
                )
                sequence = int(maximum or 0) + 1
            row = MessageEntryRow(
                entry_id=str(uuid4()),
                chain_id=chain_id,
                role=role,
                content=content,
                content_json=content_data,
                tool_call_id=tool_call_id,
                sequence=sequence,
                created_at=utc_now(),
            )
            session.add(row)
            chain = session.get(MessageChainRow, chain_id)
            if chain is None:
                raise KeyError(chain_id)
            chain.updated_at = row.created_at
        return row

    @staticmethod
    def _instance_schema(row: AgentInstanceRow) -> AgentInstance:
        return AgentInstance(
            instance_id=row.instance_id,
            run_id=row.run_id,
            flow_id=row.flow_id,
            role=AgentRole(row.role),
            status=AgentStatus(row.status),
            task_id=row.task_id,
            parent_instance_id=row.parent_instance_id,
            prompt_version_id=row.prompt_version_id,
            model_profile=row.model_profile,
            metadata=row.metadata_json,
            started_at=as_utc(row.started_at),
            updated_at=as_utc(row.updated_at),
            completed_at=as_utc(row.completed_at),
        )

    @staticmethod
    def _delegation_schema(row: AgentDelegationRow) -> AgentDelegation:
        return AgentDelegation.model_validate(
            {
                "delegation_id": row.delegation_id,
                "run_id": row.run_id,
                "flow_id": row.flow_id,
                "from_agent_instance_id": row.from_agent_instance_id,
                "to_role": row.to_role,
                "to_agent_instance_id": row.to_agent_instance_id,
                "task": row.agent_task_json,
                "status": row.status,
                "result_summary": row.result_summary,
                "created_at": as_utc(row.created_at),
                "completed_at": as_utc(row.completed_at),
            }
        )

    @staticmethod
    def _message_schema(row: AgentMessageRow) -> AgentMessage:
        return AgentMessage.model_validate(
            {
                "message_id": row.message_id,
                "run_id": row.run_id,
                "flow_id": row.flow_id,
                "from_agent_instance_id": row.from_agent_instance_id,
                "to_agent_instance_id": row.to_agent_instance_id,
                "to_role": row.to_role,
                "kind": row.kind,
                "summary": row.summary,
                "payload_ref": row.payload_ref,
                "metadata": row.metadata_json,
                "sequence": row.sequence,
                "timestamp": as_utc(row.timestamp),
            }
        )


class PromptRepository:
    def __init__(self, sessions: SessionFactory) -> None:
        self.sessions = sessions

    def upsert_template(self, template: PromptTemplateRecord) -> PromptTemplateRecord:
        with self.sessions.begin() as session:
            row = session.get(PromptRow, template.prompt_key)
            if row is None:
                row = PromptRow(prompt_key=template.prompt_key)
                session.add(row)
            row.name = template.name
            row.category = template.category
            row.message_role = template.message_role.value
            row.agent_role = None if template.agent_role is None else template.agent_role.value
            row.source_path = template.source_path
            row.variables_json = template.variables
            row.metadata_json = template.metadata
            if template.active_version_id is not None:
                row.active_version_id = template.active_version_id
        return self._template_schema(row)

    def create_version(self, version: PromptVersionRecord) -> PromptVersionRecord:
        with self.sessions.begin() as session:
            template = session.get(PromptRow, version.prompt_key)
            if template is None:
                raise KeyError(version.prompt_key)
            exists = session.scalar(
                select(PromptVersionRow.version_id).where(
                    PromptVersionRow.prompt_key == version.prompt_key,
                    PromptVersionRow.version == version.version,
                )
            )
            if exists is not None:
                raise ValueError(
                    f"prompt version already exists: {version.prompt_key}@{version.version}"
                )
            if version.status == PromptVersionStatus.ACTIVE:
                self._archive_active(session, version.prompt_key)
            row = PromptVersionRow(
                version_id=version.version_id,
                prompt_key=version.prompt_key,
                version=version.version,
                content=version.content,
                variables_json=version.variables,
                checksum=version.checksum,
                status=version.status.value,
                source=version.source,
                created_at=version.created_at,
                activated_at=version.activated_at,
            )
            session.add(row)
            if version.status == PromptVersionStatus.ACTIVE:
                template.active_version_id = version.version_id
        return self._version_schema(row)

    def activate_version(self, prompt_key: str, version_id: str) -> PromptVersionRecord:
        with self.sessions.begin() as session:
            template = session.get(PromptRow, prompt_key)
            row = session.get(PromptVersionRow, version_id)
            if template is None or row is None or row.prompt_key != prompt_key:
                raise KeyError(version_id)
            self._archive_active(session, prompt_key)
            row.status = PromptVersionStatus.ACTIVE.value
            row.activated_at = utc_now()
            template.active_version_id = version_id
        return self._version_schema(row)

    def get_template(self, prompt_key: str) -> PromptTemplateRecord | None:
        with self.sessions() as session:
            row = session.get(PromptRow, prompt_key)
            return None if row is None else self._template_schema(row)

    def get_active_version(self, prompt_key: str) -> PromptVersionRecord | None:
        with self.sessions() as session:
            row = session.scalar(
                select(PromptVersionRow).where(
                    PromptVersionRow.prompt_key == prompt_key,
                    PromptVersionRow.status == PromptVersionStatus.ACTIVE.value,
                )
            )
            return None if row is None else self._version_schema(row)

    def list_versions(self, prompt_key: str) -> list[PromptVersionRecord]:
        with self.sessions() as session:
            rows = session.scalars(
                select(PromptVersionRow)
                .where(PromptVersionRow.prompt_key == prompt_key)
                .order_by(PromptVersionRow.version)
            ).all()
            return [self._version_schema(row) for row in rows]

    @staticmethod
    def _archive_active(session: Session, prompt_key: str) -> None:
        session.execute(
            update(PromptVersionRow)
            .where(
                PromptVersionRow.prompt_key == prompt_key,
                PromptVersionRow.status == PromptVersionStatus.ACTIVE.value,
            )
            .values(status=PromptVersionStatus.ARCHIVED.value)
        )

    @staticmethod
    def _template_schema(row: PromptRow) -> PromptTemplateRecord:
        return PromptTemplateRecord(
            prompt_key=row.prompt_key,
            name=row.name,
            category=row.category,
            message_role=PromptMessageRole(row.message_role),
            agent_role=None if row.agent_role is None else AgentRole(row.agent_role),
            source_path=row.source_path,
            variables=row.variables_json,
            active_version_id=row.active_version_id,
            metadata=row.metadata_json,
        )

    @staticmethod
    def _version_schema(row: PromptVersionRow) -> PromptVersionRecord:
        return PromptVersionRecord(
            version_id=row.version_id,
            prompt_key=row.prompt_key,
            version=row.version,
            content=row.content,
            variables=row.variables_json,
            checksum=row.checksum,
            status=PromptVersionStatus(row.status),
            source=row.source,
            created_at=as_utc(row.created_at),
            activated_at=as_utc(row.activated_at),
        )


class MCPRepository:
    def __init__(self, sessions: SessionFactory) -> None:
        self.sessions = sessions

    def upsert_server(
        self,
        config: MCPServerConfig,
        *,
        status: MCPServerStatus = MCPServerStatus.DISCONNECTED,
        protocol_version: str | None = None,
        last_error: str | None = None,
    ) -> MCPServerSnapshot:
        with self.sessions.begin() as session:
            row = session.get(MCPServerRow, config.server_id)
            if row is None:
                row = MCPServerRow(server_id=config.server_id, created_at=utc_now())
                session.add(row)
            row.name = config.name
            row.transport = config.transport.value
            row.command = config.command
            row.args_json = config.args
            row.cwd = config.cwd
            row.env_refs_json = config.env_refs
            row.url = config.url
            row.header_refs_json = config.header_refs
            row.enabled = config.enabled
            row.status = status.value
            row.protocol_version = protocol_version
            row.metadata_json = {
                **config.metadata,
                "connect_timeout_seconds": config.connect_timeout_seconds,
                "call_timeout_seconds": config.call_timeout_seconds,
            }
            row.last_error = last_error
            row.updated_at = utc_now()
        return self.get_server(config.server_id)  # type: ignore[return-value]

    def get_server(self, server_id: str) -> MCPServerSnapshot | None:
        with self.sessions() as session:
            row = session.get(MCPServerRow, server_id)
            if row is None:
                return None
            capabilities = session.scalars(
                select(MCPCapabilityRow)
                .where(MCPCapabilityRow.server_id == server_id)
                .order_by(MCPCapabilityRow.kind, MCPCapabilityRow.name)
            ).all()
            return self._snapshot(row, capabilities)

    def list_servers(self) -> list[MCPServerSnapshot]:
        with self.sessions() as session:
            rows = session.scalars(select(MCPServerRow).order_by(MCPServerRow.name)).all()
            snapshots = []
            for row in rows:
                capabilities = session.scalars(
                    select(MCPCapabilityRow).where(MCPCapabilityRow.server_id == row.server_id)
                ).all()
                snapshots.append(self._snapshot(row, capabilities))
            return snapshots

    def replace_capabilities(
        self, server_id: str, capabilities: Sequence[MCPCapability]
    ) -> list[MCPCapability]:
        now = utc_now()
        with self.sessions.begin() as session:
            if session.get(MCPServerRow, server_id) is None:
                raise KeyError(server_id)
            session.execute(
                sa.delete(MCPCapabilityRow).where(MCPCapabilityRow.server_id == server_id)
            )
            for capability in capabilities:
                if capability.server_id != server_id:
                    raise ValueError("capability server_id does not match target server")
                session.add(
                    MCPCapabilityRow(
                        capability_id=capability.capability_id,
                        server_id=server_id,
                        kind=capability.kind.value,
                        name=capability.name,
                        description=capability.description,
                        input_schema_json=capability.input_schema,
                        metadata_json=capability.metadata,
                        discovered_at=now,
                        updated_at=now,
                    )
                )
        snapshot = self.get_server(server_id)
        return [] if snapshot is None else snapshot.capabilities

    @staticmethod
    def _snapshot(row: MCPServerRow, capabilities: Sequence[MCPCapabilityRow]) -> MCPServerSnapshot:
        metadata = dict(row.metadata_json)
        connect_timeout = metadata.pop("connect_timeout_seconds", None)
        call_timeout = metadata.pop("call_timeout_seconds", None)
        config = MCPServerConfig(
            server_id=row.server_id,
            name=row.name,
            transport=row.transport,
            command=row.command,
            args=row.args_json,
            cwd=row.cwd,
            env_refs=row.env_refs_json,
            url=row.url,
            header_refs=row.header_refs_json,
            enabled=row.enabled,
            connect_timeout_seconds=connect_timeout,
            call_timeout_seconds=call_timeout,
            metadata=metadata,
        )
        return MCPServerSnapshot(
            config=config,
            status=MCPServerStatus(row.status),
            protocol_version=row.protocol_version,
            capabilities=[
                MCPCapability(
                    capability_id=item.capability_id,
                    server_id=item.server_id,
                    kind=CapabilityKind(item.kind),
                    name=item.name,
                    description=item.description,
                    input_schema=item.input_schema_json,
                    metadata=item.metadata_json,
                )
                for item in capabilities
            ],
            error_message=row.last_error,
        )


class ToolCallRepository:
    def __init__(self, sessions: SessionFactory) -> None:
        self.sessions = sessions

    def create_invocation(
        self,
        invocation: UnifiedToolInvocation,
        *,
        origin: ToolOrigin,
        server_id: str | None = None,
    ) -> ToolCallRow:
        now = utc_now()
        row = ToolCallRow(
            invocation_id=invocation.invocation_id,
            run_id=invocation.run_id,
            flow_id=invocation.flow_id,
            task_id=invocation.task_id,
            subtask_id=invocation.subtask_id,
            agent_instance_id=invocation.agent_instance_id,
            tool_id=invocation.tool_id,
            origin=origin.value,
            server_id=server_id,
            arguments_json=invocation.arguments,
            status=ToolExecutionStatus.CREATED.value,
            created_at=now,
            updated_at=now,
        )
        with self.sessions.begin() as session:
            session.add(row)
        return row

    def mark_running(self, invocation_id: str) -> ToolCallRow:
        with self.sessions.begin() as session:
            row = session.get(ToolCallRow, invocation_id)
            if row is None:
                raise KeyError(invocation_id)
            row.status = ToolExecutionStatus.RUNNING.value
            row.updated_at = utc_now()
        return row

    def complete(self, result: UnifiedToolResult) -> ToolCallRow:
        with self.sessions.begin() as session:
            row = session.get(ToolCallRow, result.invocation_id)
            if row is None:
                raise KeyError(result.invocation_id)
            if row.tool_id != result.tool_id:
                raise ValueError("tool result does not match persisted invocation")
            row.status = result.status.value
            row.text_result = result.text
            row.data_json = result.data
            row.artifact_refs_json = result.artifact_refs
            row.evidence_ids_json = result.evidence_ids
            row.error_code = result.error_code
            row.error_message = result.error_message
            row.duration_ms = result.duration_ms
            row.updated_at = utc_now()
            row.completed_at = row.updated_at
        return row

    def get(self, invocation_id: str) -> ToolCallRow | None:
        with self.sessions() as session:
            return session.get(ToolCallRow, invocation_id)

    def list_for_run(self, run_id: str) -> list[ToolCallRow]:
        with self.sessions() as session:
            return list(
                session.scalars(
                    select(ToolCallRow)
                    .where(ToolCallRow.run_id == run_id)
                    .order_by(ToolCallRow.created_at)
                ).all()
            )


class ResultRepository:
    def __init__(self, sessions: SessionFactory) -> None:
        self.sessions = sessions

    def record_artifact(
        self,
        *,
        artifact_id: str,
        run_id: str,
        flow_id: str,
        name: str,
        media_type: str,
        uri: str,
        sha256: str | None = None,
        size_bytes: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ArtifactRow:
        row = ArtifactRow(
            artifact_id=artifact_id,
            run_id=run_id,
            flow_id=flow_id,
            name=name,
            media_type=media_type,
            uri=uri,
            sha256=sha256,
            size_bytes=size_bytes,
            metadata_json=metadata or {},
            created_at=utc_now(),
        )
        with self.sessions.begin() as session:
            session.add(row)
        return row

    def record_evidence(
        self,
        *,
        evidence_id: str,
        run_id: str,
        source: str,
        summary: str,
        artifact_ref: str | None = None,
        sha256: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> EvidenceRow:
        row = EvidenceRow(
            evidence_id=evidence_id,
            run_id=run_id,
            source=source,
            summary=summary,
            artifact_ref=artifact_ref,
            sha256=sha256,
            metadata_json=metadata or {},
            created_at=utc_now(),
        )
        with self.sessions.begin() as session:
            session.add(row)
        return row

    def record_finding(
        self,
        *,
        finding_id: str,
        run_id: str,
        rule_id: str,
        severity: str,
        confidence: str,
        path: str,
        title: str,
        description: str,
        subtask_id: str | None = None,
        line: int | None = None,
        remediation: str | None = None,
        evidence_ids: Sequence[str] = (),
        raw: dict[str, Any] | None = None,
    ) -> FindingRow:
        row = FindingRow(
            finding_id=finding_id,
            run_id=run_id,
            subtask_id=subtask_id,
            rule_id=rule_id,
            severity=severity,
            confidence=confidence,
            path=path,
            line=line,
            title=title,
            description=description,
            remediation=remediation,
            evidence_ids_json=list(evidence_ids),
            raw_json=raw or {},
            created_at=utc_now(),
        )
        with self.sessions.begin() as session:
            session.add(row)
        return row

    def record_report(
        self,
        *,
        run_id: str,
        status: str,
        executive_summary: str,
        findings: Sequence[dict[str, Any]] = (),
        evidence: Sequence[dict[str, Any]] = (),
        limitations: Sequence[str] = (),
    ) -> ReportRow:
        with self.sessions.begin() as session:
            maximum = session.scalar(
                select(func.max(ReportRow.version)).where(ReportRow.run_id == run_id)
            )
            row = ReportRow(
                report_id=str(uuid4()),
                run_id=run_id,
                version=int(maximum or 0) + 1,
                status=status,
                executive_summary=executive_summary,
                findings_json=list(findings),
                evidence_json=list(evidence),
                limitations_json=list(limitations),
                generated_at=utc_now(),
            )
            session.add(row)
        return row

    def latest_report(self, run_id: str) -> ReportRow | None:
        with self.sessions() as session:
            return session.scalar(
                select(ReportRow)
                .where(ReportRow.run_id == run_id)
                .order_by(ReportRow.version.desc())
                .limit(1)
            )

    def list_artifacts(self, run_id: str) -> list[ArtifactRow]:
        with self.sessions() as session:
            return list(
                session.scalars(
                    select(ArtifactRow)
                    .where(ArtifactRow.run_id == run_id)
                    .order_by(ArtifactRow.created_at)
                ).all()
            )

    def list_evidence(self, run_id: str) -> list[EvidenceRow]:
        with self.sessions() as session:
            return list(
                session.scalars(
                    select(EvidenceRow)
                    .where(EvidenceRow.run_id == run_id)
                    .order_by(EvidenceRow.created_at)
                ).all()
            )

    def list_findings(self, run_id: str) -> list[FindingRow]:
        with self.sessions() as session:
            return list(
                session.scalars(
                    select(FindingRow)
                    .where(FindingRow.run_id == run_id)
                    .order_by(FindingRow.created_at)
                ).all()
            )


class ApprovalRepository:
    def __init__(self, sessions: SessionFactory) -> None:
        self.sessions = sessions

    def create(
        self,
        *,
        request_id: str,
        run_id: str,
        step_id: str,
        reason: str,
        tool_name: str | None = None,
        request: dict[str, Any] | None = None,
    ) -> ApprovalRow:
        row = ApprovalRow(
            request_id=request_id,
            run_id=run_id,
            step_id=step_id,
            tool_name=tool_name,
            status="pending",
            reason=reason,
            request_json=request or {},
            requested_at=utc_now(),
        )
        with self.sessions.begin() as session:
            session.add(row)
        return row

    def resolve(
        self,
        request_id: str,
        *,
        decision: str,
        actor: str,
        reason: str = "",
        response: dict[str, Any] | None = None,
    ) -> ApprovalRow:
        with self.sessions.begin() as session:
            row = session.get(ApprovalRow, request_id)
            if row is None:
                raise KeyError(request_id)
            if row.resolved_at is not None:
                raise ValueError(f"approval {request_id} is already resolved")
            row.status = "resolved"
            row.decision = decision
            row.actor = actor
            row.response_reason = reason
            row.response_json = response
            row.resolved_at = utc_now()
        return row

    def list_for_run(self, run_id: str) -> list[ApprovalRow]:
        with self.sessions() as session:
            return list(
                session.scalars(
                    select(ApprovalRow)
                    .where(ApprovalRow.run_id == run_id)
                    .order_by(ApprovalRow.requested_at)
                ).all()
            )


class LLMRepository:
    def __init__(self, sessions: SessionFactory) -> None:
        self.sessions = sessions

    def start_call(
        self,
        *,
        call_id: str,
        run_id: str,
        flow_id: str,
        provider: str,
        model: str,
        stage: str,
        agent_instance_id: str | None = None,
        chain_id: str | None = None,
        request_ref: str | None = None,
    ) -> LLMCallRow:
        row = LLMCallRow(
            call_id=call_id,
            run_id=run_id,
            flow_id=flow_id,
            agent_instance_id=agent_instance_id,
            chain_id=chain_id,
            provider=provider,
            model=model,
            stage=stage,
            status="running",
            request_ref=request_ref,
            duration_ms=0,
            created_at=utc_now(),
        )
        with self.sessions.begin() as session:
            session.add(row)
        return row

    def complete_call(
        self,
        call_id: str,
        *,
        status: str,
        response_ref: str | None = None,
        error_message: str | None = None,
        duration_ms: int = 0,
    ) -> LLMCallRow:
        with self.sessions.begin() as session:
            row = session.get(LLMCallRow, call_id)
            if row is None:
                raise KeyError(call_id)
            row.status = status
            row.response_ref = response_ref
            row.error_message = error_message
            row.duration_ms = duration_ms
            row.completed_at = utc_now()
        return row

    def record_usage(
        self,
        *,
        run_id: str,
        flow_id: str,
        provider: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        call_id: str | None = None,
        agent_instance_id: str | None = None,
        agent_role: str | None = None,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
        total_tokens: int | None = None,
        estimated_cost: float | None = None,
        duration_ms: int = 0,
        usage_id: str | None = None,
    ) -> LLMUsageRow:
        row = LLMUsageRow(
            usage_id=usage_id or str(uuid4()),
            call_id=call_id,
            run_id=run_id,
            flow_id=flow_id,
            agent_instance_id=agent_instance_id,
            agent_role=agent_role,
            provider=provider,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
            total_tokens=(
                prompt_tokens + completion_tokens if total_tokens is None else total_tokens
            ),
            estimated_cost=estimated_cost,
            duration_ms=duration_ms,
            created_at=utc_now(),
        )
        with self.sessions.begin() as session:
            session.add(row)
        return row

    def list_usage(self, run_id: str) -> list[LLMUsageRow]:
        with self.sessions() as session:
            return list(
                session.scalars(
                    select(LLMUsageRow)
                    .where(LLMUsageRow.run_id == run_id)
                    .order_by(LLMUsageRow.created_at)
                ).all()
            )

class LongTermRepository:
    def __init__(self, sessions: SessionFactory) -> None:
        self.sessions = sessions

    def upsert_skill(self, skill: SkillDefinition) -> SkillDefinition:
        with self.sessions.begin() as session:
            row = session.get(SkillRow, skill.skill_id)
            if row is None:
                row = SkillRow(
                    skill_id=skill.skill_id,
                    name=skill.name,
                    description=skill.description,
                    version=skill.version,
                    content=skill.content,
                    checksum=skill.checksum,
                    tags_json=skill.tags,
                    compatible_roles_json=skill.compatible_roles,
                    source=skill.source,
                    enabled=skill.enabled,
                    metadata_json=skill.metadata,
                    created_at=skill.created_at,
                    updated_at=skill.updated_at,
                )
                session.add(row)
            else:
                row.name = skill.name
                row.description = skill.description
                row.version = skill.version
                row.content = skill.content
                row.checksum = skill.checksum
                row.tags_json = skill.tags
                row.compatible_roles_json = skill.compatible_roles
                row.source = skill.source
                row.enabled = skill.enabled
                row.metadata_json = skill.metadata
                row.updated_at = utc_now()
        return self.get_skill(skill.skill_id)  # type: ignore[return-value]

    def get_skill(self, skill_id: str) -> SkillDefinition | None:
        with self.sessions() as session:
            row = session.get(SkillRow, skill_id)
            return None if row is None else self._skill(row)

    def list_skills(self, *, enabled: bool | None = None) -> list[SkillDefinition]:
        with self.sessions() as session:
            statement = select(SkillRow).order_by(SkillRow.name, SkillRow.skill_id)
            if enabled is not None:
                statement = statement.where(SkillRow.enabled == enabled)
            return [self._skill(row) for row in session.scalars(statement).all()]

    def add_skill_load(self, load: SkillLoad) -> SkillLoad:
        with self.sessions.begin() as session:
            session.add(
                SkillLoadRow(
                    load_id=load.load_id,
                    skill_id=load.skill_id,
                    run_id=load.run_id,
                    flow_id=load.flow_id,
                    agent_instance_id=load.agent_instance_id,
                    reason=load.reason,
                    loaded_at=load.loaded_at,
                    unloaded_at=load.unloaded_at,
                )
            )
        return load

    def list_skill_loads(
        self,
        run_id: str,
        *,
        agent_instance_id: str | None = None,
        active_only: bool = True,
    ) -> list[SkillLoad]:
        with self.sessions() as session:
            statement = select(SkillLoadRow).where(SkillLoadRow.run_id == run_id)
            if agent_instance_id is not None:
                statement = statement.where(
                    sa.or_(
                        SkillLoadRow.agent_instance_id.is_(None),
                        SkillLoadRow.agent_instance_id == agent_instance_id,
                    )
                )
            if active_only:
                statement = statement.where(SkillLoadRow.unloaded_at.is_(None))
            rows = session.scalars(statement.order_by(SkillLoadRow.loaded_at)).all()
            return [self._skill_load(row) for row in rows]

    def unload_skill(self, load_id: str) -> SkillLoad:
        with self.sessions.begin() as session:
            row = session.get(SkillLoadRow, load_id)
            if row is None:
                raise KeyError(load_id)
            row.unloaded_at = utc_now()
        return self._skill_load(row)

    def create_todo(self, todo: TodoItem) -> TodoItem:
        with self.sessions.begin() as session:
            session.add(self._todo_row(todo))
        return todo

    def get_todo(self, todo_id: str) -> TodoItem | None:
        with self.sessions() as session:
            row = session.get(TodoRow, todo_id)
            return None if row is None else self._todo(row)

    def update_todo(self, todo: TodoItem) -> TodoItem:
        with self.sessions.begin() as session:
            row = session.get(TodoRow, todo.todo_id)
            if row is None:
                raise KeyError(todo.todo_id)
            for name, value in {
                "title": todo.title,
                "description": todo.description,
                "status": todo.status.value,
                "priority": int(todo.priority),
                "position": todo.position,
                "depends_on_json": todo.depends_on,
                "evidence_ids_json": todo.evidence_ids,
                "updated_at": todo.updated_at,
                "completed_at": todo.completed_at,
            }.items():
                setattr(row, name, value)
        return todo

    def list_todos(self, run_id: str) -> list[TodoItem]:
        with self.sessions() as session:
            rows = session.scalars(
                select(TodoRow)
                .where(TodoRow.run_id == run_id)
                .order_by(TodoRow.position, TodoRow.created_at)
            ).all()
            return [self._todo(row) for row in rows]

    def record_note(self, note: NoteRecord) -> NoteRecord:
        with self.sessions.begin() as session:
            session.add(
                NoteRow(
                    note_id=note.note_id,
                    run_id=note.run_id,
                    flow_id=note.flow_id,
                    agent_instance_id=note.agent_instance_id,
                    kind=note.kind.value,
                    content=note.content,
                    status=note.status.value,
                    evidence_ids_json=note.evidence_ids,
                    tags_json=note.tags,
                    created_at=note.created_at,
                    updated_at=note.updated_at,
                )
            )
        return note

    def archive_note(self, note_id: str) -> NoteRecord:
        with self.sessions.begin() as session:
            row = session.get(NoteRow, note_id)
            if row is None:
                raise KeyError(note_id)
            row.status = NoteStatus.ARCHIVED.value
            row.updated_at = utc_now()
        return self._note(row)

    def list_notes(self, run_id: str, *, active_only: bool = True) -> list[NoteRecord]:
        with self.sessions() as session:
            statement = select(NoteRow).where(NoteRow.run_id == run_id)
            if active_only:
                statement = statement.where(NoteRow.status == NoteStatus.ACTIVE.value)
            rows = session.scalars(statement.order_by(NoteRow.created_at)).all()
            return [self._note(row) for row in rows]

    def save_snapshot(self, snapshot: ContextSnapshot) -> ContextSnapshot:
        with self.sessions.begin() as session:
            session.add(
                ContextSnapshotRow(
                    snapshot_id=snapshot.snapshot_id,
                    run_id=snapshot.run_id,
                    flow_id=snapshot.flow_id,
                    agent_instance_id=snapshot.agent_instance_id,
                    source_from_sequence=snapshot.source_from_sequence,
                    source_to_sequence=snapshot.source_to_sequence,
                    estimated_tokens_before=snapshot.estimated_tokens_before,
                    estimated_tokens_after=snapshot.estimated_tokens_after,
                    narrative_summary=snapshot.narrative_summary,
                    structured_json=snapshot.structured.model_dump(mode="json"),
                    created_at=snapshot.created_at,
                )
            )
        return snapshot

    def list_snapshots(self, run_id: str) -> list[ContextSnapshot]:
        with self.sessions() as session:
            rows = session.scalars(
                select(ContextSnapshotRow)
                .where(ContextSnapshotRow.run_id == run_id)
                .order_by(ContextSnapshotRow.source_to_sequence, ContextSnapshotRow.created_at)
            ).all()
            return [self._snapshot(row) for row in rows]

    @staticmethod
    def _skill(row: SkillRow) -> SkillDefinition:
        return SkillDefinition(
            skill_id=row.skill_id,
            name=row.name,
            description=row.description,
            version=row.version,
            content=row.content,
            checksum=row.checksum,
            tags=row.tags_json,
            compatible_roles=row.compatible_roles_json,
            source=row.source,
            enabled=row.enabled,
            metadata=row.metadata_json,
            created_at=as_utc(row.created_at),
            updated_at=as_utc(row.updated_at),
        )

    @staticmethod
    def _skill_load(row: SkillLoadRow) -> SkillLoad:
        return SkillLoad(
            load_id=row.load_id,
            skill_id=row.skill_id,
            run_id=row.run_id,
            flow_id=row.flow_id,
            agent_instance_id=row.agent_instance_id,
            reason=row.reason,
            loaded_at=as_utc(row.loaded_at),
            unloaded_at=as_utc(row.unloaded_at),
        )

    @staticmethod
    def _todo_row(todo: TodoItem) -> TodoRow:
        return TodoRow(
            todo_id=todo.todo_id,
            run_id=todo.run_id,
            flow_id=todo.flow_id,
            task_id=todo.task_id,
            agent_instance_id=todo.agent_instance_id,
            title=todo.title,
            description=todo.description,
            status=todo.status.value,
            priority=int(todo.priority),
            position=todo.position,
            depends_on_json=todo.depends_on,
            evidence_ids_json=todo.evidence_ids,
            created_at=todo.created_at,
            updated_at=todo.updated_at,
            completed_at=todo.completed_at,
        )

    @staticmethod
    def _todo(row: TodoRow) -> TodoItem:
        return TodoItem(
            todo_id=row.todo_id,
            run_id=row.run_id,
            flow_id=row.flow_id,
            task_id=row.task_id,
            agent_instance_id=row.agent_instance_id,
            title=row.title,
            description=row.description,
            status=row.status,
            priority=row.priority,
            position=row.position,
            depends_on=row.depends_on_json,
            evidence_ids=row.evidence_ids_json,
            created_at=as_utc(row.created_at),
            updated_at=as_utc(row.updated_at),
            completed_at=as_utc(row.completed_at),
        )

    @staticmethod
    def _note(row: NoteRow) -> NoteRecord:
        return NoteRecord(
            note_id=row.note_id,
            run_id=row.run_id,
            flow_id=row.flow_id,
            agent_instance_id=row.agent_instance_id,
            kind=row.kind,
            content=row.content,
            status=row.status,
            evidence_ids=row.evidence_ids_json,
            tags=row.tags_json,
            created_at=as_utc(row.created_at),
            updated_at=as_utc(row.updated_at),
        )

    @staticmethod
    def _snapshot(row: ContextSnapshotRow) -> ContextSnapshot:
        return ContextSnapshot(
            snapshot_id=row.snapshot_id,
            run_id=row.run_id,
            flow_id=row.flow_id,
            agent_instance_id=row.agent_instance_id,
            source_from_sequence=row.source_from_sequence,
            source_to_sequence=row.source_to_sequence,
            estimated_tokens_before=row.estimated_tokens_before,
            estimated_tokens_after=row.estimated_tokens_after,
            narrative_summary=row.narrative_summary,
            structured=StructuredContext.model_validate(row.structured_json),
            created_at=as_utc(row.created_at),
        )


@dataclass(frozen=True)
class NativeRepositories:
    engine: Engine
    sessions: SessionFactory
    flows: FlowRepository
    tasks: TaskRepository
    agents: AgentRepository
    prompts: PromptRepository
    mcp: MCPRepository
    tool_calls: ToolCallRepository
    results: ResultRepository
    approvals: ApprovalRepository
    llm: LLMRepository
    long_term: LongTermRepository


def create_native_repositories(database_url: str, *, echo: bool = False) -> NativeRepositories:
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, future=True, echo=echo, connect_args=connect_args)
    if database_url.startswith("sqlite"):

        @sa.event.listens_for(engine, "connect")
        def enable_sqlite_foreign_keys(dbapi_connection: Any, _connection_record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    sessions = sessionmaker(engine, expire_on_commit=False)
    return NativeRepositories(
        engine=engine,
        sessions=sessions,
        flows=FlowRepository(sessions),
        tasks=TaskRepository(sessions),
        agents=AgentRepository(sessions),
        prompts=PromptRepository(sessions),
        mcp=MCPRepository(sessions),
        tool_calls=ToolCallRepository(sessions),
        results=ResultRepository(sessions),
        approvals=ApprovalRepository(sessions),
        llm=LLMRepository(sessions),
        long_term=LongTermRepository(sessions),
    )
