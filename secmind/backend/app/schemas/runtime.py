from __future__ import annotations

from datetime import UTC, datetime
from enum import IntEnum, StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION = "1.0"


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
    TOOL_CANCELLED = "tool.cancelled"
    TOOL_REPLAYED = "tool.replayed"
    AGENT_CREATED = "agent.created"
    AGENT_STARTED = "agent.started"
    AGENT_DELEGATED = "agent.delegated"
    AGENT_MESSAGE = "agent.message"
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
    VERIFICATION_COMPLETED = "verification.completed"
    REFLECTION_COMPLETED = "reflection.completed"
    REPORT_GENERATED = "report.generated"
    EVIDENCE_RECORDED = "evidence.recorded"
    FINDING_RECORDED = "finding.recorded"
    MEMORY_CANDIDATE = "memory.candidate"
    MEMORY_COMMITTED = "memory.committed"
    MEMORY_COMMIT_FAILED = "memory.commit_failed"
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


class DecisionRecord(BaseModel):
    decision: str
    rationale_summary: str
    evidence_ids: list[str] = Field(default_factory=list)
    policy_ids: list[str] = Field(default_factory=list)
    model_id: str | None = None
    prompt_version: str | None = None
    confidence: float = Field(default=1.0, ge=0, le=1)


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
    status: RunStatus
    executive_summary: str
    findings: list[Finding] = Field(default_factory=list)
    decisions: list[DecisionRecord] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AgentState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    run_id: str
    task: TaskRequest
    scenario: Scenario = Scenario.UNKNOWN
    status: RunStatus = RunStatus.PENDING
    workspace: str = ""
    input_artifacts: list[InputArtifact] = Field(default_factory=list)
    knowledge_hits: list[KnowledgeHit] = Field(default_factory=list)
    plan: list[PlanStep] = Field(default_factory=list)
    current_step_index: int = 0
    active_step_id: str | None = None
    completed_step_ids: list[str] = Field(default_factory=list)
    observations: list[RuntimeToolResult] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
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


class LedgerEvent(BaseModel):
    schema_version: str = SCHEMA_VERSION
    event_id: str
    run_id: str
    sequence: int
    event_type: str
    timestamp: datetime
    actor: str
    payload: dict[str, Any]
    prev_hash: str
    hash: str


class RunSummary(BaseModel):
    schema_version: str = SCHEMA_VERSION
    run_id: str
    status: RunStatus
    scenario: Scenario
    current_step: int
    total_steps: int
    active_step_id: str | None = None
    verification_passed: bool | None = None
    state_revision: int = 0
    pending_approval: ApprovalRequest | None = None
    last_error: str | None = None
