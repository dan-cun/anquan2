from __future__ import annotations

from datetime import UTC, datetime
from enum import IntEnum, StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = "1.0"
EVENT_CONTRACT_VERSION = "1.1"


class RuntimeEventType(StrEnum):
    """Stable event names written to the append-only runtime ledger."""

    RUN_QUEUED = "run.queued"
    RUN_STARTED = "run.started"
    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"
    FLOW_CREATED = "flow.created"
    FLOW_UPDATED = "flow.updated"
    FLOW_DELETED = "flow.deleted"
    TASK_CREATED = "task.created"
    TASK_UPDATED = "task.updated"
    SUBTASK_CREATED = "subtask.created"
    SUBTASK_UPDATED = "subtask.updated"
    INPUT_USER_MESSAGE = "input.user_message"
    INPUT_APPROVAL_RESPONSE = "input.approval_response"
    INPUT_INGESTED = "input.ingested"
    SCENARIO_CLASSIFIED = "scenario.classified"
    CONTEXT_RETRIEVED = "context.retrieved"
    PLAN_CREATED = "plan.created"
    PLAN_VALIDATED = "plan.validated"
    PLAN_REVISED = "plan.revised"
    DECISION_RECORDED = "decision.recorded"
    STEP_SELECTED = "step.selected"
    STEP_BLOCKED = "step.blocked"
    STEP_DENIED = "step.denied"
    STEP_SELECTION_COMPLETE = "step.selection_complete"
    GUARDRAIL_EVALUATED = "guardrail.evaluated"
    GUARDRAIL_DENIED = "guardrail.denied"
    APPROVAL_REQUESTED = "approval.requested"
    APPROVAL_RESOLVED = "approval.resolved"
    APPROVAL_INVALID = "approval.invalid"
    APPROVAL_PREFLIGHT_DENIED = "approval.preflight_denied"
    INTERRUPT_APPROVAL_REQUIRED = "interrupt.approval_required"
    TOOL_STARTED = "tool.started"
    TOOL_COMPLETED = "tool.completed"
    TOOL_FAILED = "tool.failed"
    TOOL_TIMED_OUT = "tool.timed_out"
    TOOL_BLOCKED = "tool.blocked"
    TOOL_CANCELLED = "tool.cancelled"
    TOOL_REPLAYED = "tool.replayed"
    AGENT_CREATED = "agent.created"
    AGENT_STARTED = "agent.started"
    AGENT_DELEGATED = "agent.delegated"
    AGENT_MESSAGE = "agent.message"
    AGENT_WAITING = "agent.waiting"
    AGENT_RESUMED = "agent.resumed"
    AGENT_STOP_REQUESTED = "agent.stop_requested"
    AGENT_COMPLETED = "agent.completed"
    AGENT_FAILED = "agent.failed"
    AGENT_CANCELLED = "agent.cancelled"
    MCP_CONNECTED = "mcp.connected"
    MCP_DISCONNECTED = "mcp.disconnected"
    MCP_CAPABILITIES_UPDATED = "mcp.capabilities_updated"
    MCP_CALL_STARTED = "mcp.call_started"
    MCP_CALL_COMPLETED = "mcp.call_completed"
    MCP_CALL_FAILED = "mcp.call_failed"
    OBSERVATION_MISSING = "observation.missing"
    OBSERVATION_RECORDED = "observation.recorded"
    ANALYSIS_COMPLETED = "analysis.completed"
    VERIFICATION_STARTED = "verification.started"
    VERIFICATION_COMPLETED = "verification.completed"
    REFLECTION_COMPLETED = "reflection.completed"
    REPORT_GENERATED = "report.generated"
    EVIDENCE_RECORDED = "evidence.recorded"
    FINDING_RECORDED = "finding.recorded"
    MEMORY_CANDIDATE = "memory.candidate"
    MEMORY_COMMITTED = "memory.committed"
    MEMORY_COMMIT_FAILED = "memory.commit_failed"
    SKILL_LOADED = "skill.loaded"
    SKILL_REGISTERED = "skill.registered"
    SKILL_UPDATED = "skill.updated"
    SKILL_UNLOADED = "skill.unloaded"
    TODO_CREATED = "todo.created"
    TODO_UPDATED = "todo.updated"
    TODO_COMPLETED = "todo.completed"
    NOTE_RECORDED = "note.recorded"
    NOTE_ARCHIVED = "note.archived"
    CONTEXT_COMPRESSED = "context.compressed"
    LOOP_DETECTED = "loop.detected"
    STRATEGY_CHANGED = "strategy.changed"
    CIRCUIT_OPENED = "circuit.opened"
    CIRCUIT_HALF_OPENED = "circuit.half_opened"
    CIRCUIT_CLOSED = "circuit.closed"
    BUDGET_EXHAUSTED = "budget.exhausted"
    LLM_REQUEST = "llm.request"
    LLM_RESPONSE = "llm.response"
    LLM_ERROR = "llm.error"
    MODEL_CONFIG_TESTED = "model.config.tested"
    MODEL_CONFIG_UPDATED = "model.config.updated"
    MODEL_CONFIG_REJECTED = "model.config.rejected"
    PROMPT_VERSION_CREATED = "prompt.version_created"
    PROMPT_VERSION_ACTIVATED = "prompt.version_activated"
    PROMPTS_IMPORTED = "prompt.imported"


