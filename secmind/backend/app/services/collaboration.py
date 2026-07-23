from __future__ import annotations

import asyncio
import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from agents.dispatcher import AgentDispatcher
from agents.native import project_tool_data
from app.database.repositories import NativeRepositories
from app.schemas.agents import (
    AgentDelegation,
    AgentInstance,
    AgentMessage,
    AgentMessageKind,
    AgentResult,
    AgentRole,
    AgentStatus,
    AgentTask,
)
from app.schemas.runtime import (
    DecisionKind,
    DecisionRecord,
    EventContext,
    Evidence,
    Finding,
    RuntimeToolContext,
    ToolStatus,
)
from app.schemas.tools import (
    ToolExecutionStatus,
    ToolOrigin,
    UnifiedToolDefinition,
    UnifiedToolInvocation,
    UnifiedToolResult,
)
from app.services.runtime import RuntimeEventHub
from app.services.workspace import RuntimeWorkspaceResolver
from ledger.runtime_store import RuntimeLedgerStore
from llm.base import LLMMessage, LLMProvider, LLMResponse
from tools.mcp.gateway import UnifiedToolGateway
from tools.runtime import RuntimeToolRegistry
from tools.safety import redact_tool_value, safe_error_message

FINDING_SEVERITY_RANK = {"CRITICAL": 5, "HIGH": 4, "MEDIUM": 3, "LOW": 2, "UNKNOWN": 1}


def _deduplicated_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for finding in findings:
        key = (
            str(finding.get("rule_id") or "UNKNOWN").upper(),
            str(finding.get("path") or "unknown").replace("\\", "/"),
            str(finding.get("line") or ""),
            str(finding.get("title") or "").strip().lower(),
        )
        unique.setdefault(key, finding)
    return sorted(
        unique.values(),
        key=lambda item: (
            -FINDING_SEVERITY_RANK.get(str(item.get("severity") or "UNKNOWN").upper(), 0),
            str(item.get("path") or ""),
            int(item.get("line") or 0),
            str(item.get("rule_id") or ""),
        ),
    )


def _canonical_sha256(value: Any) -> str:
    body = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


class NativeDemoLLMProvider(LLMProvider):
    """Structured native collaboration fallback for explicitly enabled demo mode."""

    name = "native-demo"

    async def complete(self, messages: list[LLMMessage], **kwargs: Any) -> LLMResponse:
        stage = str(kwargs.get("stage") or "")
        has_observation = any(
            message.metadata.get("context_kind") == "observation" for message in messages
        )
        if stage == "agent.assistant" and not has_observation:
            body = {
                "action": "delegate",
                "role": "generator",
                "objective": "Create a concise execution plan for the authorized task.",
            }
        elif stage == "agent.generator":
            body = {
                "action": "complete",
                "summary": "The authorized task was decomposed into a bounded execution plan.",
                "data": {"mode": "demo", "steps": ["scope", "execute", "verify", "report"]},
            }
        else:
            body = {
                "action": "complete",
                "summary": "Native collaboration completed in demo mode.",
                "data": {"mode": "demo"},
            }
        return LLMResponse(
            content=json.dumps(body),
            model="native-demo",
            provider=self.name,
            raw={"stage": stage},
        )


def _run_id(payload: dict[str, Any]) -> str:
    direct = payload.get("run_id")
    if direct:
        return str(direct)
    instance = payload.get("instance")
    if isinstance(instance, dict) and instance.get("run_id"):
        return str(instance["run_id"])
    return "system-native"


