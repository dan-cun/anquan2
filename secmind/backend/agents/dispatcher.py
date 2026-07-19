from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Iterable
from datetime import UTC, datetime
from typing import Any

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
from app.schemas.runtime import RuntimeEventType
from app.schemas.tools import (
    ToolExecutionStatus,
    UnifiedToolInvocation,
    UnifiedToolResult,
)

from .chains import InMemoryMessageChainStore, MessageChainStore
from .native import AgentRunContext, ToolGateway
from .registry import NativeAgentRegistry

EventPublisher = Callable[[str, dict[str, Any], str], Awaitable[None] | None]


async def _noop_publisher(event_type: str, payload: dict[str, Any], actor: str) -> None:
    return None


class AgentDispatcher:
    """Owns native Agent instances, delegation lifecycle, messages, and result return."""

    def __init__(
        self,
        *,
        registry: NativeAgentRegistry,
        publisher: EventPublisher | None = None,
        tool_gateway: ToolGateway | None = None,
        chain_store: MessageChainStore | None = None,
        max_parallel: int = 4,
        max_delegation_depth: int = 12,
    ) -> None:
        if max_parallel < 1:
            raise ValueError("max_parallel must be positive")
        if max_delegation_depth < 1:
            raise ValueError("max_delegation_depth must be positive")
        self.registry = registry
        self.publisher = publisher or _noop_publisher
        self.tool_gateway = tool_gateway
        self.chain_store = chain_store or InMemoryMessageChainStore()
        self.max_parallel = max_parallel
        self.max_delegation_depth = max_delegation_depth
        self._instances: dict[str, AgentInstance] = {}
        self._delegations: dict[str, AgentDelegation] = {}
        self._messages: list[AgentMessage] = []
        self._message_sequences: dict[str, int] = {}
        self._results: dict[str, AgentResult] = {}
        self._lock = asyncio.Lock()

    async def dispatch_root(self, role: AgentRole, task: AgentTask) -> AgentResult:
        return await self._dispatch(role, task, parent_instance_id=None, depth=0)

    async def delegate_from(
        self,
        parent_instance_id: str,
        role: AgentRole,
        task: AgentTask,
    ) -> AgentResult:
        parent = self._instances.get(parent_instance_id)
        if parent is None:
            raise KeyError(parent_instance_id)
        depth = int(parent.metadata.get("delegation_depth", 0)) + 1
        return await self._delegate(parent, role, task, depth=depth)

    async def dispatch_many(
        self,
        assignments: Iterable[tuple[AgentRole, AgentTask]],
    ) -> list[AgentResult]:
        semaphore = asyncio.Semaphore(self.max_parallel)

        async def run(role: AgentRole, task: AgentTask) -> AgentResult:
            async with semaphore:
                return await self.dispatch_root(role, task)

        return await asyncio.gather(*(run(role, task) for role, task in assignments))

    async def _dispatch(
        self,
        role: AgentRole,
        task: AgentTask,
        *,
        parent_instance_id: str | None,
        depth: int,
    ) -> AgentResult:
        descriptor = self.registry.descriptor(role)
        instance = AgentInstance(
            run_id=task.run_id,
            flow_id=task.flow_id,
            role=role,
            task_id=task.task_id,
            parent_instance_id=parent_instance_id,
            model_profile=descriptor.model_profile,
            metadata={"delegation_depth": depth},
        )
        async with self._lock:
            self._instances[instance.instance_id] = instance
        await self._publish(RuntimeEventType.AGENT_CREATED, instance.model_dump(mode="json"), role)
        chain = await self.chain_store.create(
            run_id=task.run_id,
            flow_id=task.flow_id,
            agent_instance_id=instance.instance_id,
            agent_role=role,
        )
        instance.metadata["chain_id"] = chain.chain_id

        if depth > self.max_delegation_depth:
            instance.status = AgentStatus.FAILED
            instance.completed_at = datetime.now(UTC)
            instance.updated_at = instance.completed_at
            result = AgentResult(
                agent_instance_id=instance.instance_id,
                task_id=task.task_id,
                status=AgentStatus.FAILED,
                summary="Maximum Agent delegation depth exceeded",
                error_code="AGENT_DELEGATION_DEPTH",
                error_message="Maximum Agent delegation depth exceeded",
                completed_at=instance.completed_at,
            )
            async with self._lock:
                self._results[instance.instance_id] = result
            await self._publish(
                RuntimeEventType.AGENT_FAILED,
                {
                    "instance": instance.model_dump(mode="json"),
                    "result": result.model_dump(mode="json"),
                },
                role,
            )
            return result

        instance.status = AgentStatus.RUNNING
        instance.started_at = datetime.now(UTC)
        instance.updated_at = instance.started_at
        await self._publish(RuntimeEventType.AGENT_STARTED, instance.model_dump(mode="json"), role)

        async def delegate(child_role: AgentRole, child_task: AgentTask) -> AgentResult:
            return await self._delegate(instance, child_role, child_task, depth=depth + 1)

        async def invoke_tool(tool_id: str, arguments: dict[str, Any]) -> UnifiedToolResult:
            invocation = UnifiedToolInvocation(
                run_id=task.run_id,
                flow_id=task.flow_id,
                task_id=task.task_id,
                subtask_id=task.subtask_id,
                agent_instance_id=instance.instance_id,
                tool_id=tool_id,
                arguments=arguments,
            )
            if self.tool_gateway is None:
                return UnifiedToolResult(
                    invocation_id=invocation.invocation_id,
                    tool_id=tool_id,
                    status=ToolExecutionStatus.FAILED,
                    error_code="TOOL_GATEWAY_UNAVAILABLE",
                    error_message="No unified tool gateway is configured",
                )
            return await self.tool_gateway.invoke(invocation)

        context = AgentRunContext(
            instance=instance,
            task=task,
            chain=chain,
            delegate_callback=delegate,
            tool_callback=invoke_tool,
        )
        try:
            result = await self.registry.subgraph(role).invoke(context)
        except asyncio.CancelledError:
            instance.status = AgentStatus.CANCELLED
            instance.completed_at = datetime.now(UTC)
            instance.updated_at = instance.completed_at
            await self._publish(
                RuntimeEventType.AGENT_CANCELLED,
                instance.model_dump(mode="json"),
                role,
            )
            raise
        except Exception as error:
            result = AgentResult(
                agent_instance_id=instance.instance_id,
                task_id=task.task_id,
                status=AgentStatus.FAILED,
                summary=f"Agent failed ({type(error).__name__})",
                error_code=type(error).__name__,
                error_message=str(error),
                started_at=instance.started_at,
            )

        terminal_status = (
            AgentStatus.COMPLETED if result.status == AgentStatus.COMPLETED else AgentStatus.FAILED
        )
        instance.status = terminal_status
        instance.completed_at = result.completed_at
        instance.updated_at = result.completed_at
        async with self._lock:
            self._results[instance.instance_id] = result
        event_type = (
            RuntimeEventType.AGENT_COMPLETED
            if terminal_status == AgentStatus.COMPLETED
            else RuntimeEventType.AGENT_FAILED
        )
        await self._publish(
            event_type,
            {
                "instance": instance.model_dump(mode="json"),
                "result": result.model_dump(mode="json"),
            },
            role,
        )
        return result

    async def _delegate(
        self,
        parent: AgentInstance,
        role: AgentRole,
        task: AgentTask,
        *,
        depth: int,
    ) -> AgentResult:
        delegation = AgentDelegation(
            run_id=task.run_id,
            flow_id=task.flow_id,
            from_agent_instance_id=parent.instance_id,
            to_role=role,
            task=task,
        )
        async with self._lock:
            self._delegations[delegation.delegation_id] = delegation
        await self._publish(
            RuntimeEventType.AGENT_DELEGATED,
            delegation.model_dump(mode="json"),
            parent.role,
        )
        await self._message(
            AgentMessage(
                run_id=task.run_id,
                flow_id=task.flow_id,
                from_agent_instance_id=parent.instance_id,
                to_role=role,
                kind=AgentMessageKind.DELEGATION,
                summary=task.objective,
                metadata={"delegation_id": delegation.delegation_id},
            ),
            parent.role,
        )

        result = await self._dispatch(
            role,
            task,
            parent_instance_id=parent.instance_id,
            depth=depth,
        )
        delegation.to_agent_instance_id = result.agent_instance_id
        delegation.status = result.status
        delegation.result_summary = result.summary
        delegation.completed_at = result.completed_at
        await self._message(
            AgentMessage(
                run_id=task.run_id,
                flow_id=task.flow_id,
                from_agent_instance_id=result.agent_instance_id,
                to_agent_instance_id=parent.instance_id,
                kind=AgentMessageKind.RESPONSE,
                summary=result.summary or result.error_message or "Agent returned no summary",
                metadata={
                    "delegation_id": delegation.delegation_id,
                    "status": result.status.value,
                    "evidence_ids": result.evidence_ids,
                    "finding_ids": result.finding_ids,
                },
            ),
            role,
        )
        return result

    async def _message(self, message: AgentMessage, actor: AgentRole) -> None:
        async with self._lock:
            next_sequence = self._message_sequences.get(message.run_id, 0) + 1
            self._message_sequences[message.run_id] = next_sequence
            message.sequence = next_sequence
            self._messages.append(message)
        await self._publish(RuntimeEventType.AGENT_MESSAGE, message.model_dump(mode="json"), actor)

    async def _publish(
        self,
        event_type: RuntimeEventType,
        payload: dict[str, Any],
        actor: AgentRole,
    ) -> None:
        result = self.publisher(event_type.value, payload, actor.value)
        if inspect.isawaitable(result):
            await result

    def instances(self, run_id: str | None = None) -> list[AgentInstance]:
        values = list(self._instances.values())
        return values if run_id is None else [item for item in values if item.run_id == run_id]

    def delegations(self, run_id: str | None = None) -> list[AgentDelegation]:
        values = list(self._delegations.values())
        return values if run_id is None else [item for item in values if item.run_id == run_id]

    def messages(self, run_id: str | None = None) -> list[AgentMessage]:
        return (
            list(self._messages)
            if run_id is None
            else [item for item in self._messages if item.run_id == run_id]
        )

    def result(self, agent_instance_id: str) -> AgentResult | None:
        return self._results.get(agent_instance_id)