class EventCategory(StrEnum):
    RUN = "run"
    FLOW = "flow"
    TASK = "task"
    INPUT = "input"
    CONTEXT = "context"
    PLAN = "plan"
    DECISION = "decision"
    STEP = "step"
    POLICY = "policy"
    APPROVAL = "approval"
    AGENT = "agent"
    TOOL = "tool"
    MCP = "mcp"
    OBSERVATION = "observation"
    ANALYSIS = "analysis"
    VERIFICATION = "verification"
    REPORT = "report"
    EVIDENCE = "evidence"
    FINDING = "finding"
    MEMORY = "memory"
    SKILL = "skill"
    TODO = "todo"
    NOTE = "note"
    LOOP = "loop"
    CIRCUIT = "circuit"
    LLM = "llm"
    MODEL = "model"
    PROMPT = "prompt"
    SYSTEM = "system"


class EventVisibility(StrEnum):
    PUBLIC = "public"
    OPERATOR = "operator"
    AUDIT = "audit"


class DecisionKind(StrEnum):
    ROUTE = "route"
    PLAN = "plan"
    DELEGATE = "delegate"
    TOOL = "tool"
    WAIT = "wait"
    STOP = "stop"
    VERIFY = "verify"
    RETRY = "retry"
    COMPLETE = "complete"
    FALLBACK = "fallback"
    OTHER = "other"


class VerificationVerdict(StrEnum):
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    INCONCLUSIVE = "inconclusive"


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


def event_category(event_type: str) -> EventCategory:
    prefix = event_type.partition(".")[0]
    try:
        return EventCategory(prefix)
    except ValueError:
        return EventCategory.SYSTEM


DECISION_REQUIRED_EVENT_TYPES = frozenset(
    {
        RuntimeEventType.AGENT_DELEGATED.value,
        RuntimeEventType.AGENT_STOP_REQUESTED.value,
        RuntimeEventType.AGENT_COMPLETED.value,
        RuntimeEventType.TOOL_STARTED.value,
        RuntimeEventType.RUN_COMPLETED.value,
    }
)

TOOL_TERMINAL_EVENT_TYPES = frozenset(
    {
        RuntimeEventType.TOOL_COMPLETED.value,
        RuntimeEventType.TOOL_FAILED.value,
        RuntimeEventType.TOOL_TIMED_OUT.value,
        RuntimeEventType.TOOL_CANCELLED.value,
        RuntimeEventType.TOOL_BLOCKED.value,
    }
)


class Scenario(StrEnum):
    CODE_AUDIT = "code_audit"
    LOG_ANALYSIS = "log_analysis"
    INCIDENT_RESPONSE = "incident_response"
    PENETRATION_TEST = "penetration_test"
    UNKNOWN = "unknown"


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    PARTIAL = "partial"
    DENIED = "denied"
    FAILED = "failed"


class RiskLevel(IntEnum):
    R0 = 0
    R1 = 1
    R2 = 2
    R3 = 3


class ApprovalDecision(StrEnum):
    APPROVE = "approve"
    DENY = "deny"
    EDIT = "edit"


