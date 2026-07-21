from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Iterable
from enum import StrEnum
from typing import Any, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.schemas.runtime import VerificationVerdict
from app.schemas.tools import (
    ToolExecutionStatus,
    ToolOrigin,
    UnifiedToolDefinition,
    UnifiedToolInvocation,
    UnifiedToolResult,
)
from tools.safety import safe_error_message

from .loop_guard import result_fingerprint


class VerificationToolGateway(Protocol):
    async def invoke(self, invocation: UnifiedToolInvocation) -> UnifiedToolResult: ...


class VerifierToolRegistry(Protocol):
    def register_native(
        self,
        definition: UnifiedToolDefinition,
        handler: Callable[[UnifiedToolInvocation], Awaitable[UnifiedToolResult]],
    ) -> None: ...


class PredicateOperator(StrEnum):
    EXISTS = "exists"
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    CONTAINS = "contains"
    TRUTHY = "truthy"


class VerificationPredicate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pointer: str = Field(
        default="",
        max_length=500,
        description="RFC 6901 JSON Pointer into UnifiedToolResult",
    )
    operator: PredicateOperator
    expected: Any = None

    @model_validator(mode="after")
    def validate_pointer(self) -> VerificationPredicate:
        if self.pointer and not self.pointer.startswith("/"):
            raise ValueError("pointer must be empty or start with /")
        return self