class PersistedToolGateway:
    def __init__(
        self,
        *,
        gateway: UnifiedToolGateway,
        repositories: NativeRepositories,
        ledger: RuntimeLedgerStore,
        event_hub: RuntimeEventHub,
        workspace_resolver: RuntimeWorkspaceResolver | None = None,
    ) -> None:
        self.gateway = gateway
        self.repositories = repositories
        self.ledger = ledger
        self.event_hub = event_hub
        self.workspace_resolver = workspace_resolver
        self._run_opened_circuit_keys: dict[str, set[str]] = defaultdict(set)
        self.gateway.set_event_publisher(self._publish_gateway_event)

    def definitions(self) -> list[UnifiedToolDefinition]:
        return self.gateway.definitions()

    def definitions_for_run(self, run_id: str) -> list[UnifiedToolDefinition]:
        unavailable = self._run_unavailable_tool_ids(run_id)
        return [item for item in self.definitions() if item.tool_id not in unavailable]

    def run_circuit_state(self, run_id: str) -> dict[str, list[str]]:
        keys = sorted(self._run_opened_circuit_keys.get(run_id, set()))
        servers = sorted(
            key.removeprefix("server:") for key in keys if key.startswith("server:")
        )
        tools = sorted(
            item.tool_id
            for item in self.definitions()
            if item.server_id in servers or f"tool:{item.tool_id}" in keys
        )
        return {
            "opened_circuit_keys": keys,
            "unavailable_server_ids": servers,
            "unavailable_tool_ids": tools,
        }

    def restore_run_circuit_state(
        self,
        run_id: str,
        *,
        opened_circuit_keys: list[str] | None = None,
        unavailable_server_ids: list[str] | None = None,
        unavailable_tool_ids: list[str] | None = None,
    ) -> None:
        keys = {
            str(item)
            for item in (opened_circuit_keys or [])
            if str(item).startswith(("server:", "tool:"))
        }
        keys.update(f"server:{item}" for item in (unavailable_server_ids or []) if item)
        keys.update(f"tool:{item}" for item in (unavailable_tool_ids or []) if item)
        self._run_opened_circuit_keys[run_id].update(keys)

    async def invoke(self, invocation: UnifiedToolInvocation) -> UnifiedToolResult:
        invocation = self._bind_workspace(invocation)
        definition = next(
            (item for item in self.gateway.definitions() if item.tool_id == invocation.tool_id),
            None,
        )
        origin = ToolOrigin.MCP if definition is None else definition.origin
        server_id = None if definition is None else definition.server_id
        decision, invocation = self._decision_context(invocation, definition)
        safe_invocation = invocation.model_copy(
            update={
                "arguments": redact_tool_value(invocation.arguments),
                "metadata": redact_tool_value(invocation.metadata),
            },
            deep=True,
        )
        self.repositories.tool_calls.create_invocation(
            safe_invocation,
            origin=origin,
            server_id=server_id,
        )
        await self._publish(
            "decision.recorded",
            invocation,
            {
                "decision": decision.model_dump(mode="json"),
                "invocation_id": invocation.invocation_id,
                "tool_id": invocation.tool_id,
            },
        )
        self.repositories.tool_calls.mark_running(invocation.invocation_id)
        await self._publish("tool.started", invocation, safe_invocation.model_dump(mode="json"))
        if invocation.tool_id in self._run_unavailable_tool_ids(invocation.run_id):
            result = UnifiedToolResult(
                invocation_id=invocation.invocation_id,
                tool_id=invocation.tool_id,
                status=ToolExecutionStatus.FAILED,
                error_code="capability_unavailable",
                error_message="Tool is unavailable for this run after its MCP circuit opened",
                data={"run_circuit": True, "reason": "circuit_open"},
            )
        else:
            try:
                result = await self.gateway.invoke(invocation)
            except asyncio.CancelledError:
                result = UnifiedToolResult(
                    invocation_id=invocation.invocation_id,
                    tool_id=invocation.tool_id,
                    status=ToolExecutionStatus.CANCELLED,
                    error_code="tool_cancelled",
                    error_message="Tool call was cancelled by its caller",
                )
                await self._finalize(invocation, safe_invocation, result)
                raise
            except Exception as error:
                result = UnifiedToolResult(
                    invocation_id=invocation.invocation_id,
                    tool_id=invocation.tool_id,
                    status=ToolExecutionStatus.FAILED,
                    error_code="tool_gateway_error",
                    error_message=f"{type(error).__name__}: {safe_error_message(error)}",
                )
        self._record_result_circuit(invocation.run_id, result)
        await self._finalize(invocation, safe_invocation, result)
        return result

    def _run_unavailable_tool_ids(self, run_id: str) -> set[str]:
        state = self._run_opened_circuit_keys.get(run_id, set())
        return {
            item.tool_id
            for item in self.definitions()
            if f"tool:{item.tool_id}" in state
            or (item.server_id is not None and f"server:{item.server_id}" in state)
        }

    def _record_result_circuit(self, run_id: str, result: UnifiedToolResult) -> None:
        if result.error_code != "circuit_open":
            return
        key = str(result.data.get("circuit_key") or "")
        if key:
            self._run_opened_circuit_keys[run_id].add(key)

    def _bind_workspace(self, invocation: UnifiedToolInvocation) -> UnifiedToolInvocation:
        if self.workspace_resolver is None:
            return invocation
        metadata = dict(invocation.metadata)
        metadata["scope"] = self.workspace_resolver.scope(invocation.run_id)
        metadata["workspace_ref"] = self.workspace_resolver.context_refs(invocation.run_id)[0]
        return invocation.model_copy(update={"metadata": metadata}, deep=True)

    async def _finalize(
        self,
        invocation: UnifiedToolInvocation,
        safe_invocation: UnifiedToolInvocation,
        result: UnifiedToolResult,
    ) -> None:
        self.repositories.tool_calls.complete(result)
        await self._publish(
            self._terminal_event(result),
            invocation,
            {
                "invocation": safe_invocation.model_dump(mode="json"),
                "result": result.model_dump(mode="json"),
            },
        )

    async def _publish_gateway_event(
        self,
        event_type: str,
        invocation: UnifiedToolInvocation,
        payload: dict[str, Any],
    ) -> None:
        if event_type == "circuit.opened":
            key = str(payload.get("circuit_key") or "")
            if key:
                self._run_opened_circuit_keys[invocation.run_id].add(key)
        await self._publish(event_type, invocation, payload)

    async def _publish(
        self,
        event_type: str,
        invocation: UnifiedToolInvocation,
        payload: dict[str, Any],
    ) -> None:
        event = self.ledger.append(
            invocation.run_id,
            event_type,
            redact_tool_value(payload),
            actor="tool_gateway",
            context=self._event_context(invocation),
        )
        await self.event_hub.publish(event.model_dump(mode="json"))

    @staticmethod
    def _terminal_event(result: UnifiedToolResult) -> str:
        if result.status == ToolExecutionStatus.COMPLETED:
            return "tool.completed"
        if result.status == ToolExecutionStatus.TIMED_OUT:
            return "tool.timed_out"
        if result.status == ToolExecutionStatus.CANCELLED:
            return "tool.cancelled"
        if result.error_code in {
            "scope_violation",
            "circuit_open",
            "capability_unavailable",
        }:
            return "tool.blocked"
        return "tool.failed"

    @staticmethod
    def _event_context(invocation: UnifiedToolInvocation) -> EventContext:
        return EventContext(
            flow_id=invocation.flow_id,
            correlation_id=str(
                invocation.metadata.get("correlation_id") or invocation.invocation_id
            ),
            decision_id=str(invocation.metadata.get("decision_id") or "") or None,
            agent_instance_id=invocation.agent_instance_id,
            task_id=invocation.task_id,
            tool_invocation_id=invocation.invocation_id,
        )

    @staticmethod
    def _decision_context(
        invocation: UnifiedToolInvocation,
        definition: UnifiedToolDefinition | None,
    ) -> tuple[DecisionRecord, UnifiedToolInvocation]:
        metadata = redact_tool_value(invocation.metadata)
        supplied = metadata.get("decision") if isinstance(metadata, dict) else None
        decision: DecisionRecord | None = None
        if isinstance(supplied, dict):
            try:
                decision = DecisionRecord.model_validate(supplied)
            except ValueError:
                decision = None
        if decision is None:
            risk = None if definition is None else definition.annotations.get("risk_level")
            decision = DecisionRecord(
                decision_id=str(metadata.get("decision_id") or uuid4()),
                kind=DecisionKind.TOOL,
                goal=str(metadata.get("goal") or "执行当前任务所需的工具步骤"),
                decision=f"调用 {invocation.tool_id}",
                rationale_summary=str(
                    metadata.get("rationale_summary")
                    or "Agent 请求执行该工具；统一网关将在调用前检查范围、超时和熔断状态。"
                ),
                expected_outcome=str(
                    metadata.get("expected_outcome") or "获得可供后续分析引用的工具结果。"
                ),
                risk_summary=(
                    f"工具声明风险等级为 {risk}；执行范围以调用中声明的 scope 为准。"
                    if risk is not None
                    else "执行范围以调用中声明的 scope 为准。"
                ),
                model_id=(str(metadata["model_id"]) if metadata.get("model_id") else None),
                prompt_version=(
                    str(metadata["prompt_version"])
                    if metadata.get("prompt_version")
                    else None
                ),
            )
        enriched = dict(invocation.metadata)
        enriched.update(
            {
                "correlation_id": str(
                    invocation.metadata.get("correlation_id") or invocation.invocation_id
                ),
                "decision_id": decision.decision_id,
            }
        )
        return decision, invocation.model_copy(update={"metadata": enriched}, deep=True)


