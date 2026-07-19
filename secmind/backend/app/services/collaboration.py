from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from agents.dispatcher import AgentDispatcher
from agents.guardrail import Guardrail
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
from app.schemas.runtime import RuntimeToolContext, ToolStatus
from app.schemas.tools import (
    ToolExecutionStatus,
    ToolOrigin,
    UnifiedToolDefinition,
    UnifiedToolInvocation,
    UnifiedToolResult,
)
from app.services.runtime import RuntimeEventHub
from ledger.runtime_store import RuntimeLedgerStore
from llm.base import LLMMessage, LLMProvider, LLMResponse
from tools.mcp.gateway import UnifiedToolGateway
from tools.runtime import RuntimeToolBroker, RuntimeToolRegistry


class NativeDemoLLMProvider(LLMProvider):
    """Structured native collaboration fallback for explicitly enabled demo mode."""

    name = "native-demo"

    async def complete(self, messages: list[LLMMessage], **kwargs: Any) -> LLMResponse:
        stage = str(kwargs.get("stage") or "")
        has_observation = any(message.role == "tool" for message in messages)
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
    ) -> None:
        self.gateway = gateway
        self.repositories = repositories
        self.ledger = ledger
        self.event_hub = event_hub

    def definitions(self) -> list[UnifiedToolDefinition]:
        return self.gateway.definitions()

    async def invoke(self, invocation: UnifiedToolInvocation) -> UnifiedToolResult:
        definition = next(
            (item for item in self.gateway.definitions() if item.tool_id == invocation.tool_id),
            None,
        )
        origin = ToolOrigin.MCP if definition is None else definition.origin
        server_id = None if definition is None else definition.server_id
        self.repositories.tool_calls.create_invocation(
            invocation,
            origin=origin,
            server_id=server_id,
        )
        self.repositories.tool_calls.mark_running(invocation.invocation_id)
        await self._publish("tool.started", invocation.run_id, invocation.model_dump(mode="json"))
        result = await self.gateway.invoke(invocation)
        self.repositories.tool_calls.complete(result)
        event_type = (
            "tool.completed" if result.status == ToolExecutionStatus.COMPLETED else "tool.failed"
        )
        await self._publish(
            event_type,
            invocation.run_id,
            {
                "invocation": invocation.model_dump(mode="json"),
                "result": result.model_dump(mode="json"),
            },
        )
        return result

    async def _publish(self, event_type: str, run_id: str, payload: dict[str, Any]) -> None:
        event = self.ledger.append(run_id, event_type, payload, actor="tool_gateway")
        await self.event_hub.publish(event.model_dump(mode="json"))


def register_runtime_tools(
    gateway: UnifiedToolGateway,
    runtime_registry: RuntimeToolRegistry,
    *,
    workspace: Path,
) -> None:
    broker = RuntimeToolBroker(runtime_registry, Guardrail())
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
            },
        )

        async def invoke_native(
            invocation: UnifiedToolInvocation,
            *,
            name: str = manifest.name,
        ) -> UnifiedToolResult:
            result = await broker.invoke(
                name,
                invocation.arguments,
                RuntimeToolContext(
                    run_id=invocation.run_id,
                    step_id=invocation.subtask_id or invocation.task_id or invocation.invocation_id,
                    workspace=str(workspace),
                    allowed_paths=[str(workspace)],
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
        metadata: dict[str, Any] | None = None,
        role: AgentRole = AgentRole.ASSISTANT,
    ) -> tuple[str, AgentResult]:
        run_id = str(uuid4())
        task = AgentTask(
            run_id=run_id,
            flow_id=flow_id,
            objective=objective,
            metadata=metadata or {},
        )
        self.repositories.tasks.create_task(
            flow_id=flow_id,
            task_id=task.task_id,
            title=objective[:200],
            objective=objective,
            status="running",
        )
        result = await self.dispatcher.dispatch_root(role, task)
        self.repositories.tasks.update_task(
            task.task_id,
            status=result.status.value,
            result=result.model_dump(mode="json"),
        )
        return run_id, result

    async def publish_agent_event(
        self,
        event_type: str,
        payload: dict[str, Any],
        actor: str,
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
        elif event_type == "agent.cancelled":
            instance = AgentInstance.model_validate(payload)
            self.repositories.agents.update_instance_status(
                instance.instance_id,
                AgentStatus.CANCELLED,
                completed_at=instance.completed_at,
                prompt_version_id=instance.prompt_version_id,
                metadata=instance.metadata,
            )

        run_id = _run_id(payload)
        event = self.ledger.append(run_id, event_type, payload, actor=actor)
        await self.event_hub.publish(event.model_dump(mode="json"))
