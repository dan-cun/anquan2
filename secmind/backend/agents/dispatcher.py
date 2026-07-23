from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

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
    RuntimeEventType,
)
from app.schemas.tools import (
    ToolExecutionStatus,
    UnifiedToolDefinition,
    UnifiedToolInvocation,
    UnifiedToolResult,
)

from .chains import InMemoryMessageChainStore, MessageChainStore
from .native import AgentRunContext, ToolGateway
from .registry import NativeAgentRegistry
from .tool_catalog import visible_tool_definitions

EventPublisher = Callable[
    [str, dict[str, Any], str, EventContext | None],
    Awaitable[None] | None,
]
ContextProvider = Callable[[str, str | None], dict[str, Any]]
logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AgentRunControl:
    max_agents: int
    soft_deadline_at: datetime
    tool_grace_deadline_at: datetime
    hard_deadline_at: datetime


async def _noop_publisher(
    event_type: str,
    payload: dict[str, Any],
    actor: str,
    context: EventContext | None = None,
) -> None:
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
        context_provider: ContextProvider | None = None,
    ) -> None:
        if max_parallel < 1:
            raise ValueError("max_parallel must be positive")
        if max_delegation_depth < 1:
            raise ValueError("max_delegation_depth must be positive")
        self.registry = registry
        self.publisher = publisher or _noop_publisher
        publisher_parameters = inspect.signature(self.publisher).parameters.values()
        self._publisher_accepts_context = (
            any(
                item.kind in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}
                for item in publisher_parameters
            )
            or len(inspect.signature(self.publisher).parameters) >= 4
        )
        self.tool_gateway = tool_gateway
        self.chain_store = chain_store or InMemoryMessageChainStore()
        self.max_parallel = max_parallel
        self.max_delegation_depth = max_delegation_depth
        self.context_provider = context_provider
        self._instances: dict[str, AgentInstance] = {}
        self._delegations: dict[str, AgentDelegation] = {}
        self._messages: list[AgentMessage] = []
        self._message_sequences: dict[str, int] = {}
        self._results: dict[str, AgentResult] = {}
        self._inboxes: dict[str, asyncio.Queue[AgentMessage | None]] = {}
        self._completion_events: dict[str, asyncio.Event] = {}
        self._stop_requests: dict[str, str] = {}
        self._background_tasks: set[asyncio.Task[AgentResult]] = set()
        self._background_task_runs: dict[asyncio.Task[AgentResult], str] = {}
        self._run_controls: dict[str, AgentRunControl] = {}
        self._lock = asyncio.Lock()

    def configure_run(
        self,
        run_id: str,
        *,
        max_agents: int,
        soft_deadline_at: datetime,
        tool_grace_deadline_at: datetime,
        hard_deadline_at: datetime,
    ) -> None:
        if max_agents < 1:
            raise ValueError("max_agents must be positive")
        if soft_deadline_at >= hard_deadline_at:
            raise ValueError("soft_deadline_at must be before hard_deadline_at")
        if not soft_deadline_at <= tool_grace_deadline_at <= hard_deadline_at:
            raise ValueError("tool_grace_deadline_at must be between soft and hard deadlines")
        self._run_controls[run_id] = AgentRunControl(
            max_agents=max_agents,
            soft_deadline_at=soft_deadline_at,
            tool_grace_deadline_at=tool_grace_deadline_at,
            hard_deadline_at=hard_deadline_at,
        )

    def clear_run_control(self, run_id: str) -> None:
        self._run_controls.pop(run_id, None)

    async def cancel_run(self, run_id: str, *, reason: str) -> None:
        terminal = {AgentStatus.COMPLETED, AgentStatus.FAILED, AgentStatus.CANCELLED}
        roots = [
            item
            for item in self._instances.values()
            if item.run_id == run_id
            and item.parent_instance_id is None
            and item.status not in terminal
        ]
        for root in roots:
            await self.stop_agent(root.instance_id, reason=reason)
        tasks = [
            task
            for task, task_run_id in self._background_task_runs.items()
            if task_run_id == run_id and not task.done()
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def dispatch_root(self, role: AgentRole, task: AgentTask) -> AgentResult:
        return await self._dispatch(role, task, parent_instance_id=None, depth=0)

    async def start_root(self, role: AgentRole, task: AgentTask) -> AgentInstance:
        """Start a root Agent in the background and return after `agent.created`."""
        ready: asyncio.Future[AgentInstance] = asyncio.get_running_loop().create_future()
        background = self._background_dispatch(
            role,
            task,
            parent_instance_id=None,
            depth=0,
            ready=ready,
        )
        self._track_background(background, task.run_id)
        return await ready

    async def delegate_from(
        self,
        parent_instance_id: str,
        role: AgentRole,
        task: AgentTask,
    ) -> AgentResult:
        parent = self._instances.get(parent_instance_id)
        if parent is None:
            raise KeyError(parent_instance_id)
        self._validate_child_task(parent, task)
        depth = int(parent.metadata.get("delegation_depth", 0)) + 1
        return await self._delegate(parent, role, task, depth=depth)

    async def start_delegation(
        self,
        parent_instance_id: str,
        role: AgentRole,
        task: AgentTask,
    ) -> AgentDelegation:
        """Create a first-class delegation and run its child asynchronously."""
        parent = self._instances.get(parent_instance_id)
        if parent is None:
            raise KeyError(parent_instance_id)
        self._validate_child_task(parent, task)
        depth = int(parent.metadata.get("delegation_depth", 0)) + 1
        ready: asyncio.Future[AgentDelegation] = asyncio.get_running_loop().create_future()
        background = self._background_delegate(parent, role, task, depth=depth, ready=ready)
        self._track_background(background, task.run_id)
        return await ready

    async def send_message(
        self,
        *,
        from_agent_instance_id: str,
        to_agent_instance_id: str,
        summary: str,
        kind: AgentMessageKind = AgentMessageKind.STATUS,
        payload_ref: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AgentMessage:
        source = self._instances.get(from_agent_instance_id)
        target = self._instances.get(to_agent_instance_id)
        if source is None:
            raise KeyError(from_agent_instance_id)
        if target is None:
            raise KeyError(to_agent_instance_id)
        if source.instance_id == target.instance_id:
            raise ValueError("Agent cannot send a graph message to itself")
        if source.run_id != target.run_id or source.flow_id != target.flow_id:
            raise ValueError("Agent messages cannot cross run or flow boundaries")
        if target.status in {
            AgentStatus.COMPLETED,
            AgentStatus.FAILED,
            AgentStatus.CANCELLED,
        }:
            raise ValueError("Cannot send a message to a terminal Agent")
        message = AgentMessage(
            run_id=source.run_id,
            flow_id=source.flow_id,
            from_agent_instance_id=source.instance_id,
            to_agent_instance_id=target.instance_id,
            kind=kind,
            summary=summary,
            payload_ref=payload_ref,
            metadata=metadata or {},
        )
        await self._message(message, source.role)
        chain = await self.chain_store.for_instance(target.instance_id)
        chain.append(
            "user",
            summary,
            graph_message_id=message.message_id,
            from_agent_instance_id=source.instance_id,
            message_kind=kind.value,
            payload_ref=payload_ref,
        )
        await self._inboxes[target.instance_id].put(message)
        return message

    async def wait_for_message(
        self,
        agent_instance_id: str,
        *,
        reason: str,
        timeout_seconds: float | None = None,
    ) -> AgentMessage | None:
        if timeout_seconds is not None and timeout_seconds < 0:
            raise ValueError("timeout_seconds must not be negative")
        instance = self._active_instance(agent_instance_id)
        inbox = self._inboxes[agent_instance_id]
        parked = inbox.empty()
        if parked:
            instance.status = AgentStatus.WAITING
            instance.updated_at = datetime.now(UTC)
            await self._publish(
                RuntimeEventType.AGENT_WAITING,
                {"instance": instance.model_dump(mode="json"), "reason": reason},
                instance.role,
                context=self._event_context(instance, correlation_id=str(uuid4())),
            )
        try:
            if timeout_seconds is None:
                message = await inbox.get()
            else:
                message = await asyncio.wait_for(inbox.get(), timeout_seconds)
        except TimeoutError:
            message = None
            outcome = "timeout"
        else:
            outcome = "stopped" if message is None else "message_arrived"
        if parked and agent_instance_id not in self._stop_requests:
            instance.status = AgentStatus.RUNNING
            instance.updated_at = datetime.now(UTC)
            await self._publish(
                RuntimeEventType.AGENT_RESUMED,
                {
                    "instance": instance.model_dump(mode="json"),
                    "reason": reason,
                    "outcome": outcome,
                },
                instance.role,
                context=self._event_context(instance, correlation_id=str(uuid4())),
            )
        return message

    async def wait_for_agent(
        self,
        agent_instance_id: str,
        *,
        timeout_seconds: float | None = None,
    ) -> AgentResult | None:
        if agent_instance_id in self._results:
            return self._results[agent_instance_id]
        completion = self._completion_events.get(agent_instance_id)
        if completion is None:
            raise KeyError(agent_instance_id)
        try:
            if timeout_seconds is None:
                await completion.wait()
            else:
                await asyncio.wait_for(completion.wait(), timeout_seconds)
        except TimeoutError:
            return None
        return self._results.get(agent_instance_id)

    async def stop_agent(self, agent_instance_id: str, *, reason: str) -> AgentInstance:
        instance = self._instances.get(agent_instance_id)
        if instance is None:
            raise KeyError(agent_instance_id)
        if instance.status in {
            AgentStatus.COMPLETED,
            AgentStatus.FAILED,
            AgentStatus.CANCELLED,
        }:
            return instance
        terminal = {AgentStatus.COMPLETED, AgentStatus.FAILED, AgentStatus.CANCELLED}
        targets = [item for item in self._subtree(agent_instance_id) if item.status not in terminal]
        correlation_id = str(uuid4())
        for target in targets:
            self._stop_requests[target.instance_id] = reason
            await self._inboxes[target.instance_id].put(None)
            await self._publish_controlled(
                target,
                RuntimeEventType.AGENT_STOP_REQUESTED,
                {"instance": target.model_dump(mode="json"), "reason": reason},
                kind=DecisionKind.STOP,
                decision="stop_agent",
                rationale_summary=reason,
                correlation_id=correlation_id,
            )
        return instance

    async def dispatch_many(
        self,
        assignments: Iterable[tuple[AgentRole, AgentTask]],
    ) -> list[AgentResult]:
        semaphore = asyncio.Semaphore(self.max_parallel)

        async def run(role: AgentRole, task: AgentTask) -> AgentResult:
            async with semaphore:
                return await self.dispatch_root(role, task)

        return await asyncio.gather(*(run(role, task) for role, task in assignments))

    def _background_dispatch(
        self,
        role: AgentRole,
        task: AgentTask,
        *,
        parent_instance_id: str | None,
        depth: int,
        ready: asyncio.Future[AgentInstance],
    ) -> asyncio.Task[AgentResult]:
        async def run() -> AgentResult:
            try:
                return await self._dispatch(
                    role,
                    task,
                    parent_instance_id=parent_instance_id,
                    depth=depth,
                    ready=ready,
                )
            except Exception as error:
                if not ready.done():
                    ready.set_exception(error)
                raise

        return asyncio.create_task(run(), name=f"secmind-agent-{role.value}-{task.task_id}")

    def _background_delegate(
        self,
        parent: AgentInstance,
        role: AgentRole,
        task: AgentTask,
        *,
        depth: int,
        ready: asyncio.Future[AgentDelegation],
    ) -> asyncio.Task[AgentResult]:
        async def run() -> AgentResult:
            try:
                return await self._delegate(parent, role, task, depth=depth, ready=ready)
            except Exception as error:
                if not ready.done():
                    ready.set_exception(error)
                raise

        return asyncio.create_task(
            run(),
            name=f"secmind-delegation-{parent.instance_id}-{task.task_id}",
        )

    def _track_background(self, task: asyncio.Task[AgentResult], run_id: str) -> None:
        self._background_tasks.add(task)
        self._background_task_runs[task] = run_id

        def completed(value: asyncio.Task[AgentResult]) -> None:
            self._background_tasks.discard(value)
            self._background_task_runs.pop(value, None)
            try:
                value.result()
            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("Background Agent task failed")

        task.add_done_callback(completed)

    async def _dispatch(
        self,
        role: AgentRole,
        task: AgentTask,
        *,
        parent_instance_id: str | None,
        depth: int,
        ready: asyncio.Future[AgentInstance] | None = None,
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
            control = self._run_controls.get(task.run_id)
            agent_count = sum(
                1 for item in self._instances.values() if item.run_id == task.run_id
            )
            agent_limit_reached = control is not None and agent_count >= control.max_agents
            if not agent_limit_reached:
                self._instances[instance.instance_id] = instance
                self._inboxes[instance.instance_id] = asyncio.Queue()
                self._completion_events[instance.instance_id] = asyncio.Event()
        if agent_limit_reached:
            message = f"Run Agent limit reached ({control.max_agents})"
            if ready is not None and not ready.done():
                ready.set_exception(RuntimeError(message))
            return await self._run_control_failure(
                task,
                role,
                error_code="AGENT_COUNT_LIMIT",
                message=message,
            )
        await self._publish(
            RuntimeEventType.AGENT_CREATED,
            instance.model_dump(mode="json"),
            role,
            context=self._event_context(instance, correlation_id=instance.instance_id),
        )
        chain = await self.chain_store.create(
            run_id=task.run_id,
            flow_id=task.flow_id,
            agent_instance_id=instance.instance_id,
            agent_role=role,
        )
        instance.metadata["chain_id"] = chain.chain_id
        if ready is not None and not ready.done():
            ready.set_result(instance)

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
                context=self._event_context(instance, correlation_id=instance.instance_id),
            )
            self._completion_events[instance.instance_id].set()
            return result

        instance.status = AgentStatus.RUNNING
        instance.started_at = datetime.now(UTC)
        instance.updated_at = instance.started_at
        await self._publish(
            RuntimeEventType.AGENT_STARTED,
            instance.model_dump(mode="json"),
            role,
            context=self._event_context(instance, correlation_id=instance.instance_id),
        )

        async def delegate(child_role: AgentRole, child_task: AgentTask) -> AgentResult:
            return await self._delegate(instance, child_role, child_task, depth=depth + 1)

        descriptor = self.registry.descriptor(role)

        def role_tool_catalog() -> list[UnifiedToolDefinition]:
            if self.tool_gateway is None:
                return []
            run_definitions = getattr(self.tool_gateway, "definitions_for_run", None)
            definitions = getattr(self.tool_gateway, "definitions", None)
            if callable(run_definitions):
                visible = visible_tool_definitions(descriptor, run_definitions(task.run_id))
            elif callable(definitions):
                visible = visible_tool_definitions(descriptor, definitions())
            else:
                return []
            configured = task.metadata.get("allowed_tool_ids")
            if not isinstance(configured, list):
                return visible
            allowed = {str(item) for item in configured}
            return [item for item in visible if item.tool_id in allowed]

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
            control = self._run_controls.get(task.run_id)
            if control is not None and datetime.now(UTC) >= control.tool_grace_deadline_at:
                return UnifiedToolResult(
                    invocation_id=invocation.invocation_id,
                    tool_id=tool_id,
                    status=ToolExecutionStatus.FAILED,
                    error_code="AGENT_TOOL_GRACE_DEADLINE",
                    error_message=(
                        "The tool-call grace deadline was reached; complete using existing "
                        "observations and evidence"
                    ),
                )
            if self.tool_gateway is None:
                return UnifiedToolResult(
                    invocation_id=invocation.invocation_id,
                    tool_id=tool_id,
                    status=ToolExecutionStatus.FAILED,
                    error_code="TOOL_GATEWAY_UNAVAILABLE",
                    error_message="No unified tool gateway is configured",
                )
            allowed = {item.tool_id for item in role_tool_catalog()}
            if tool_id not in allowed:
                definitions = getattr(self.tool_gateway, "definitions", None)
                known = callable(definitions) and any(
                    item.tool_id == tool_id for item in definitions()
                )
                return UnifiedToolResult(
                    invocation_id=invocation.invocation_id,
                    tool_id=tool_id,
                    status=ToolExecutionStatus.FAILED,
                    error_code=("TOOL_NOT_ALLOWED_FOR_ROLE" if known else "UNKNOWN_TOOL"),
                    error_message=(
                        f"Tool {tool_id} is not authorized for Agent role {role.value}"
                        if known
                        else f"Unknown unified tool: {tool_id}"
                    ),
                )
            return await self.tool_gateway.invoke(invocation)

        async def send_message(
            target_agent_instance_id: str,
            summary: str,
            kind: AgentMessageKind,
            metadata: dict[str, Any],
        ) -> AgentMessage:
            return await self.send_message(
                from_agent_instance_id=instance.instance_id,
                to_agent_instance_id=target_agent_instance_id,
                summary=summary,
                kind=kind,
                metadata=metadata,
            )

        async def wait_for_message(
            reason: str,
            timeout_seconds: float | None,
        ) -> AgentMessage | None:
            return await self.wait_for_message(
                instance.instance_id,
                reason=reason,
                timeout_seconds=timeout_seconds,
            )

        async def publish_runtime_event(
            event_type: str,
            payload: dict[str, Any],
        ) -> None:
            runtime_type = RuntimeEventType(event_type)
            correlation_id = str(payload.get("detection_id") or uuid4())
            await self._publish(
                runtime_type,
                {
                    "run_id": task.run_id,
                    "flow_id": task.flow_id,
                    "agent_instance_id": instance.instance_id,
                    "task_id": task.task_id,
                    **payload,
                },
                role,
                context=self._event_context(
                    instance,
                    correlation_id=correlation_id,
                ),
            )

        context = AgentRunContext(
            instance=instance,
            task=task,
            chain=chain,
            delegate_callback=delegate,
            tool_callback=invoke_tool,
            message_callback=send_message,
            wait_message_callback=wait_for_message,
            stop_requested_callback=lambda: instance.instance_id in self._stop_requests,
            runtime_event_callback=publish_runtime_event,
            tool_catalog_callback=role_tool_catalog,
            long_term_context=(
                self.context_provider(task.run_id, instance.instance_id)
                if self.context_provider is not None
                else {}
            ),
        )
        try:
            result = await self.registry.subgraph(role).invoke(context)
        except asyncio.CancelledError:
            instance.status = AgentStatus.CANCELLED
            instance.completed_at = datetime.now(UTC)
            instance.updated_at = instance.completed_at
            result = AgentResult(
                agent_instance_id=instance.instance_id,
                task_id=task.task_id,
                status=AgentStatus.CANCELLED,
                summary="Agent execution task was cancelled",
                error_code="AGENT_TASK_CANCELLED",
                error_message="Agent execution task was cancelled",
                started_at=instance.started_at,
                completed_at=instance.completed_at,
            )
            self._results[instance.instance_id] = result
            await self._publish(
                RuntimeEventType.AGENT_CANCELLED,
                instance.model_dump(mode="json"),
                role,
                context=self._event_context(instance, correlation_id=instance.instance_id),
            )
            self._completion_events[instance.instance_id].set()
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
            result.status
            if result.status in {AgentStatus.COMPLETED, AgentStatus.FAILED, AgentStatus.CANCELLED}
            else AgentStatus.FAILED
        )
        instance.status = terminal_status
        instance.completed_at = result.completed_at
        instance.updated_at = result.completed_at
        async with self._lock:
            self._results[instance.instance_id] = result
        event_type = {
            AgentStatus.COMPLETED: RuntimeEventType.AGENT_COMPLETED,
            AgentStatus.FAILED: RuntimeEventType.AGENT_FAILED,
            AgentStatus.CANCELLED: RuntimeEventType.AGENT_CANCELLED,
        }[terminal_status]
        payload = {
            "instance": instance.model_dump(mode="json"),
            "result": result.model_dump(mode="json"),
        }
        if terminal_status == AgentStatus.COMPLETED:
            await self._publish_controlled(
                instance,
                event_type,
                payload,
                kind=DecisionKind.COMPLETE,
                decision="complete_agent",
                rationale_summary=result.summary or "Agent completed its assigned objective.",
                correlation_id=f"completion:{instance.instance_id}",
            )
        else:
            await self._publish(
                event_type,
                payload,
                role,
                context=self._event_context(
                    instance,
                    correlation_id=f"completion:{instance.instance_id}",
                ),
            )
        self._stop_requests.pop(instance.instance_id, None)
        self._completion_events[instance.instance_id].set()
        return result

    async def _delegate(
        self,
        parent: AgentInstance,
        role: AgentRole,
        task: AgentTask,
        *,
        depth: int,
        ready: asyncio.Future[AgentDelegation] | None = None,
    ) -> AgentResult:
        control = self._run_controls.get(task.run_id)
        if control is not None and datetime.now(UTC) >= control.soft_deadline_at:
            return await self._run_control_failure(
                task,
                role,
                error_code="AGENT_SOFT_DEADLINE",
                message=(
                    "The collaboration soft deadline was reached; do not delegate again and "
                    "complete using the observations and evidence already available"
                ),
                parent=parent,
            )
        delegation = AgentDelegation(
            run_id=task.run_id,
            flow_id=task.flow_id,
            from_agent_instance_id=parent.instance_id,
            to_role=role,
            task=task,
        )
        async with self._lock:
            self._delegations[delegation.delegation_id] = delegation
        await self._publish_controlled(
            parent,
            RuntimeEventType.AGENT_DELEGATED,
            delegation.model_dump(mode="json"),
            kind=DecisionKind.DELEGATE,
            decision=f"delegate_to:{role.value}",
            rationale_summary=(f"将独立子任务委派给 {role.value}，目标为：{task.objective}"),
            correlation_id=delegation.delegation_id,
        )
        if ready is not None and not ready.done():
            ready.set_result(delegation)
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

    async def _run_control_failure(
        self,
        task: AgentTask,
        role: AgentRole,
        *,
        error_code: str,
        message: str,
        parent: AgentInstance | None = None,
    ) -> AgentResult:
        await self._publish(
            RuntimeEventType.BUDGET_EXHAUSTED,
            {
                "run_id": task.run_id,
                "flow_id": task.flow_id,
                "task_id": task.task_id,
                "budget": "agent_collaboration",
                "error_code": error_code,
                "message": message,
            },
            parent.role if parent is not None else role,
            context=(
                self._event_context(parent, correlation_id=str(uuid4()))
                if parent is not None
                else EventContext(flow_id=task.flow_id, task_id=task.task_id)
            ),
        )
        return AgentResult(
            agent_instance_id=str(uuid4()),
            task_id=task.task_id,
            status=AgentStatus.FAILED,
            summary=message,
            error_code=error_code,
            error_message=message,
        )

    async def _message(self, message: AgentMessage, actor: AgentRole) -> None:
        async with self._lock:
            next_sequence = self._message_sequences.get(message.run_id, 0) + 1
            self._message_sequences[message.run_id] = next_sequence
            message.sequence = next_sequence
            self._messages.append(message)
        source = self._instances.get(message.from_agent_instance_id)
        await self._publish(
            RuntimeEventType.AGENT_MESSAGE,
            message.model_dump(mode="json"),
            actor,
            context=(
                None
                if source is None
                else self._event_context(source, correlation_id=message.message_id)
            ),
        )

    async def _publish(
        self,
        event_type: RuntimeEventType,
        payload: dict[str, Any],
        actor: AgentRole,
        *,
        context: EventContext | None = None,
    ) -> None:
        if self._publisher_accepts_context:
            result = self.publisher(event_type.value, payload, actor.value, context)
        else:
            result = self.publisher(event_type.value, payload, actor.value)  # type: ignore[call-arg]
        if inspect.isawaitable(result):
            await result

    async def _publish_controlled(
        self,
        instance: AgentInstance,
        event_type: RuntimeEventType,
        payload: dict[str, Any],
        *,
        kind: DecisionKind,
        decision: str,
        rationale_summary: str,
        correlation_id: str,
    ) -> None:
        record = DecisionRecord(
            kind=kind,
            goal=decision,
            decision=decision,
            rationale_summary=rationale_summary or "执行已请求的 Agent Graph 控制操作。",
            expected_outcome=f"产生 {event_type.value} 状态变更。",
            model_id="agent-dispatcher",
            prompt_version="agent-graph-v1",
        )
        context = self._event_context(
            instance,
            correlation_id=correlation_id,
            decision_id=record.decision_id,
        )
        await self._publish(
            RuntimeEventType.DECISION_RECORDED,
            {
                "run_id": instance.run_id,
                "flow_id": instance.flow_id,
                "decision": record.model_dump(mode="json"),
            },
            instance.role,
            context=context,
        )
        await self._publish(
            event_type,
            payload,
            instance.role,
            context=context,
        )

    @staticmethod
    def _event_context(
        instance: AgentInstance,
        *,
        correlation_id: str,
        decision_id: str | None = None,
    ) -> EventContext:
        return EventContext(
            flow_id=instance.flow_id,
            correlation_id=correlation_id,
            decision_id=decision_id,
            agent_instance_id=instance.instance_id,
            task_id=instance.task_id,
        )

    def _active_instance(self, agent_instance_id: str) -> AgentInstance:
        instance = self._instances.get(agent_instance_id)
        if instance is None:
            raise KeyError(agent_instance_id)
        if instance.status in {
            AgentStatus.COMPLETED,
            AgentStatus.FAILED,
            AgentStatus.CANCELLED,
        }:
            raise ValueError("Terminal Agent cannot enter a waiting state")
        return instance

    def _subtree(self, agent_instance_id: str) -> list[AgentInstance]:
        result: list[AgentInstance] = []
        pending = [agent_instance_id]
        while pending:
            current = pending.pop(0)
            instance = self._instances.get(current)
            if instance is None:
                continue
            result.append(instance)
            pending.extend(
                item.instance_id
                for item in self._instances.values()
                if item.parent_instance_id == current
            )
        return result

    @staticmethod
    def _validate_child_task(parent: AgentInstance, task: AgentTask) -> None:
        if parent.run_id != task.run_id or parent.flow_id != task.flow_id:
            raise ValueError("Delegated Agent task must remain in the parent run and flow")
        if task.parent_agent_instance_id not in {None, parent.instance_id}:
            raise ValueError("Delegated Agent task has a conflicting parent instance")

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