class VerificationProbe(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_id: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: float | None = Field(default=None, gt=0)


class VerificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verification_id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str
    flow_id: str
    finding_id: str
    claim: str = Field(min_length=1, max_length=20_000)
    verifier_agent_instance_id: str
    subject_agent_instance_id: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    reproduction: VerificationProbe
    baseline: VerificationProbe
    negative_control: VerificationProbe | None = None
    confirm_when: VerificationPredicate
    reject_when: VerificationPredicate | None = None
    scope: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_independence_and_controls(self) -> VerificationRequest:
        if self.subject_agent_instance_id == self.verifier_agent_instance_id:
            raise ValueError("verifier must use an independent Agent instance")
        probes = [self.baseline]
        if self.negative_control is not None:
            probes.append(self.negative_control)
        if any(item.tool_id != self.reproduction.tool_id for item in probes):
            raise ValueError("reproduction and controls must use the same tool")
        if self.reproduction.arguments == self.baseline.arguments:
            raise ValueError("baseline arguments must differ from reproduction arguments")
        if (
            self.negative_control is not None
            and self.negative_control.arguments == self.reproduction.arguments
        ):
            raise ValueError("negative-control arguments must differ from reproduction arguments")
        return self


class ProbeObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    invocation_id: str
    tool_id: str
    status: ToolExecutionStatus
    result_fingerprint: str
    confirm_matched: bool
    reject_matched: bool | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None


class VerificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verification_id: str
    finding_id: str
    verdict: VerificationVerdict
    method_summary: str
    source_evidence_valid: bool
    evidence_ids: list[str] = Field(default_factory=list)
    counterevidence_refs: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    reproduction: ProbeObservation
    baseline: ProbeObservation
    negative_control: ProbeObservation | None = None
    confidence: float = Field(ge=0, le=1)


EvidenceResolver = Callable[
    [str, str, list[str]],
    set[str] | Awaitable[set[str]],
]
VerifierEventPublisher = Callable[
    [str, VerificationRequest, dict[str, Any]],
    None | Awaitable[None],
]


class IndependentVerifier:
    """Reproduce a finding with a baseline and optional negative control."""

    def __init__(
        self,
        *,
        tool_gateway: VerificationToolGateway,
        evidence_resolver: EvidenceResolver,
        publisher: VerifierEventPublisher | None = None,
    ) -> None:
        self.tool_gateway = tool_gateway
        self.evidence_resolver = evidence_resolver
        self.publisher = publisher

    async def verify(self, request: VerificationRequest) -> VerificationResult:
        source_ids = await self._resolve_evidence(
            request.run_id,
            request.finding_id,
            request.evidence_ids,
        )
        source_evidence_valid = bool(request.evidence_ids) and source_ids == set(
            request.evidence_ids
        )
        await self._publish(
            "verification.started",
            request,
            {
                "verification_id": request.verification_id,
                "finding_id": request.finding_id,
                "evidence_ids": request.evidence_ids,
                "reproduction_tool_id": request.reproduction.tool_id,
                "has_negative_control": request.negative_control is not None,
            },
        )

        reproduction = await self._run_probe("reproduction", request.reproduction, request)
        baseline = await self._run_probe("baseline", request.baseline, request)
        negative = (
            None
            if request.negative_control is None
            else await self._run_probe("negative_control", request.negative_control, request)
        )
        result = self._classify(
            request,
            source_evidence_valid=source_evidence_valid,
            reproduction=reproduction,
            baseline=baseline,
            negative_control=negative,
        )
        await self._publish(
            "verification.completed",
            request,
            result.model_dump(mode="json"),
        )
        return result

    async def _run_probe(
        self,
        label: str,
        probe: VerificationProbe,
        request: VerificationRequest,
    ) -> ProbeObservation:
        invocation = UnifiedToolInvocation(
            run_id=request.run_id,
            flow_id=request.flow_id,
            agent_instance_id=request.verifier_agent_instance_id,
            tool_id=probe.tool_id,
            arguments=probe.arguments,
            timeout_seconds=probe.timeout_seconds,
            metadata={
                "verification_id": request.verification_id,
                "verification_probe": label,
                "scope": request.scope,
                "goal": f"独立验证 Finding {request.finding_id}",
                "rationale_summary": (
                    f"执行独立{label}探针，验证原结论是否可复现并与基线区分。"
                ),
                "expected_outcome": "获得可与确认/反证谓词比较的独立工具结果。",
            },
        )
        try:
            result = await self.tool_gateway.invoke(invocation)
        except Exception as error:
            result = UnifiedToolResult(
                invocation_id=invocation.invocation_id,
                tool_id=invocation.tool_id,
                status=ToolExecutionStatus.FAILED,
                error_code="verifier_probe_error",
                error_message=f"{type(error).__name__}: {safe_error_message(error)}",
            )
        return ProbeObservation(
            label=label,
            invocation_id=invocation.invocation_id,
            tool_id=invocation.tool_id,
            status=result.status,
            result_fingerprint=result_fingerprint(result),
            confirm_matched=_matches(request.confirm_when, result),
            reject_matched=(
                None if request.reject_when is None else _matches(request.reject_when, result)
            ),
            evidence_ids=result.evidence_ids,
            error_code=result.error_code,
            error_message=result.error_message,
        )

    @staticmethod
    def _classify(
        request: VerificationRequest,
        *,
        source_evidence_valid: bool,
        reproduction: ProbeObservation,
        baseline: ProbeObservation,
        negative_control: ProbeObservation | None,
    ) -> VerificationResult:
        observations = [reproduction, baseline]
        if negative_control is not None:
            observations.append(negative_control)
        limitations: list[str] = []
        if not source_evidence_valid:
            limitations.append("原 Finding 的 Evidence 引用缺失或无法解析。")
        failed = [
            item.label
            for item in observations
            if item.status != ToolExecutionStatus.COMPLETED
        ]
        if failed:
            limitations.append(f"以下验证探针未成功完成：{', '.join(failed)}。")
        controls_discriminate = not baseline.confirm_matched and (
            negative_control is None or not negative_control.confirm_matched
        )
        if not controls_discriminate:
            limitations.append("确认谓词在基线或负向对照中同样成立，测试缺乏区分度。")
        predicates_conflict = (
            request.reject_when is not None
            and reproduction.confirm_matched
            and reproduction.reject_matched is True
        )
        if predicates_conflict:
            limitations.append("确认谓词与反证谓词同时成立，判定规则相互冲突。")

        probes_completed = not failed
        if (
            source_evidence_valid
            and probes_completed
            and controls_discriminate
            and not predicates_conflict
            and reproduction.confirm_matched
        ):
            verdict = VerificationVerdict.CONFIRMED
            confidence = 0.9 if negative_control is not None else 0.8
        elif (
            source_evidence_valid
            and probes_completed
            and controls_discriminate
            and not predicates_conflict
            and request.reject_when is not None
            and reproduction.reject_matched is True
        ):
            verdict = VerificationVerdict.REJECTED
            confidence = 0.9 if negative_control is not None else 0.8
        else:
            verdict = VerificationVerdict.INCONCLUSIVE
            confidence = 0.3
            if probes_completed and not reproduction.confirm_matched:
                if request.reject_when is None or reproduction.reject_matched is not True:
                    limitations.append("未复现原结论，但没有满足显式反证谓词。")

        evidence_ids = _unique(
            [
                *request.evidence_ids,
                *(item for observation in observations for item in observation.evidence_ids),
            ]
        )
        counterevidence_refs = (
            [f"tool-call:{reproduction.invocation_id}"]
            if verdict == VerificationVerdict.REJECTED
            else []
        )
        return VerificationResult(
            verification_id=request.verification_id,
            finding_id=request.finding_id,
            verdict=verdict,
            method_summary=(
                "由独立 Agent 使用同一工具分别执行目标复现、基线和可选负向对照；"
                "结果通过结构化谓词判定，未使用原 Agent 的结论作为输入。"
            ),
            source_evidence_valid=source_evidence_valid,
            evidence_ids=evidence_ids,
            counterevidence_refs=counterevidence_refs,
            limitations=_unique(limitations),
            reproduction=reproduction,
            baseline=baseline,
            negative_control=negative_control,
            confidence=confidence,
        )

    async def _resolve_evidence(
        self,
        run_id: str,
        finding_id: str,
        evidence_ids: list[str],
    ) -> set[str]:
        value = self.evidence_resolver(run_id, finding_id, evidence_ids)
        if inspect.isawaitable(value):
            value = await value
        return set(value)

    async def _publish(
        self,
        event_type: str,
        request: VerificationRequest,
        payload: dict[str, Any],
    ) -> None:
        if self.publisher is None:
            return
        value = self.publisher(event_type, request, payload)
        if inspect.isawaitable(value):
            await value


_MISSING = object()


def _matches(predicate: VerificationPredicate, result: UnifiedToolResult) -> bool:
    value = _resolve_pointer(result.model_dump(mode="json"), predicate.pointer)
    if predicate.operator == PredicateOperator.EXISTS:
        return value is not _MISSING
    if value is _MISSING:
        return False
    if predicate.operator == PredicateOperator.EQUALS:
        return value == predicate.expected
    if predicate.operator == PredicateOperator.NOT_EQUALS:
        return value != predicate.expected
    if predicate.operator == PredicateOperator.TRUTHY:
        return bool(value)
    if predicate.operator == PredicateOperator.CONTAINS:
        try:
            return predicate.expected in value
        except TypeError:
            return False
    return False


def _resolve_pointer(value: Any, pointer: str) -> Any:
    if not pointer:
        return value
    current = value
    for raw_token in pointer.removeprefix("/").split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if token not in current:
                return _MISSING
            current = current[token]
        elif isinstance(current, list):
            try:
                current = current[int(token)]
            except (IndexError, ValueError):
                return _MISSING
        else:
            return _MISSING
    return current


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(item for item in values if item))


