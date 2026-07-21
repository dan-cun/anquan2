from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.schemas.agents import (
    AgentDescriptor,
    AgentInstance,
    AgentMessage,
    AgentMessageKind,
    AgentResult,
    AgentRole,
    AgentStatus,
    AgentTask,
)
from app.schemas.tools import UnifiedToolDefinition, UnifiedToolInvocation, UnifiedToolResult
from llm.base import LLMMessage, LLMProvider

from .actions import ACTION_PROTOCOL, AgentActionError, AgentActionType, parse_agent_action
from .chains import AgentMessageChain
from .loop_guard import AgentLoopGuard, LoopGuardConfig
from .tool_catalog import render_tool_catalog


class PromptResolver(Protocol):
    async def render(
        self,
        prompt_key: str,
        variables: dict[str, Any],
    ) -> tuple[str, str | None]: ...


class ToolGateway(Protocol):
    def definitions(self) -> list[UnifiedToolDefinition]: ...

    async def invoke(self, invocation: UnifiedToolInvocation) -> UnifiedToolResult: ...


DelegateCallback = Callable[[AgentRole, AgentTask], Awaitable[AgentResult]]
ToolCallback = Callable[[str, dict[str, Any]], Awaitable[UnifiedToolResult]]
ToolCatalogCallback = Callable[[], list[UnifiedToolDefinition]]
MessageCallback = Callable[
    [str, str, AgentMessageKind, dict[str, Any]], Awaitable[AgentMessage]
]
WaitMessageCallback = Callable[[str, float | None], Awaitable[AgentMessage | None]]
StopRequestedCallback = Callable[[], bool]
RuntimeEventCallback = Callable[[str, dict[str, Any]], Awaitable[None]]


class StaticPromptResolver:
    def __init__(self, prompts: dict[str, str] | None = None) -> None:
        self._prompts = prompts or {}

    async def render(
        self,
        prompt_key: str,
        variables: dict[str, Any],
    ) -> tuple[str, str | None]:
        prompt = self._prompts.get(
            prompt_key,
            f"You are the native SecMind {prompt_key} Agent. Complete the assigned objective.",
        )
        return prompt, None


def _merge_unique(target: list[str], values: list[str]) -> None:
    known = set(target)
    for value in values:
        if value not in known:
            target.append(value)
            known.add(value)


