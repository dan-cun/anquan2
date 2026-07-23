from __future__ import annotations

import hashlib
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
from app.schemas.provider import AgentFinalReport, AgentObservation
from app.schemas.tools import UnifiedToolDefinition, UnifiedToolInvocation, UnifiedToolResult
from llm.base import LLMMessage, LLMProvider

from .actions import (
    ACTION_PROTOCOL,
    AgentAction,
    AgentActionError,
    AgentActionType,
    parse_agent_action,
)
from .chains import AgentMessageChain
from .loop_guard import AgentLoopGuard, LoopGuardConfig
from .tool_catalog import render_tool_catalog

MAX_OBSERVATION_REFS = 64
MAX_PROJECTED_FINDINGS = 20
MAX_PROJECTED_DATA_CHARS = 12_000
SEVERITY_RANK = {"CRITICAL": 5, "HIGH": 4, "MEDIUM": 3, "LOW": 2, "UNKNOWN": 1}
CONFIDENCE_RANK = {"HIGH": 3, "MEDIUM": 2, "LOW": 1, "UNKNOWN": 0}


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
MessageCallback = Callable[[str, str, AgentMessageKind, dict[str, Any]], Awaitable[AgentMessage]]
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


def project_tool_data(data: dict[str, Any]) -> dict[str, Any]:
    """Build a bounded model-facing view while persistence retains the full result."""

    if not data:
        return {}
    raw_size = len(_canonical_json(data))
    findings = data.get("findings")
    if isinstance(findings, list):
        unique = _deduplicate_findings(findings)
        selected = sorted(unique, key=_finding_sort_key)[:MAX_PROJECTED_FINDINGS]
        severity_counts: dict[str, int] = {}
        for finding in unique:
            severity = str(finding.get("severity") or "UNKNOWN").upper()
            severity_counts[severity] = severity_counts.get(severity, 0) + 1
        projection: dict[str, Any] = {
            "finding_summary": {
                "reported_count": len(findings),
                "unique_count": len(unique),
                "included_count": len(selected),
                "omitted_count": max(0, len(unique) - len(selected)),
                "severity_counts": dict(sorted(severity_counts.items())),
            },
            "findings": [_project_finding(item) for item in selected],
        }
        for key, value in data.items():
            if key != "findings":
                projection[key] = _bounded_value(value, 2_000)
        projection["projection"] = {
            "version": "tool-observation-v1",
            "source_sha256": _payload_sha256(data),
            "source_chars": raw_size,
            "truncated": len(unique) > len(selected),
        }
        return projection
    if raw_size <= MAX_PROJECTED_DATA_CHARS:
        return data.copy()
    return {
        "projection": {
            "version": "tool-observation-v1",
            "source_sha256": _payload_sha256(data),
            "source_chars": raw_size,
            "truncated": True,
        },
        "keys": sorted(str(key) for key in data),
        "summary": _bounded_text(_canonical_json(data), MAX_PROJECTED_DATA_CHARS),
    }


def _deduplicate_findings(findings: list[Any]) -> list[dict[str, Any]]:
    unique: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for raw in findings:
        if not isinstance(raw, dict):
            continue
        key = (
            str(raw.get("rule_id") or raw.get("test_id") or "UNKNOWN").upper(),
            str(raw.get("path") or raw.get("filename") or "unknown").replace("\\", "/"),
            str(raw.get("line") or raw.get("line_number") or ""),
            str(raw.get("title") or raw.get("test_name") or "").strip().lower(),
        )
        candidate = dict(raw)
        existing = unique.get(key)
        if existing is None or _finding_sort_key(candidate) < _finding_sort_key(existing):
            unique[key] = candidate
    return list(unique.values())