def register_verifier_tool(
    registry: VerifierToolRegistry,
    verifier: IndependentVerifier,
) -> None:
    tool_id = "native:independent_verify"
    definition = UnifiedToolDefinition(
        tool_id=tool_id,
        name="independent_verify",
        description=(
            "Independently reproduce a Finding with a baseline and optional negative control."
        ),
        origin=ToolOrigin.NATIVE,
        input_schema={
            "type": "object",
            "required": [
                "finding_id",
                "claim",
                "subject_agent_instance_id",
                "evidence_ids",
                "reproduction",
                "baseline",
                "confirm_when",
            ],
            "properties": {
                "finding_id": {"type": "string"},
                "claim": {"type": "string"},
                "subject_agent_instance_id": {"type": "string"},
                "evidence_ids": {"type": "array", "items": {"type": "string"}},
                "reproduction": {"type": "object"},
                "baseline": {"type": "object"},
                "negative_control": {"type": ["object", "null"]},
                "confirm_when": {"type": "object"},
                "reject_when": {"type": ["object", "null"]},
                "scope": {"type": "object"},
            },
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "verdict": {
                    "type": "string",
                    "enum": [item.value for item in VerificationVerdict],
                },
                "evidence_ids": {"type": "array", "items": {"type": "string"}},
                "limitations": {"type": "array", "items": {"type": "string"}},
            },
        },
        annotations={
            "risk_level": 1,
            "idempotent": False,
            "requires_independent_agent": True,
        },
    )

    async def invoke(call: UnifiedToolInvocation) -> UnifiedToolResult:
        try:
            request = VerificationRequest.model_validate(
                {
                    "run_id": call.run_id,
                    "flow_id": call.flow_id,
                    "verifier_agent_instance_id": call.agent_instance_id,
                    **call.arguments,
                }
            )
            if request.reproduction.tool_id == tool_id:
                raise ValueError("independent verifier cannot recursively verify itself")
            result = await verifier.verify(request)
        except (ValidationError, ValueError) as error:
            return UnifiedToolResult(
                invocation_id=call.invocation_id,
                tool_id=call.tool_id,
                status=ToolExecutionStatus.FAILED,
                error_code="verification_request_invalid",
                error_message=safe_error_message(error),
            )
        return UnifiedToolResult(
            invocation_id=call.invocation_id,
            tool_id=call.tool_id,
            status=ToolExecutionStatus.COMPLETED,
            text=f"Independent verification verdict: {result.verdict.value}",
            data=result.model_dump(mode="json"),
            evidence_ids=result.evidence_ids,
        )

    registry.register_native(definition, invoke)