class ToolStatus(StrEnum):
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"
    DENIED = "denied"


class CompletionMode(StrEnum):
    FINDINGS = "findings"
    FINAL_ANSWER = "final_answer"


class CapabilityStatus(StrEnum):
    READY = "ready"
    DEGRADED = "degraded"
    UNAVAILABLE = "capability_unavailable"


class UnitOutcomeStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    CAPABILITY_UNAVAILABLE = "capability_unavailable"
    INCONCLUSIVE = "inconclusive"


class ExecutionIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    flow_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)


class AttachmentRef(BaseModel):
    ref: str = Field(min_length=1, description="Upload reference or input-root-relative path")
    name: str | None = None


class TaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    objective: str = Field(min_length=1, max_length=10_000)
    attachments: list[AttachmentRef] = Field(default_factory=list)
    target_scope: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    expected_outputs: list[str] = Field(default_factory=lambda: ["security_report"])
    autonomy_policy: Literal["graded", "approval_all", "automatic"] = "graded"

    @field_validator("objective")
    @classmethod
    def normalize_objective(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("objective must not be blank")
        return normalized


class InputArtifact(BaseModel):
    artifact_id: str = Field(default_factory=lambda: str(uuid4()))
    original_name: str
    relative_path: str
    sha256: str
    size_bytes: int
    media_type: str = "application/octet-stream"


class CapabilityRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability: str
    required: bool = True
    satisfied: bool
    matched_tool_ids: list[str] = Field(default_factory=list)
    reason: str = ""


class CapabilityPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_kind: str
    languages: list[str] = Field(default_factory=list)
    dynamic_target: bool = False
    status: CapabilityStatus
    requirements: list[CapabilityRequirement] = Field(default_factory=list)
    allowed_tool_ids: list[str] = Field(default_factory=list)
    unavailable_reason: str | None = None


class PrimaryFindingCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str = "PRIMARY-CANDIDATE"
    title: str
    path: str = "unknown"
    line: int | None = None
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL", "UNKNOWN"] = "UNKNOWN"
    root_cause: str
    impact: str
    remediation: str
    evidence_gap: str | None = None
    confidence: float = Field(default=0.5, ge=0, le=1)


class UniversalPrimaryResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: UnitOutcomeStatus
    final_answer: str | None = None
    executive_summary: str
    findings: list[PrimaryFindingCandidate] = Field(default_factory=list)
    evidence_gaps: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0, ge=0, le=1)
    limitations: list[str] = Field(default_factory=list)

    @field_validator("final_answer")
    @classmethod
    def normalize_final_answer(cls, value: str | None) -> str | None:
        normalized = value.strip() if isinstance(value, str) else None
        return normalized or None


class ExecutionReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    receipt_id: str = Field(default_factory=lambda: str(uuid4()))
    unit_type: Literal["agent", "tool", "workspace_chunk", "verification", "primary"]
    unit_id: str
    status: UnitOutcomeStatus
    attempt: int = Field(default=1, ge=1)
    error_type: str | None = None
    error_message: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    finding_ids: list[str] = Field(default_factory=list)
    artifact_refs: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class VerificationDelta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    delta_id: str = Field(default_factory=lambda: str(uuid4()))
    source: str
    finding_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    artifact_refs: list[str] = Field(default_factory=list)
    final_answer_verified: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PlanStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: str
    objective: str
    agent_role: str
    dependencies: list[str] = Field(default_factory=list)
    tool_candidates: list[str] = Field(default_factory=list)
    inputs: dict[str, Any] = Field(default_factory=dict)
    success_criteria: list[str] = Field(default_factory=list)
    risk_hint: RiskLevel = RiskLevel.R0
    max_attempts: int = Field(default=2, ge=1, le=5)


class BudgetState(BaseModel):
    max_steps: int = 12
    max_tool_calls: int = 12
    max_model_calls: int = 20
    max_runtime_seconds: int = 600
    steps_used: int = 0
    tool_calls_used: int = 0
    model_calls_used: int = 0