def register_runtime_tools(
    gateway: UnifiedToolGateway,
    runtime_registry: RuntimeToolRegistry,
    *,
    workspace_resolver: RuntimeWorkspaceResolver,
) -> None:
    for manifest in runtime_registry.manifests():
        tool_id = f"native:{manifest.name}"
        definition = UnifiedToolDefinition(
            tool_id=tool_id,
            name=manifest.name,
            description=manifest.description,
            origin=ToolOrigin.NATIVE,
            input_schema=manifest.input_schema,
            output_schema=manifest.output_schema,
            annotations={
                "risk_level": manifest.risk_level.value,
                "permissions": manifest.permissions,
                "idempotent": manifest.idempotent,
                "timeout_seconds": manifest.timeout_seconds,
            },
        )

        async def invoke_native(
            invocation: UnifiedToolInvocation,
            *,
            name: str = manifest.name,
        ) -> UnifiedToolResult:
            resolved_workspace = workspace_resolver.resolve(invocation.run_id)
            result = await runtime_registry.get(name).invoke(
                invocation.arguments,
                RuntimeToolContext(
                    run_id=invocation.run_id,
                    step_id=invocation.subtask_id or invocation.task_id or invocation.invocation_id,
                    workspace=str(resolved_workspace),
                    allowed_paths=[str(resolved_workspace)],
                ),
            )
            status = {
                ToolStatus.SUCCESS: ToolExecutionStatus.COMPLETED,
                ToolStatus.TIMEOUT: ToolExecutionStatus.TIMED_OUT,
            }.get(result.status, ToolExecutionStatus.FAILED)
            return UnifiedToolResult(
                invocation_id=invocation.invocation_id,
                tool_id=invocation.tool_id,
                status=status,
                text=result.summary,
                data=result.data,
                artifact_refs=result.artifacts,
                evidence_ids=[item.evidence_id for item in result.evidence],
                error_code=result.error_code,
                error_message=result.error_message,
                duration_ms=result.duration_ms,
            )

        gateway.register_native(definition, invoke_native)