@dataclass(slots=True)
class AgentRunContext:
    instance: AgentInstance
    task: AgentTask
    chain: AgentMessageChain
    delegate_callback: DelegateCallback
    tool_callback: ToolCallback
    message_callback: MessageCallback
    wait_message_callback: WaitMessageCallback
    stop_requested_callback: StopRequestedCallback
    runtime_event_callback: RuntimeEventCallback
    tool_catalog_callback: ToolCatalogCallback = field(default_factory=lambda: lambda: [])
    child_results: list[AgentResult] = field(default_factory=list)
    tool_results: list[UnifiedToolResult] = field(default_factory=list)
    artifact_refs: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    finding_ids: list[str] = field(default_factory=list)
    long_term_context: dict[str, Any] = field(default_factory=dict)

    async def delegate(
        self,
        role: AgentRole,
        *,
        objective: str,
        context_refs: list[str] | None = None,
        constraints: list[str] | None = None,
        expected_outputs: list[str] | None = None,
    ) -> AgentResult:
        child_context_refs = list(self.task.context_refs)
        _merge_unique(child_context_refs, context_refs or [])
        child_task = AgentTask(
            run_id=self.task.run_id,
            flow_id=self.task.flow_id,
            subtask_id=self.task.subtask_id,
            parent_agent_instance_id=self.instance.instance_id,
            objective=objective,
            context_refs=child_context_refs,
            constraints=constraints or self.task.constraints,
            expected_outputs=expected_outputs or self.task.expected_outputs,
            metadata=self.task.metadata.copy(),
        )
        result = await self.delegate_callback(role, child_task)
        self.child_results.append(result)
        _merge_unique(self.artifact_refs, result.artifact_refs)
        _merge_unique(self.evidence_ids, result.evidence_ids)
        _merge_unique(self.finding_ids, result.finding_ids)
        return result

    async def invoke_tool(
        self,
        tool_id: str,
        arguments: dict[str, Any],
    ) -> UnifiedToolResult:
        result = await self.tool_callback(tool_id, arguments)
        self.tool_results.append(result)
        _merge_unique(self.artifact_refs, result.artifact_refs)
        _merge_unique(self.evidence_ids, result.evidence_ids)
        return result

    async def send_message(
        self,
        target_agent_instance_id: str,
        summary: str,
        *,
        kind: AgentMessageKind = AgentMessageKind.STATUS,
        metadata: dict[str, Any] | None = None,
    ) -> AgentMessage:
        return await self.message_callback(
            target_agent_instance_id,
            summary,
            kind,
            metadata or {},
        )

    async def wait_for_message(
        self,
        *,
        reason: str,
        timeout_seconds: float | None = None,
    ) -> AgentMessage | None:
        return await self.wait_message_callback(reason, timeout_seconds)

    def stop_requested(self) -> bool:
        return self.stop_requested_callback()

    async def publish_runtime_event(
        self,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        await self.runtime_event_callback(event_type, payload)

    def tool_catalog(self) -> list[UnifiedToolDefinition]:
        return [item.model_copy(deep=True) for item in self.tool_catalog_callback()]


class NativeAgent(ABC):
    descriptor: AgentDescriptor

    def __init__(self, descriptor: AgentDescriptor) -> None:
        self.descriptor = descriptor

    @abstractmethod
    async def run(self, context: AgentRunContext) -> AgentResult:
        raise NotImplementedError


class ModelNativeAgent(NativeAgent):
    """PentAGI-style Agent loop: model -> delegate/tool -> observation -> model."""

    def __init__(
        self,
        descriptor: AgentDescriptor,
        *,
        model: LLMProvider,
        prompts: PromptResolver,
        max_iterations: int = 24,
        max_reflections: int = 3,
        loop_guard_config: LoopGuardConfig | None = None,
    ) -> None:
        super().__init__(descriptor)
        if max_iterations < 1:
            raise ValueError("max_iterations must be positive")
        if max_reflections < 0:
            raise ValueError("max_reflections must not be negative")
        self.model = model
        self.prompts = prompts
        self.max_iterations = max_iterations
        self.max_reflections = max_reflections
        self.loop_guard_config = loop_guard_config or LoopGuardConfig()

    async def run(self, context: AgentRunContext) -> AgentResult:
        prompt, prompt_version_id = await self.prompts.render(
            self.descriptor.prompt_key,
            {
                "AgentRole": self.descriptor.role.value,
                "Objective": context.task.objective,
                "Constraints": context.task.constraints,
                "ExpectedOutputs": context.task.expected_outputs,
                "ContextRefs": context.task.context_refs,
                "Capabilities": self.descriptor.capabilities,
                "LongTermContext": context.long_term_context,
            },
        )
        context.instance.prompt_version_id = prompt_version_id
        context.chain.append(
            "system",
            f"{prompt}\n\n{ACTION_PROTOCOL}",
            prompt_key=self.descriptor.prompt_key,
        )
        if context.long_term_context:
            context.chain.append(
                "system",
                "以下是可审计的长期任务状态。只按需加载 Skill；事实必须保留 Evidence 引用。\n"
                + json.dumps(context.long_term_context, ensure_ascii=False, default=str),
                context_kind="long_term_state",
            )
        context.chain.append(
            "user",
            context.task.objective,
            task_id=context.task.task_id,
            context_refs=context.task.context_refs,
            constraints=context.task.constraints,
            expected_outputs=context.task.expected_outputs,
        )

        reflection_count = 0
        loop_guard = AgentLoopGuard(self.loop_guard_config)
        for iteration in range(1, self.max_iterations + 1):
            if context.stop_requested():
                return self._cancelled(context)
            catalog_text, catalog_digest = render_tool_catalog(
                self.descriptor,
                context.tool_catalog(),
            )
            request_messages = list(context.chain.messages)
            request_messages.insert(
                1,
                LLMMessage(
                    role="system",
                    content=catalog_text,
                    metadata={
                        "context_kind": "runtime_tool_catalog",
                        "agent_role": self.descriptor.role.value,
                        "catalog_sha256": catalog_digest,
                    },
                ),
            )
            response = await self.model.complete(
                request_messages,
                stage=f"agent.{self.descriptor.role.value}",
                model_profile=self.descriptor.model_profile,
                run_id=context.task.run_id,
                flow_id=context.task.flow_id,
                agent_instance_id=context.instance.instance_id,
                task_id=context.task.task_id,
                iteration=iteration,
            )
            context.chain.append(
                "assistant",
                response.content,
                provider=response.provider,
                model=response.model,
                iteration=iteration,
            )
            if context.stop_requested():
                return self._cancelled(context)
            try:
                action = parse_agent_action(response.content)
            except AgentActionError:
                if self.descriptor.role == AgentRole.REFLECTOR:
                    return self._complete(context, response.content.strip())
                if reflection_count >= self.max_reflections:
                    return self._failed(
                        context,
                        code="AGENT_ACTION_INVALID",
                        message="Agent repeatedly returned an invalid action envelope",
                    )
                reflection_count += 1
                reflection = await context.delegate(
                    AgentRole.REFLECTOR,
                    objective=(
                        "Correct this Agent response so the original Agent can return one valid "
                        f"action envelope. Response:\n{response.content}"
                    ),
                    expected_outputs=["public corrective instruction"],
                )
                context.chain.append(
                    "tool",
                    reflection.model_dump_json(),
                    delegated_role=AgentRole.REFLECTOR.value,
                    result_status=reflection.status.value,
                )
                continue

            action_fp, loop_detection, strategy_change = loop_guard.inspect_action(action)
            if strategy_change is not None:
                await context.publish_runtime_event(
                    "strategy.changed",
                    strategy_change.event_payload(),
                )
            if loop_detection is not None:
                await context.publish_runtime_event(
                    "loop.detected",
                    loop_detection.event_payload(),
                )
                context.chain.append(
                    "tool",
                    loop_detection.model_instruction(),
                    loop_guard=True,
                    detection_id=loop_detection.detection_id,
                )
                if loop_detection.terminal:
                    return self._failed(
                        context,
                        code="AGENT_LOOP_DETECTED",
                        message="Agent ignored repeated loop-guard strategy-change requests",
                    )
                continue

            if action.action == AgentActionType.COMPLETE:
                return self._complete(
                    context,
                    action.summary,
                    data=action.data,
                    artifact_refs=action.artifact_refs,
                    evidence_ids=action.evidence_ids,
                    finding_ids=action.finding_ids,
                )

            if action.action == AgentActionType.DELEGATE:
                assert action.role is not None and action.objective is not None
                result = await context.delegate(
                    action.role,
                    objective=action.objective,
                    context_refs=action.context_refs,
                    constraints=action.constraints,
                    expected_outputs=action.expected_outputs,
                )
                context.chain.append(
                    "tool",
                    result.model_dump_json(),
                    delegated_role=action.role.value,
                    result_status=result.status.value,
                )
                loop_detection = loop_guard.record_result(
                    action_fp,
                    result,
                    artifact_refs=context.artifact_refs,
                    evidence_ids=context.evidence_ids,
                    finding_ids=context.finding_ids,
                )
                if loop_detection is not None:
                    await context.publish_runtime_event(
                        "loop.detected",
                        loop_detection.event_payload(),
                    )
                    context.chain.append(
                        "tool",
                        loop_detection.model_instruction(),
                        loop_guard=True,
                        detection_id=loop_detection.detection_id,
                    )
                    if loop_detection.terminal:
                        return self._failed(
                            context,
                            code="AGENT_LOOP_DETECTED",
                            message=(
                                "Agent ignored repeated loop-guard strategy-change requests"
                            ),
                        )
                continue

            assert action.tool_id is not None
            tool_result = await context.invoke_tool(action.tool_id, action.arguments)
            context.chain.append(
                "tool",
                tool_result.model_dump_json(),
                tool_id=action.tool_id,
                result_status=tool_result.status.value,
            )
            loop_detection = loop_guard.record_result(
                action_fp,
                tool_result,
                artifact_refs=context.artifact_refs,
                evidence_ids=context.evidence_ids,
                finding_ids=context.finding_ids,
            )
            if loop_detection is not None:
                await context.publish_runtime_event(
                    "loop.detected",
                    loop_detection.event_payload(),
                )
                context.chain.append(
                    "tool",
                    loop_detection.model_instruction(),
                    loop_guard=True,
                    detection_id=loop_detection.detection_id,
                )
                if loop_detection.terminal:
                    return self._failed(
                        context,
                        code="AGENT_LOOP_DETECTED",
                        message="Agent ignored repeated loop-guard strategy-change requests",
                    )

        return self._failed(
            context,
            code="AGENT_ITERATION_LIMIT",
            message=f"Agent exceeded {self.max_iterations} model iterations",
        )

    @staticmethod
    def _complete(
        context: AgentRunContext,
        summary: str,
        *,
        data: dict[str, Any] | None = None,
        artifact_refs: list[str] | None = None,
        evidence_ids: list[str] | None = None,
        finding_ids: list[str] | None = None,
    ) -> AgentResult:
        artifacts = list(context.artifact_refs)
        evidence = list(context.evidence_ids)
        findings = list(context.finding_ids)
        _merge_unique(artifacts, artifact_refs or [])
        _merge_unique(evidence, evidence_ids or [])
        _merge_unique(findings, finding_ids or [])
        return AgentResult(
            agent_instance_id=context.instance.instance_id,
            task_id=context.task.task_id,
            status=AgentStatus.COMPLETED,
            summary=summary,
            data=data or {},
            artifact_refs=artifacts,
            evidence_ids=evidence,
            finding_ids=findings,
            started_at=context.instance.started_at,
        )

    @staticmethod
    def _failed(context: AgentRunContext, *, code: str, message: str) -> AgentResult:
        return AgentResult(
            agent_instance_id=context.instance.instance_id,
            task_id=context.task.task_id,
            status=AgentStatus.FAILED,
            summary=message,
            artifact_refs=list(context.artifact_refs),
            evidence_ids=list(context.evidence_ids),
            finding_ids=list(context.finding_ids),
            error_code=code,
            error_message=message,
            started_at=context.instance.started_at,
        )

    @staticmethod
    def _cancelled(context: AgentRunContext) -> AgentResult:
        return AgentResult(
            agent_instance_id=context.instance.instance_id,
            task_id=context.task.task_id,
            status=AgentStatus.CANCELLED,
            summary="Agent stopped by request",
            artifact_refs=list(context.artifact_refs),
            evidence_ids=list(context.evidence_ids),
            finding_ids=list(context.finding_ids),
            error_code="AGENT_STOP_REQUESTED",
            error_message="Agent stopped by request",
            started_at=context.instance.started_at,
        )