def _finding_sort_key(finding: dict[str, Any]) -> tuple[int, int, str, int, str]:
    severity = str(
        finding.get("severity") or finding.get("issue_severity") or "UNKNOWN"
    ).upper()
    confidence_value = finding.get("confidence") or finding.get("issue_confidence") or "UNKNOWN"
    if isinstance(confidence_value, (int, float)):
        confidence = round(float(confidence_value) * 3)
    else:
        confidence = CONFIDENCE_RANK.get(str(confidence_value).upper(), 0)
    path = str(finding.get("path") or finding.get("filename") or "unknown")
    line = int(finding.get("line") or finding.get("line_number") or 0)
    rule_id = str(finding.get("rule_id") or finding.get("test_id") or "UNKNOWN")
    return (-SEVERITY_RANK.get(severity, 0), -confidence, path, line, rule_id)


def _project_finding(finding: dict[str, Any]) -> dict[str, Any]:
    evidence_ids = finding.get("evidence_ids")
    return {
        "finding_id": finding.get("finding_id"),
        "rule_id": finding.get("rule_id") or finding.get("test_id") or "UNKNOWN",
        "severity": str(
            finding.get("severity") or finding.get("issue_severity") or "UNKNOWN"
        ).upper(),
        "confidence": finding.get("confidence") or finding.get("issue_confidence") or "UNKNOWN",
        "path": finding.get("path") or finding.get("filename") or "unknown",
        "line": finding.get("line") or finding.get("line_number"),
        "title": _bounded_text(
            str(finding.get("title") or finding.get("test_name") or "Finding"), 240
        ),
        "description": _bounded_text(
            str(finding.get("description") or finding.get("issue_text") or ""), 600
        ),
        "remediation": _bounded_text(str(finding.get("remediation") or ""), 400),
        "evidence_ids": (
            [str(item) for item in evidence_ids[:8]] if isinstance(evidence_ids, list) else []
        ),
    }


def _bounded_value(value: Any, limit: int) -> Any:
    serialized = _canonical_json(value)
    if len(serialized) <= limit:
        return value
    return {
        "sha256": hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
        "source_chars": len(serialized),
        "summary": _bounded_text(serialized, limit),
        "truncated": True,
    }


def _payload_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _bounded_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)].rstrip() + "..."


def _agent_result_observation(result: AgentResult, role: AgentRole) -> AgentObservation:
    projected_data = project_tool_data(result.data)
    report = AgentFinalReport(
        agent_instance_id=result.agent_instance_id,
        task_id=result.task_id,
        status=result.status.value,
        summary=result.summary,
        data=projected_data,
        artifact_refs=result.artifact_refs[:MAX_OBSERVATION_REFS],
        evidence_ids=result.evidence_ids[:MAX_OBSERVATION_REFS],
        finding_ids=result.finding_ids[:MAX_OBSERVATION_REFS],
        error_code=result.error_code,
        error_message=result.error_message,
    )
    return AgentObservation(
        source="agent",
        source_id=result.agent_instance_id,
        summary=_bounded_text(
            result.summary or result.error_message or f"{role.value} returned no summary",
            1_200,
        ),
        status=result.status.value,
        artifact_refs=result.artifact_refs[:MAX_OBSERVATION_REFS],
        evidence_ids=result.evidence_ids[:MAX_OBSERVATION_REFS],
        finding_ids=result.finding_ids[:MAX_OBSERVATION_REFS],
        final_report=report,
        metadata={
            "delegated_role": role.value,
            "artifact_ref_count": len(result.artifact_refs),
            "evidence_id_count": len(result.evidence_ids),
            "finding_id_count": len(result.finding_ids),
        },
    )


def _tool_result_observation(result: UnifiedToolResult) -> AgentObservation:
    projected_data = project_tool_data(result.data)
    return AgentObservation(
        source="tool",
        source_id=result.invocation_id,
        summary=_bounded_text(
            result.text or result.error_message or f"{result.tool_id} returned no summary",
            1_200,
        ),
        status=result.status.value,
        data=projected_data,
        artifact_refs=result.artifact_refs[:MAX_OBSERVATION_REFS],
        evidence_ids=result.evidence_ids[:MAX_OBSERVATION_REFS],
        metadata={
            "tool_id": result.tool_id,
            "error_code": result.error_code,
            "duration_ms": result.duration_ms,
            "artifact_ref_count": len(result.artifact_refs),
            "evidence_id_count": len(result.evidence_ids),
            "projection_chars": len(_canonical_json(projected_data)),
            "source_data_sha256": _payload_sha256(result.data),
        },
    )