class Evidence(BaseModel):
    evidence_id: str = Field(default_factory=lambda: str(uuid4()))
    source: str
    summary: str
    artifact_ref: str | None = None
    sha256: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeHit(BaseModel):
    memory_id: str
    content: str
    source: str
    version: str
    confidence: float = Field(ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Finding(BaseModel):
    finding_id: str = Field(default_factory=lambda: str(uuid4()))
    rule_id: str
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL", "UNKNOWN"] = "UNKNOWN"
    confidence: Literal["LOW", "MEDIUM", "HIGH", "UNKNOWN"] = "UNKNOWN"
    path: str
    line: int | None = None
    title: str
    description: str
    remediation: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class DecisionAlternative(BaseModel):
    model_config = ConfigDict(extra="forbid")

    option: str = Field(min_length=1, max_length=2_000)
    rejection_reason: str = Field(min_length=1, max_length=4_000)
    evidence_ids: list[str] = Field(default_factory=list)


class DecisionRecord(BaseModel):
    """Public, auditable explanation of an action without private chain-of-thought."""

    model_config = ConfigDict(extra="forbid")

    decision_id: str = Field(default_factory=lambda: str(uuid4()))
    kind: DecisionKind = DecisionKind.OTHER
    goal: str = Field(default="", max_length=4_000)
    decision: str = Field(min_length=1, max_length=4_000)
    rationale_summary: str = Field(min_length=1, max_length=8_000)
    evidence_ids: list[str] = Field(default_factory=list)
    alternatives: list[DecisionAlternative] = Field(default_factory=list)
    expected_outcome: str | None = Field(default=None, max_length=4_000)
    risk_summary: str | None = Field(default=None, max_length=4_000)
    actual_outcome: str | None = Field(default=None, max_length=8_000)
    next_action: str | None = Field(default=None, max_length=4_000)
    policy_ids: list[str] = Field(default_factory=list)
    model_id: str | None = None
    prompt_version: str | None = None
    confidence: float = Field(default=1.0, ge=0, le=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ApprovalRequest(BaseModel):
    request_id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str
    step_id: str
    tool_name: str
    parameters: dict[str, Any]
    target: str
    risk_level: RiskLevel
    reason: str
    expected_impact: str


class ApprovalResponse(BaseModel):
    decision: ApprovalDecision
    actor: str = "operator"
    reason: str = ""
    edited_parameters: dict[str, Any] | None = None

    @field_validator("edited_parameters")
    @classmethod
    def require_edited_parameters(cls, value: dict[str, Any] | None, info: Any) -> Any:
        if info.data.get("decision") == ApprovalDecision.EDIT and value is None:
            raise ValueError("edited_parameters is required for edit decisions")
        return value


class ToolManifest(BaseModel):
    name: str
    version: str
    description: str
    scenarios: list[Scenario]
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    risk_level: RiskLevel
    permissions: list[str] = Field(default_factory=list)
    timeout_seconds: int = Field(default=120, ge=1, le=3600)
    idempotent: bool = True
    requires_network: bool = False


class RuntimeToolContext(BaseModel):
    run_id: str
    step_id: str
    workspace: str
    allowed_paths: list[str]


class RuntimeToolResult(BaseModel):
    status: ToolStatus
    data: dict[str, Any] = Field(default_factory=dict)
    summary: str = ""
    artifacts: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    duration_ms: int = 0
    error_code: str | None = None
    error_message: str | None = None


class AgentReport(BaseModel):
    run_id: str
    flow_id: str | None = None
    task_id: str | None = None
    status: RunStatus
    executive_summary: str
    findings: list[Finding] = Field(default_factory=list)
    decisions: list[DecisionRecord] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    agent_results: list[dict[str, Any]] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    capability_plan: CapabilityPlan | None = None
    primary_result: UniversalPrimaryResult | None = None
    receipts: list[ExecutionReceipt] = Field(default_factory=list)
    verified_deltas: list[VerificationDelta] = Field(default_factory=list)
    final_answer: str | None = None
    final_answer_verified: bool = False
    completion_mode: CompletionMode = CompletionMode.FINDINGS
    review_rounds: int = 0
    review_converged: bool = False
    completion_gate_reason: str | None = None
    limitations: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AgentState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    run_id: str
    flow_id: str | None = None
    task_id: str | None = None
    task: TaskRequest
    scenario: Scenario = Scenario.UNKNOWN
    classification_completed: bool = False
    status: RunStatus = RunStatus.PENDING
    workspace: str = ""
    input_artifacts: list[InputArtifact] = Field(default_factory=list)
    capability_plan: CapabilityPlan | None = None
    primary_result: UniversalPrimaryResult | None = None
    primary_persisted: bool = False
    receipts: list[ExecutionReceipt] = Field(default_factory=list)
    verified_deltas: list[VerificationDelta] = Field(default_factory=list)
    knowledge_hits: list[KnowledgeHit] = Field(default_factory=list)
    plan: list[PlanStep] = Field(default_factory=list)
    current_step_index: int = 0
    active_step_id: str | None = None
    completed_step_ids: list[str] = Field(default_factory=list)
    observations: list[RuntimeToolResult] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    agent_results: list[dict[str, Any]] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    artifact_refs: list[str] = Field(default_factory=list)
    collaboration_evidence_ids: list[str] = Field(default_factory=list)
    collaboration_finding_ids: list[str] = Field(default_factory=list)
    tool_call_ids: list[str] = Field(default_factory=list)
    collaboration_completed: bool = False
    completion_mode: CompletionMode = CompletionMode.FINDINGS
    final_answer: str | None = None
    final_answer_verified: bool = False
    review_round: int = Field(default=0, ge=0)
    review_finding_fingerprints: list[str] = Field(default_factory=list)
    review_converged: bool = False
    completion_gate_reason: str | None = None
    decisions: list[DecisionRecord] = Field(default_factory=list)
    pending_approval: ApprovalRequest | None = None
    approvals: list[dict[str, Any]] = Field(default_factory=list)
    retry_counts: dict[str, int] = Field(default_factory=dict)
    reflection_count: int = Field(default=0, ge=0)
    verification_passed: bool | None = None
    state_revision: int = Field(default=0, ge=0)
    budget: BudgetState = Field(default_factory=BudgetState)
    report: AgentReport | None = None
    last_error: str | None = None
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None


class EventContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    flow_id: str | None = None
    correlation_id: str | None = None
    causation_id: str | None = None
    decision_id: str | None = None
    agent_instance_id: str | None = None
    task_id: str | None = None
    tool_invocation_id: str | None = None
    visibility: EventVisibility = EventVisibility.PUBLIC


class EventEnvelope(BaseModel):
    """Versioned DTO shared by ledger replay, GraphQL, WebSocket, and UI projectors."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = EVENT_CONTRACT_VERSION
    event_id: str
    run_id: str
    sequence: int = Field(ge=1)
    event_type: str = Field(min_length=3, max_length=100)
    category: EventCategory = EventCategory.SYSTEM
    timestamp: datetime
    actor: str = Field(min_length=1, max_length=100)
    context: EventContext = Field(default_factory=EventContext)
    payload: dict[str, Any] = Field(default_factory=dict)
    decision: DecisionRecord | None = None
    verification_verdict: VerificationVerdict | None = None

    @model_validator(mode="after")
    def normalize_derived_fields(self) -> EventEnvelope:
        self.category = event_category(self.event_type)
        if self.decision is None and self.event_type == RuntimeEventType.DECISION_RECORDED:
            candidate = self.payload.get("decision", self.payload)
            if isinstance(candidate, dict):
                self.decision = DecisionRecord.model_validate(candidate)
        if self.verification_verdict is None:
            candidate_verdict = self.payload.get("verdict")
            if candidate_verdict in {item.value for item in VerificationVerdict}:
                self.verification_verdict = VerificationVerdict(candidate_verdict)
        return self


class LedgerEvent(EventEnvelope):
    prev_hash: str
    hash: str


class RunSummary(BaseModel):
    schema_version: str = SCHEMA_VERSION
    run_id: str
    flow_id: str | None = None
    task_id: str | None = None
    status: RunStatus
    scenario: Scenario
    current_step: int
    total_steps: int
    active_step_id: str | None = None
    verification_passed: bool | None = None
    completion_mode: CompletionMode = CompletionMode.FINDINGS
    final_answer_verified: bool = False
    review_round: int = 0
    review_converged: bool = False
    completion_gate_reason: str | None = None
    state_revision: int = 0
    pending_approval: ApprovalRequest | None = None
    last_error: str | None = None