@dataclass(slots=True)
class NativeCollaborationService:
    dispatcher: AgentDispatcher
    repositories: NativeRepositories
    ledger: RuntimeLedgerStore
    event_hub: RuntimeEventHub

    async def submit(
        self,
        *,
        flow_id: str,
        objective: str,
        run_id: str | None = None,
        task_id: str | None = None,
        context_refs: list[str] | None = None,
        constraints: list[str] | None = None,
        expected_outputs: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        role: AgentRole = AgentRole.ASSISTANT,
    ) -> tuple[str, AgentResult]:
        resolved_run_id = run_id or str(uuid4())
        task = AgentTask(
            task_id=task_id or str(uuid4()),
            run_id=resolved_run_id,
            flow_id=flow_id,
            objective=objective,
            context_refs=context_refs or [],
            constraints=constraints or [],
            expected_outputs=expected_outputs or [],
            metadata=metadata or {},
        )
        if self.repositories.tasks.get_task(task.task_id) is None:
            self.repositories.tasks.create_task(
                flow_id=flow_id,
                task_id=task.task_id,
                title=objective[:200],
                objective=objective,
                status="running",
            )
        else:
            self.repositories.tasks.update_task(task.task_id, status="running")
        result = await self.dispatcher.dispatch_root(role, task)
        self.repositories.tasks.update_task(
            task.task_id,
            status=result.status.value,
            result=result.model_dump(mode="json"),
        )
        return resolved_run_id, result

    def collect_run_products(self, run_id: str, result: AgentResult) -> dict[str, Any]:
        agent_results = [
            item.model_dump(mode="json")
            for instance in self.dispatcher.instances(run_id)
            if (item := self.dispatcher.result(instance.instance_id)) is not None
        ]
        artifacts = [
            {
                "artifact_id": row.artifact_id,
                "name": row.name,
                "media_type": row.media_type,
                "uri": row.uri,
                "sha256": row.sha256,
                "size_bytes": row.size_bytes,
                "metadata": row.metadata_json,
            }
            for row in self.repositories.results.list_artifacts(run_id)
        ]
        known_artifact_refs = {str(item["artifact_id"]) for item in artifacts}
        for reference in result.artifact_refs:
            if reference not in known_artifact_refs:
                artifacts.append(
                    {
                        "artifact_id": reference,
                        "uri": reference,
                        "source": "agent_result",
                    }
                )

        evidence = [
            Evidence(
                evidence_id=row.evidence_id,
                source=row.source,
                summary=row.summary,
                artifact_ref=row.artifact_ref,
                sha256=row.sha256,
                metadata=row.metadata_json,
            ).model_dump(mode="json")
            for row in self.repositories.results.list_evidence(run_id)
        ]
        raw_findings = [
            Finding(
                finding_id=row.finding_id,
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
            ).model_dump(mode="json")
            for row in self.repositories.results.list_findings(run_id)
        ]
        findings = _deduplicated_findings(raw_findings)
        tool_calls = [
            {
                "invocation_id": row.invocation_id,
                "tool_id": row.tool_id,
                "origin": row.origin,
                "server_id": row.server_id,
                "task_id": row.task_id,
                "subtask_id": row.subtask_id,
                "agent_instance_id": row.agent_instance_id,
                "arguments": row.arguments_json,
                "status": row.status,
                "text_result": row.text_result,
                "data": project_tool_data(row.data_json),
                "data_sha256": _canonical_sha256(row.data_json),
                "data_projected": True,
                "artifact_refs": row.artifact_refs_json,
                "evidence_ids": row.evidence_ids_json,
                "error_code": row.error_code,
                "error_message": row.error_message,
                "duration_ms": row.duration_ms,
            }
            for row in self.repositories.tool_calls.list_for_run(run_id)
        ]
        return {
            "agent_result": result.model_dump(mode="json"),
            "agent_results": agent_results,
            "artifacts": artifacts,
            "evidence": evidence,
            "findings": findings,
            "tool_calls": tool_calls,
        }

    async def start(
        self,
        *,
        flow_id: str,
        objective: str,
        role: AgentRole,
        run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AgentInstance:
        if self.repositories.flows.get_flow(flow_id) is None:
            raise KeyError(flow_id)
        task = AgentTask(
            run_id=run_id or str(uuid4()),
            flow_id=flow_id,
            objective=objective,
            metadata=metadata or {},
        )
        self.repositories.tasks.create_task(
            flow_id=flow_id,
            task_id=task.task_id,
            title=objective[:200],
            objective=objective,
            status="created",
        )
        return await self.dispatcher.start_root(role, task)

    async def send_message(
        self,
        *,
        from_agent_instance_id: str,
        to_agent_instance_id: str,
        summary: str,
        kind: AgentMessageKind,
        payload_ref: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AgentMessage:
        return await self.dispatcher.send_message(
            from_agent_instance_id=from_agent_instance_id,
            to_agent_instance_id=to_agent_instance_id,
            summary=summary,
            kind=kind,
            payload_ref=payload_ref,
            metadata=metadata,
        )

    async def wait_agent(
        self,
        agent_instance_id: str,
        *,
        timeout_seconds: float | None,
    ) -> AgentInstance:
        await self.dispatcher.wait_for_agent(
            agent_instance_id,
            timeout_seconds=timeout_seconds,
        )
        instance = self.repositories.agents.get_instance(agent_instance_id)
        if instance is None:
            raise KeyError(agent_instance_id)
        return instance

    async def stop_agent(self, agent_instance_id: str, *, reason: str) -> AgentInstance:
        await self.dispatcher.stop_agent(agent_instance_id, reason=reason)
        instance = self.repositories.agents.get_instance(agent_instance_id)
        if instance is None:
            raise KeyError(agent_instance_id)
        return instance

    async def publish_agent_event(
        self,
        event_type: str,
        payload: dict[str, Any],
        actor: str,
        context: EventContext | None = None,
    ) -> None:
        if event_type == "agent.created":
            self.repositories.agents.create_instance(AgentInstance.model_validate(payload))
        elif event_type == "agent.started":
            instance = AgentInstance.model_validate(payload)
            self.repositories.agents.update_instance_status(
                instance.instance_id,
                AgentStatus.RUNNING,
                started_at=instance.started_at,
                metadata=instance.metadata,
            )
        elif event_type == "agent.delegated":
            delegation = AgentDelegation.model_validate(payload)
            task = delegation.task
            self.repositories.tasks.create_task(
                flow_id=task.flow_id,
                task_id=task.task_id,
                title=task.objective[:200],
                objective=task.objective,
                status="created",
            )
            self.repositories.agents.create_delegation(delegation)
        elif event_type == "agent.message":
            message = AgentMessage.model_validate(payload)
            self.repositories.agents.append_message(message)
            delegation_id = str(message.metadata.get("delegation_id") or "")
            if message.kind == AgentMessageKind.RESPONSE and delegation_id:
                self.repositories.agents.complete_delegation(
                    delegation_id,
                    status=AgentStatus(str(message.metadata.get("status", "completed"))),
                    result_summary=message.summary,
                    to_agent_instance_id=message.from_agent_instance_id,
                )
        elif event_type in {"agent.waiting", "agent.resumed"}:
            instance = AgentInstance.model_validate(payload["instance"])
            self.repositories.agents.update_instance_status(
                instance.instance_id,
                instance.status,
                metadata=instance.metadata,
            )
        elif event_type in {"agent.completed", "agent.failed"}:
            instance = AgentInstance.model_validate(payload["instance"])
            result = AgentResult.model_validate(payload["result"])
            self.repositories.agents.update_instance_status(
                instance.instance_id,
                result.status,
                completed_at=result.completed_at,
                prompt_version_id=instance.prompt_version_id,
                metadata=instance.metadata,
            )
            if instance.task_id is not None:
                self.repositories.tasks.update_task(
                    instance.task_id,
                    status=result.status.value,
                    result=result.model_dump(mode="json"),
                )
        elif event_type == "agent.cancelled":
            raw_instance = payload.get("instance", payload)
            instance = AgentInstance.model_validate(raw_instance)
            self.repositories.agents.update_instance_status(
                instance.instance_id,
                AgentStatus.CANCELLED,
                completed_at=instance.completed_at,
                prompt_version_id=instance.prompt_version_id,
                metadata=instance.metadata,
            )
            result_payload = payload.get("result")
            if instance.task_id is not None and isinstance(result_payload, dict):
                self.repositories.tasks.update_task(
                    instance.task_id,
                    status=AgentStatus.CANCELLED.value,
                    result=result_payload,
                )

        run_id = _run_id(payload)
        event = self.ledger.append(run_id, event_type, payload, actor=actor, context=context)
        await self.event_hub.publish(event.model_dump(mode="json"))
