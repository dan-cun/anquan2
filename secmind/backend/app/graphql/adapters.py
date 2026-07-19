from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
import strawberry
from graphql import GraphQLError

from app.database.models import (
    AgentDelegationRow,
    AgentMessageRow,
    ArtifactRow,
    EvidenceRow,
    FindingRow,
    LLMUsageRow,
    MCPServerRow,
    MessageChainRow,
    MessageEntryRow,
    PromptRow,
    SubtaskRow,
    TaskRow,
    ToolCallRow,
)
from app.graphql import converters, types
from app.graphql.ports import GraphQLBackend
from app.schemas.agents import AgentMessage, AgentRole, AgentTask
from app.schemas.flow import FlowStatus
from app.schemas.mcp import MCPServerConfig, MCPServerStatus
from app.schemas.prompts import (
    PromptMessageRole,
    PromptTemplateRecord,
    PromptVersionRecord,
)
from app.schemas.runtime import LedgerEvent
from app.schemas.tools import CapabilityKind, ToolExecutionStatus

if TYPE_CHECKING:
    from app.services.context import AppServices


def _optional(value: Any, default: Any = None) -> Any:
    return default if value is strawberry.UNSET else value


def _task(row: TaskRow) -> types.Task:
    return types.Task(
        id=row.id,
        flow_id=row.flow_id,
        title=row.title,
        objective=row.objective,
        status=row.status,
        result=row.result_json or None,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _subtask(row: SubtaskRow) -> types.Subtask:
    return types.Subtask(
        id=row.id,
        task_id=row.task_id,
        title=row.title,
        description=row.description,
        status=row.status,
        agent_role=None if row.agent_role is None else AgentRole(row.agent_role),
        result=row.result_json or None,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class NativeGraphQLAdapter:
    """Concrete GraphQL ports backed by the integrated application services."""

    def __init__(self, services: AppServices) -> None:
        self.services = services
        self.repositories = services.repositories
        self._assistants: dict[str, types.Assistant] = {}

    async def list_flows(self) -> list[types.Flow]:
        return [converters.flow(item) for item in self.repositories.flows.list_flows()]

    async def get_flow(self, flow_id: str) -> types.Flow | None:
        item = self.repositories.flows.get_flow(flow_id)
        return None if item is None else converters.flow(item)

    async def list_tasks(self, flow_id: str) -> list[types.Task]:
        return [_task(item) for item in self.repositories.tasks.list_tasks(flow_id)]

    async def list_tasks_batch(self, flow_ids: list[str]) -> dict[str, list[types.Task]]:
        return {flow_id: await self.list_tasks(flow_id) for flow_id in flow_ids}

    async def list_subtasks(self, task_id: str) -> list[types.Subtask]:
        return [_subtask(item) for item in self.repositories.tasks.list_subtasks(task_id)]

    async def list_subtasks_batch(self, task_ids: list[str]) -> dict[str, list[types.Subtask]]:
        return {task_id: await self.list_subtasks(task_id) for task_id in task_ids}

    async def list_assistants(self, flow_id: str) -> list[types.Assistant]:
        return [item for item in self._assistants.values() if str(item.flow_id) == flow_id]

    async def create_flow(self, input: types.CreateFlowInput) -> types.Flow:
        item = self.repositories.flows.create_flow(
            title=_optional(input.title),
            initial_input=input.input,
        )
        self.services.ledger.append(
            item.id,
            event_type="flow.created",
            actor="graphql",
            payload={"title": item.title, "initial_input": input.input},
        )
        return converters.flow(item)

    async def submit_flow_input(
        self,
        flow_id: str,
        input: types.SubmitFlowInput,
    ) -> types.Flow:
        self.repositories.flows.update_status(flow_id, FlowStatus.running)
        _, result = await self.services.collaboration.submit(
            flow_id=flow_id,
            objective=input.content,
            metadata=dict(_optional(input.metadata, {}) or {}),
        )
        status = FlowStatus.finished if result.status.value == "completed" else FlowStatus.failed
        return converters.flow(self.repositories.flows.update_status(flow_id, status))

    async def stop_flow(self, flow_id: str, reason: str | None) -> types.Flow:
        event = self.services.runtime_ledger.append(
            flow_id,
            "flow.stopped",
            {"reason": reason},
            actor="graphql",
        )
        await self.services.runtime_events.publish(event.model_dump(mode="json"))
        return converters.flow(self.repositories.flows.update_status(flow_id, FlowStatus.failed))

    async def finish_flow(self, flow_id: str) -> types.Flow:
        return converters.flow(self.repositories.flows.update_status(flow_id, FlowStatus.finished))

    async def delete_flow(self, flow_id: str) -> bool:
        self.repositories.flows.delete_flow(flow_id)
        return True

    async def rename_flow(self, flow_id: str, title: str) -> types.Flow:
        return converters.flow(self.repositories.flows.rename_flow(flow_id, title))

    async def create_assistant(
        self,
        flow_id: str,
        input: types.CreateAssistantInput,
    ) -> types.Assistant:
        now = datetime.now(UTC)
        assistant = types.Assistant(
            id=hashlib.sha256(f"{flow_id}:{now.isoformat()}".encode()).hexdigest()[:36],
            flow_id=flow_id,
            title=_optional(input.title) or input.input[:80],
            status="created",
            use_agents=True if input.use_agents is None else input.use_agents,
            model_provider=_optional(input.model_provider),
            created_at=now,
            updated_at=now,
        )
        self._assistants[str(assistant.id)] = assistant
        return assistant

    async def call_assistant(
        self,
        flow_id: str,
        assistant_id: str,
        input: str,
        use_agents: bool,
    ) -> types.Assistant:
        assistant = self._assistants.get(assistant_id)
        if assistant is None or str(assistant.flow_id) != flow_id:
            raise GraphQLError("assistant not found")
        if use_agents:
            await self.services.collaboration.submit(flow_id=flow_id, objective=input)
        assistant.status = "completed"
        assistant.updated_at = datetime.now(UTC)
        return assistant

    async def stop_assistant(self, flow_id: str, assistant_id: str) -> types.Assistant:
        assistant = self._assistants.get(assistant_id)
        if assistant is None or str(assistant.flow_id) != flow_id:
            raise GraphQLError("assistant not found")
        assistant.status = "stopped"
        assistant.updated_at = datetime.now(UTC)
        return assistant

    async def delete_assistant(self, flow_id: str, assistant_id: str) -> bool:
        assistant = self._assistants.get(assistant_id)
        if assistant is None or str(assistant.flow_id) != flow_id:
            return False
        del self._assistants[assistant_id]
        return True

    async def retry_subtask(self, subtask_id: str) -> types.Subtask:
        return _subtask(self.repositories.tasks.update_subtask(subtask_id, status="running"))

    async def revise_plan(self, input: types.RevisePlanInput) -> types.Task:
        return _task(
            self.repositories.tasks.update_task(
                str(input.task_id),
                result={"revision": input.revision, "reason": input.reason},
            )
        )

    async def list_descriptors(self) -> list[types.AgentDescriptor]:
        return [
            converters.agent_descriptor(item) for item in self.services.agent_registry.descriptors()
        ]

    async def list_instances(
        self,
        flow_id: str,
        run_id: str | None,
    ) -> list[types.AgentInstance]:
        return [
            converters.agent_instance(item)
            for item in self.repositories.agents.list_instances(flow_id, run_id)
        ]

    async def list_delegations(
        self,
        flow_id: str,
        run_id: str | None,
    ) -> list[types.AgentDelegation]:
        statement = sa.select(AgentDelegationRow).where(AgentDelegationRow.flow_id == flow_id)
        if run_id is not None:
            statement = statement.where(AgentDelegationRow.run_id == run_id)
        with self.repositories.sessions() as session:
            rows = session.scalars(statement.order_by(AgentDelegationRow.created_at)).all()
            return [
                converters.agent_delegation(self.repositories.agents._delegation_schema(item))
                for item in rows
            ]

    async def list_messages(self, flow_id: str, after_sequence: int) -> list[types.AgentMessage]:
        statement = sa.select(AgentMessageRow).where(AgentMessageRow.flow_id == flow_id)
        if after_sequence:
            statement = statement.where(AgentMessageRow.sequence > after_sequence)
        with self.repositories.sessions() as session:
            rows = session.scalars(statement.order_by(AgentMessageRow.timestamp)).all()
            return [
                converters.agent_message(self.repositories.agents._message_schema(item))
                for item in rows
            ]

    async def delegate(self, input: types.DelegateAgentInput) -> types.AgentDelegation:
        task = AgentTask(
            run_id=str(input.run_id),
            flow_id=str(input.flow_id),
            subtask_id=_optional(input.subtask_id),
            parent_agent_instance_id=str(input.from_agent_instance_id),
            objective=input.objective,
            context_refs=list(_optional(input.context_refs, []) or []),
            constraints=list(_optional(input.constraints, []) or []),
            expected_outputs=list(_optional(input.expected_outputs, []) or []),
            metadata=dict(_optional(input.metadata, {}) or {}),
        )
        await self.services.agent_dispatcher.delegate_from(
            str(input.from_agent_instance_id),
            input.to_role,
            task,
        )
        values = self.repositories.agents.list_delegations(str(input.run_id))
        match = next((item for item in reversed(values) if item.task.task_id == task.task_id), None)
        if match is None:
            raise GraphQLError("delegation was not persisted")
        return converters.agent_delegation(match)

    async def list_tools(self) -> list[types.UnifiedTool]:
        return [converters.unified_tool(item) for item in self.services.tool_gateway.definitions()]

    async def list_tool_calls(
        self,
        flow_id: str,
        agent_instance_id: str | None,
    ) -> list[types.ToolCall]:
        statement = sa.select(ToolCallRow).where(ToolCallRow.flow_id == flow_id)
        if agent_instance_id is not None:
            statement = statement.where(ToolCallRow.agent_instance_id == agent_instance_id)
        with self.repositories.sessions() as session:
            rows = session.scalars(statement.order_by(ToolCallRow.created_at)).all()
            return [
                types.ToolCall(
                    invocation_id=row.invocation_id,
                    run_id=row.run_id,
                    flow_id=row.flow_id,
                    task_id=row.task_id,
                    subtask_id=row.subtask_id,
                    agent_instance_id=row.agent_instance_id,
                    tool_id=row.tool_id,
                    arguments=row.arguments_json,
                    status=ToolExecutionStatus(row.status),
                    text=row.text_result,
                    data=row.data_json,
                    artifact_refs=row.artifact_refs_json,
                    evidence_ids=row.evidence_ids_json,
                    error_code=row.error_code,
                    error_message=row.error_message,
                    duration_ms=row.duration_ms,
                )
                for row in rows
            ]

    async def list_message_chains(
        self,
        flow_id: str,
        agent_instance_id: str | None,
    ) -> list[types.MessageChain]:
        statement = sa.select(MessageChainRow).where(MessageChainRow.flow_id == flow_id)
        if agent_instance_id is not None:
            statement = statement.where(MessageChainRow.agent_instance_id == agent_instance_id)
        with self.repositories.sessions() as session:
            rows = session.scalars(statement.order_by(MessageChainRow.created_at)).all()
            result = []
            for row in rows:
                entries = session.scalars(
                    sa.select(MessageEntryRow)
                    .where(MessageEntryRow.chain_id == row.chain_id)
                    .order_by(MessageEntryRow.sequence)
                ).all()
                result.append(
                    types.MessageChain(
                        chain_id=row.chain_id,
                        run_id=row.run_id,
                        flow_id=row.flow_id,
                        task_id=row.task_id,
                        subtask_id=row.subtask_id,
                        agent_instance_id=row.agent_instance_id,
                        agent_role=AgentRole(row.agent_role),
                        model_provider=row.model_provider,
                        model=row.model,
                        summary=row.summary,
                        created_at=row.created_at,
                        updated_at=row.updated_at,
                        entries=[
                            types.MessageEntry(
                                entry_id=item.entry_id,
                                chain_id=item.chain_id,
                                role=item.role,
                                content=item.content,
                                content_data=item.content_json,
                                tool_call_id=item.tool_call_id,
                                sequence=item.sequence,
                                created_at=item.created_at,
                            )
                            for item in entries
                        ],
                    )
                )
            return result

    async def list_servers(self) -> list[types.MCPServer]:
        return [converters.mcp_server(item) for item in self.services.mcp_manager.snapshots()]

    async def list_capabilities(
        self,
        server_id: str | None,
        kind: CapabilityKind | None,
    ) -> list[types.MCPCapability]:
        values = self.services.mcp_manager.capabilities()
        return [
            converters.mcp_capability(item)
            for item in values
            if (server_id is None or item.server_id == server_id)
            and (kind is None or item.kind == kind)
        ]

    async def register_server(self, input: types.RegisterMCPServerInput) -> types.MCPServer:
        config = MCPServerConfig(
            server_id=str(input.server_id),
            name=input.name,
            transport=input.transport,
            command=_optional(input.command),
            args=list(_optional(input.args, []) or []),
            cwd=_optional(input.cwd),
            env_refs=dict(_optional(input.env_refs, {}) or {}),
            url=_optional(input.url),
            header_refs=dict(_optional(input.header_refs, {}) or {}),
            enabled=True if input.enabled is None else input.enabled,
            metadata=dict(_optional(input.metadata, {}) or {}),
        )
        if config.server_id in self.services.mcp_manager.configs:
            raise GraphQLError("MCP server already exists")
        self.services.mcp_manager.configs[config.server_id] = config
        self.repositories.mcp.upsert_server(config)
        snapshot = (
            await self.services.mcp_manager.connect(config.server_id)
            if config.enabled
            else self.repositories.mcp.get_server(config.server_id)
        )
        assert snapshot is not None
        self.repositories.mcp.upsert_server(
            snapshot.config,
            status=snapshot.status,
            protocol_version=snapshot.protocol_version,
            last_error=snapshot.error_message,
        )
        self.repositories.mcp.replace_capabilities(config.server_id, snapshot.capabilities)
        return converters.mcp_server(snapshot)

    async def update_server(
        self,
        server_id: str,
        input: types.UpdateMCPServerInput,
    ) -> types.MCPServer:
        current = self.services.mcp_manager.configs.get(server_id)
        if current is None:
            raise GraphQLError("MCP server not found")
        update = {
            name: value
            for name in (
                "name",
                "command",
                "args",
                "cwd",
                "env_refs",
                "url",
                "header_refs",
                "enabled",
                "metadata",
            )
            if (value := getattr(input, name)) is not strawberry.UNSET
        }
        config = current.model_copy(update=update)
        self.services.mcp_manager.configs[server_id] = config
        self.repositories.mcp.upsert_server(config)
        if config.enabled:
            snapshot = await self.services.mcp_manager.connect(server_id)
        else:
            await self.services.mcp_manager.disconnect(server_id)
            snapshot = self.repositories.mcp.upsert_server(
                config,
                status=MCPServerStatus.DISCONNECTED,
            )
        return converters.mcp_server(snapshot)

    async def remove_server(self, server_id: str) -> bool:
        if server_id not in self.services.mcp_manager.configs:
            return False
        await self.services.mcp_manager.disconnect(server_id)
        self.services.mcp_manager.configs.pop(server_id, None)
        with self.repositories.sessions.begin() as session:
            session.execute(sa.delete(MCPServerRow).where(MCPServerRow.server_id == server_id))
        return True

    async def refresh_capabilities(self, server_id: str | None) -> list[types.MCPServer]:
        snapshots = (
            [await self.services.mcp_manager.refresh(server_id)]
            if server_id is not None
            else await self.services.mcp_manager.refresh_all()
        )
        for snapshot in snapshots:
            self.repositories.mcp.upsert_server(
                snapshot.config,
                status=snapshot.status,
                protocol_version=snapshot.protocol_version,
                last_error=snapshot.error_message,
            )
            self.repositories.mcp.replace_capabilities(
                snapshot.config.server_id,
                snapshot.capabilities,
            )
        return [converters.mcp_server(item) for item in snapshots]

    async def list_prompts(self) -> list[types.PromptTemplate]:
        with self.repositories.sessions() as session:
            keys = list(
                session.scalars(sa.select(PromptRow.prompt_key).order_by(PromptRow.prompt_key))
            )
        values = []
        for key in keys:
            template = self.repositories.prompts.get_template(key)
            if template is not None:
                values.append(
                    converters.prompt_template(
                        template,
                        versions=self.repositories.prompts.list_versions(key),
                    )
                )
        return values

    async def get_prompt(self, prompt_key: str) -> types.PromptTemplate | None:
        template = self.repositories.prompts.get_template(prompt_key)
        return (
            None
            if template is None
            else converters.prompt_template(
                template,
                versions=self.repositories.prompts.list_versions(prompt_key),
            )
        )

    async def create_version(self, input: types.CreatePromptVersionInput) -> types.PromptVersion:
        prompt_key = str(input.prompt_key)
        template = self.repositories.prompts.get_template(prompt_key)
        if template is None:
            template = self.repositories.prompts.upsert_template(
                PromptTemplateRecord(
                    prompt_key=prompt_key,
                    name=prompt_key,
                    category="native",
                    message_role=PromptMessageRole.SYSTEM,
                )
            )
        versions = self.repositories.prompts.list_versions(prompt_key)
        record = PromptVersionRecord(
            prompt_key=prompt_key,
            version=len(versions) + 1,
            content=input.content,
            checksum=hashlib.sha256(input.content.encode()).hexdigest(),
            source=input.source or "graphql",
        )
        _ = template
        return converters.prompt_version(self.repositories.prompts.create_version(record))

    async def enable_version(self, prompt_key: str, version_id: str) -> types.PromptTemplate:
        self.repositories.prompts.activate_version(prompt_key, version_id)
        value = await self.get_prompt(prompt_key)
        if value is None:
            raise GraphQLError("prompt not found")
        return value

    async def import_workbook(self, workbook_ref: str) -> list[types.PromptTemplate]:
        try:
            templates = self.services.prompt_registry.import_workbook(Path(workbook_ref))
        except (OSError, ValueError) as error:
            raise GraphQLError(
                str(error),
                extensions={"code": "PROMPT_IMPORT_FAILED"},
            ) from error
        return [
            converters.prompt_template(
                template,
                versions=self.repositories.prompts.list_versions(template.prompt_key),
            )
            for template in templates
        ]

    async def list_approvals(self, run_id: str) -> list[types.Approval]:
        return [
            types.Approval(
                request_id=row.request_id,
                run_id=row.run_id,
                step_id=row.step_id,
                status=row.status,
                reason=row.reason,
                decision=row.decision,
                actor=row.actor,
                requested_at=row.requested_at,
                resolved_at=row.resolved_at,
            )
            for row in self.repositories.approvals.list_for_run(run_id)
        ]

    async def resolve_approval(
        self,
        run_id: str,
        request_id: str,
        approved: bool,
        reason: str | None,
    ) -> types.Approval:
        row = self.repositories.approvals.resolve(
            request_id,
            decision="approve" if approved else "reject",
            actor="graphql",
            reason=reason or "",
        )
        if row.run_id != run_id:
            raise GraphQLError("approval does not belong to run")
        return (await self.list_approvals(run_id))[-1]

    async def list_runtime_events(
        self,
        run_id: str,
        after_sequence: int,
    ) -> list[types.RuntimeEvent]:
        return [
            converters.runtime_event(item)
            for item in self.services.runtime_ledger.events(run_id, after_sequence, 10_000)
        ]

    async def get_report(self, run_id: str) -> types.Report | None:
        row = self.repositories.results.latest_report(run_id)
        if row is None:
            state = self.services.runtime_ledger.load_state(run_id)
            return (
                None if state is None or state.report is None else converters.report(state.report)
            )
        return types.Report(
            run_id=row.run_id,
            status=row.status,
            executive_summary=row.executive_summary,
            findings=row.findings_json,
            evidence=row.evidence_json,
            limitations=row.limitations_json,
            generated_at=row.generated_at,
        )

    async def list_artifacts(self, run_id: str) -> list[types.Artifact]:
        return [self._artifact(item) for item in self.repositories.results.list_artifacts(run_id)]

    async def list_evidence(self, run_id: str) -> list[types.Evidence]:
        return [self._evidence(item) for item in self.repositories.results.list_evidence(run_id)]

    async def list_findings(self, run_id: str) -> list[types.Finding]:
        return [self._finding(item) for item in self.repositories.results.list_findings(run_id)]

    async def usage_by_flow(self, flow_id: str) -> types.UsageStats:
        rows = self._usage_rows(flow_id)
        return types.UsageStats(
            request_count=len(rows),
            prompt_tokens=sum(item.prompt_tokens for item in rows),
            completion_tokens=sum(item.completion_tokens for item in rows),
            total_tokens=sum(item.total_tokens for item in rows),
            estimated_cost=sum(item.estimated_cost or 0 for item in rows) or None,
        )

    async def usage_by_agent(self, flow_id: str) -> dict[str, Any]:
        return self._group_usage(self._usage_rows(flow_id), "agent_role")

    async def usage_by_model(self, flow_id: str | None) -> dict[str, Any]:
        return self._group_usage(self._usage_rows(flow_id), "model")

    async def usage_by_tool(self, flow_id: str | None) -> dict[str, Any]:
        statement = sa.select(ToolCallRow)
        if flow_id is not None:
            statement = statement.where(ToolCallRow.flow_id == flow_id)
        with self.repositories.sessions() as session:
            rows = session.scalars(statement).all()
        values: dict[str, int] = {}
        for row in rows:
            values[row.tool_id] = values.get(row.tool_id, 0) + 1
        return values

    def _usage_rows(self, flow_id: str | None) -> list[LLMUsageRow]:
        statement = sa.select(LLMUsageRow)
        if flow_id is not None:
            statement = statement.where(LLMUsageRow.flow_id == flow_id)
        with self.repositories.sessions() as session:
            return list(session.scalars(statement).all())

    @staticmethod
    def _group_usage(rows: list[LLMUsageRow], field: str) -> dict[str, Any]:
        values: dict[str, dict[str, int]] = {}
        for row in rows:
            key = str(getattr(row, field) or "unknown")
            item = values.setdefault(key, {"requests": 0, "tokens": 0})
            item["requests"] += 1
            item["tokens"] += row.total_tokens
        return values

    @staticmethod
    def _artifact(row: ArtifactRow) -> types.Artifact:
        return types.Artifact(
            artifact_id=row.artifact_id,
            run_id=row.run_id,
            flow_id=row.flow_id,
            name=row.name,
            media_type=row.media_type,
            uri=row.uri,
            sha256=row.sha256,
            size_bytes=row.size_bytes,
            metadata=row.metadata_json,
            created_at=row.created_at,
        )

    @staticmethod
    def _evidence(row: EvidenceRow) -> types.Evidence:
        return types.Evidence(
            evidence_id=row.evidence_id,
            run_id=row.run_id,
            source=row.source,
            summary=row.summary,
            artifact_ref=row.artifact_ref,
            sha256=row.sha256,
            metadata=row.metadata_json,
            created_at=row.created_at,
        )

    @staticmethod
    def _finding(row: FindingRow) -> types.Finding:
        return types.Finding(
            finding_id=row.finding_id,
            run_id=row.run_id,
            subtask_id=row.subtask_id,
            rule_id=row.rule_id,
            severity=row.severity,
            confidence=row.confidence,
            path=row.path,
            line=row.line,
            title=row.title,
            description=row.description,
            remediation=row.remediation,
            evidence_ids=row.evidence_ids_json,
            raw=row.raw_json,
            created_at=row.created_at,
        )


class NativeGraphQLEventAdapter:
    def __init__(self, services: AppServices) -> None:
        self.services = services

    async def subscribe(self, topic: str, **filters: Any) -> AsyncIterator[Any]:
        run_id = filters.get("run_id")
        after_sequence = int(filters.get("after_sequence") or 0)
        if topic == "runtime.event" and run_id:
            for item in self.services.runtime_ledger.events(run_id, after_sequence, 10_000):
                yield converters.runtime_event(item)
            async with self.services.runtime_events.subscribe(run_id) as queue:
                while True:
                    yield converters.runtime_event(LedgerEvent.model_validate(await queue.get()))
        else:
            async for value in self._typed_events(topic, filters):
                yield value

    async def _typed_events(self, topic: str, filters: dict[str, Any]) -> AsyncIterator[Any]:
        flow_id = filters.get("flow_id")
        cursors: dict[str, int] = {}
        while True:
            run_ids = self.services.runtime_ledger.run_ids()
            for run_id in run_ids:
                for event in self.services.runtime_ledger.events(
                    run_id, cursors.get(run_id, 0), 1000
                ):
                    cursors[run_id] = event.sequence
                    if event.event_type != topic:
                        continue
                    payload_flow = event.payload.get("flow_id")
                    instance = event.payload.get("instance")
                    if payload_flow is None and isinstance(instance, dict):
                        payload_flow = instance.get("flow_id")
                    if flow_id is not None and payload_flow != flow_id:
                        continue
                    value = self._typed_value(topic, event.payload)
                    if value is not None:
                        yield value
            await asyncio.sleep(0.2)

    @staticmethod
    def _typed_value(topic: str, payload: dict[str, Any]) -> Any:
        if topic in {"agent.started"}:
            from app.schemas.agents import AgentInstance

            return converters.agent_instance(AgentInstance.model_validate(payload))
        if topic == "agent.delegated":
            from app.schemas.agents import AgentDelegation

            return converters.agent_delegation(AgentDelegation.model_validate(payload))
        if topic == "agent.message":
            return converters.agent_message(AgentMessage.model_validate(payload))
        if topic in {"agent.completed", "agent.failed"}:
            from app.schemas.agents import AgentResult

            return converters.agent_result(AgentResult.model_validate(payload["result"]))
        return None


def build_graphql_backend(services: AppServices) -> GraphQLBackend:
    adapter = services.graphql_adapter
    return GraphQLBackend(
        flows=adapter,
        agents=adapter,
        tools=adapter,
        mcp=adapter,
        prompts=adapter,
        audit=adapter,
        analytics=adapter,
        events=services.graphql_events,
    )