def _policy_observation(*, source_id: str, summary: str, terminal: bool) -> AgentObservation:
    return AgentObservation(
        source="policy",
        source_id=source_id,
        summary=summary,
        status="blocked" if terminal else "guidance",
        metadata={"terminal": terminal},
    )


def _action_repair_observation(
    *,
    response_sha256: str,
    attempts: int,
    repaired_action: AgentAction | None,
    diagnostic: str,
) -> AgentObservation:
    failed = repaired_action is None
    return AgentObservation(
        source="policy",
        source_id=f"action-repair:{response_sha256}",
        summary=(
            "Agent action envelope could not be repaired"
            if failed
            else "Agent action envelope was repaired and validated"
        ),
        status="failed" if failed else "completed",
        data={
            "error_code": "AGENT_ACTION_REPAIR_FAILED" if failed else None,
            "attempts": attempts,
            "retryable": False,
            "response_sha256": response_sha256,
            "diagnostic": diagnostic,
            "repaired_action": None if failed else repaired_action.action.value,
        },
        metadata={"terminal": failed},
    )


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
        max_action_repair_attempts: int | None = 1,
        loop_guard_config: LoopGuardConfig | None = None,
    ) -> None:
        super().__init__(descriptor)
        if max_iterations < 1:
            raise ValueError("max_iterations must be positive")
        if max_reflections < 0:
            raise ValueError("max_reflections must not be negative")
        if max_action_repair_attempts is not None and max_action_repair_attempts < 0:
            raise ValueError("max_action_repair_attempts must not be negative")
        self.model = model
        self.prompts = prompts
        self.max_iterations = max_iterations
        self.max_reflections = max_reflections
        self.max_action_repair_attempts = (
            1 if max_action_repair_attempts is None else max_action_repair_attempts
        )
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

        action_repair_attempts = 0
        retry_without_thinking = False
        loop_guard = AgentLoopGuard(self.loop_guard_config)
        for iteration in range(1, self.max_iterations + 1):
            if context.stop_requested():
                return self._cancelled(context)
            catalog_text, catalog_digest = render_tool_catalog(
                self.descriptor,
                context.tool_catalog(),
                compact=True,
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
            request_kwargs = {
                "stage": f"agent.{self.descriptor.role.value}",
                "model_profile": self.descriptor.model_profile,
                "run_id": context.task.run_id,
                "flow_id": context.task.flow_id,
                "agent_instance_id": context.instance.instance_id,
                "task_id": context.task.task_id,
                "iteration": iteration,
                "response_schema": AgentAction.model_json_schema(),
                "json_mode": True,
            }
            if retry_without_thinking:
                request_kwargs["thinking_enabled"] = False
            response = await self.model.complete(request_messages, **request_kwargs)
            context.chain.append(
                "assistant",
                response.content,
                tool_calls=response.tool_calls,
                provider=response.provider,
                model=response.model,
                iteration=iteration,
            )
            if context.stop_requested():
                return self._cancelled(context)
            if response.should_retry_without_thinking and not retry_without_thinking:
                response_sha256 = hashlib.sha256(response.content.encode("utf-8")).hexdigest()
                await context.publish_runtime_event(
                    "agent.action_invalid",
                    {
                        "response_sha256": response_sha256,
                        "diagnostic": str(response.empty_content_reason),
                        "repair_attempts_used": action_repair_attempts,
                    },
                )
                context.chain.append_observation(
                    _policy_observation(
                        source_id=f"action-retry:{response_sha256}",
                        summary=(
                            "Model returned reasoning without an Action; retrying once "
                            "with thinking disabled."
                        ),
                        terminal=False,
                    )
                )
                retry_without_thinking = True
                continue
            retry_without_thinking = False
            try:
                action = parse_agent_action(response.content)
            except AgentActionError as error:
                response_sha256 = hashlib.sha256(response.content.encode("utf-8")).hexdigest()
                await context.publish_runtime_event(
                    "agent.action_invalid",
                    {
                        "response_sha256": response_sha256,
                        "diagnostic": type(error.__cause__).__name__,
                        "repair_attempts_used": action_repair_attempts,
                    },
                )
                repair_forbidden = self.descriptor.role in {
                    AgentRole.REFLECTOR,
                    AgentRole.TOOLCALL_FIXER,
                }
                if repair_forbidden or action_repair_attempts >= self.max_action_repair_attempts:
                    observation = _action_repair_observation(
                        response_sha256=response_sha256,
                        attempts=action_repair_attempts,
                        repaired_action=None,
                        diagnostic="repair_not_available",
                    )
                    context.chain.append_observation(observation)
                    return self._failed(
                        context,
                        code="AGENT_ACTION_REPAIR_FAILED",
                        message=observation.summary,
                    )
                action_repair_attempts += 1
                action, diagnostic = await self._repair_action(
                    context,
                    response.content,
                    attempt=action_repair_attempts,
                )
                observation = _action_repair_observation(
                    response_sha256=response_sha256,
                    attempts=action_repair_attempts,
                    repaired_action=action,
                    diagnostic=diagnostic,
                )
                context.chain.append_observation(observation)
                if action is None:
                    return self._failed(
                        context,
                        code="AGENT_ACTION_REPAIR_FAILED",
                        message=observation.summary,
                    )

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
                context.chain.append_observation(
                    _policy_observation(
                        source_id=loop_detection.detection_id,
                        summary=loop_detection.model_instruction(),
                        terminal=loop_detection.terminal,
                    )
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
                context.chain.append_observation(_agent_result_observation(result, action.role))
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
                    context.chain.append_observation(
                        _policy_observation(
                            source_id=loop_detection.detection_id,
                            summary=loop_detection.model_instruction(),
                            terminal=loop_detection.terminal,
                        )
                    )
                    if loop_detection.terminal:
                        return self._failed(
                            context,
                            code="AGENT_LOOP_DETECTED",
                            message=("Agent ignored repeated loop-guard strategy-change requests"),
                        )
                continue

            assert action.tool_id is not None
            tool_result = await context.invoke_tool(action.tool_id, action.arguments)
            context.chain.append_observation(_tool_result_observation(tool_result))
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
                context.chain.append_observation(
                    _policy_observation(
                        source_id=loop_detection.detection_id,
                        summary=loop_detection.model_instruction(),
                        terminal=loop_detection.terminal,
                    )
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

    async def _repair_action(
        self,
        context: AgentRunContext,
        invalid_content: str,
        *,
        attempt: int,
    ) -> tuple[AgentAction | None, str]:
        prompt, prompt_version_id = await self.prompts.render(
            "toolcall_fixer",
            {
                "AgentRole": self.descriptor.role.value,
                "Objective": context.task.objective,
                "InvalidResponseSha256": hashlib.sha256(
                    invalid_content.encode("utf-8")
                ).hexdigest(),
            },
        )
        messages = [
            LLMMessage(
                role="system",
                content=(
                    f"{prompt}\n\nReturn exactly one corrected Agent action matching this schema; "
                    "do not return a wrapper or prose."
                ),
                metadata={"prompt_key": "toolcall_fixer"},
            ),
            LLMMessage(role="user", content=invalid_content),
        ]
        try:
            response = await self.model.complete(
                messages,
                stage="agent.toolcall_fixer",
                model_profile="fallback",
                run_id=context.task.run_id,
                flow_id=context.task.flow_id,
                agent_instance_id=context.instance.instance_id,
                task_id=context.task.task_id,
                iteration=attempt,
                response_schema=AgentAction.model_json_schema(),
                json_mode=True,
                prompt_version_id=prompt_version_id,
            )
            return parse_agent_action(response.content), "repaired_action_valid"
        except AgentActionError as error:
            return None, f"invalid_repair:{type(error.__cause__).__name__}"
        except Exception as error:
            return None, f"repair_error:{type(error).__name__}"

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
