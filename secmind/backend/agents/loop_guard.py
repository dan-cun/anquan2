from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import uuid4

from app.schemas.agents import AgentResult
from app.schemas.tools import UnifiedToolResult
from tools.safety import redact_tool_value

from .actions import AgentAction, AgentActionType


class LoopReason(StrEnum):
    REPEATED_CALL = "repeated_call"
    REPEATED_RESULT = "repeated_result"
    NO_PROGRESS = "no_progress"


@dataclass(frozen=True, slots=True)
class LoopGuardConfig:
    repeated_call_threshold: int = 3
    repeated_result_threshold: int = 3
    no_progress_threshold: int = 4
    max_interventions: int = 2

    def __post_init__(self) -> None:
        for name in (
            "repeated_call_threshold",
            "repeated_result_threshold",
            "no_progress_threshold",
        ):
            if getattr(self, name) < 2:
                raise ValueError(f"{name} must be at least 2")
        if self.max_interventions < 1:
            raise ValueError("max_interventions must be at least 1")


@dataclass(frozen=True, slots=True)
class LoopDetection:
    detection_id: str
    reason: LoopReason
    action_fingerprint: str
    result_fingerprint: str | None
    repeat_count: int
    no_progress_count: int
    intervention: int
    terminal: bool

    def event_payload(self) -> dict[str, Any]:
        return {
            "detection_id": self.detection_id,
            "reason": self.reason.value,
            "action_fingerprint": self.action_fingerprint,
            "result_fingerprint": self.result_fingerprint,
            "repeat_count": self.repeat_count,
            "no_progress_count": self.no_progress_count,
            "intervention": self.intervention,
            "terminal": self.terminal,
            "required_change": (
                "停止重复当前方法，改用不同工具、参数、证据来源或委派策略。"
            ),
        }

    def model_instruction(self) -> str:
        return json.dumps(
            {
                "loop_guard": "switch_required",
                "reason": self.reason.value,
                "blocked_action_fingerprint": self.action_fingerprint,
                "required_change": (
                    "选择不同工具、参数、证据来源或委派策略；不要再次提交相同动作。"
                ),
                "terminal": self.terminal,
            },
            ensure_ascii=False,
            sort_keys=True,
        )


@dataclass(frozen=True, slots=True)
class StrategyChange:
    detection_id: str
    previous_action_fingerprint: str
    new_action_fingerprint: str
    reason: LoopReason

    def event_payload(self) -> dict[str, Any]:
        return {
            "detection_id": self.detection_id,
            "reason": self.reason.value,
            "previous_action_fingerprint": self.previous_action_fingerprint,
            "new_action_fingerprint": self.new_action_fingerprint,
        }


class AgentLoopGuard:
    """Detect repeated actions/results and progress-free cycles inside one Agent run."""

    def __init__(self, config: LoopGuardConfig | None = None) -> None:
        self.config = config or LoopGuardConfig()
        self._action_counts: dict[str, int] = {}
        self._result_counts: dict[str, int] = {}
        self._seen_results: set[str] = set()
        self._material_refs: set[str] = set()
        self._no_progress_count = 0
        self._intervention_count = 0
        self._pending: LoopDetection | None = None

    def inspect_action(
        self,
        action: AgentAction,
    ) -> tuple[str, LoopDetection | None, StrategyChange | None]:
        fingerprint = action_fingerprint(action)
        strategy_change: StrategyChange | None = None
        if self._pending is not None and fingerprint != self._pending.action_fingerprint:
            strategy_change = StrategyChange(
                detection_id=self._pending.detection_id,
                previous_action_fingerprint=self._pending.action_fingerprint,
                new_action_fingerprint=fingerprint,
                reason=self._pending.reason,
            )
            self._pending = None

        if action.action == AgentActionType.COMPLETE:
            return fingerprint, None, strategy_change

        count = self._action_counts.get(fingerprint, 0) + 1
        self._action_counts[fingerprint] = count
        if count >= self.config.repeated_call_threshold:
            return (
                fingerprint,
                self._detect(
                    LoopReason.REPEATED_CALL,
                    action_fingerprint=fingerprint,
                    result_fingerprint=None,
                    repeat_count=count,
                ),
                strategy_change,
            )
        return fingerprint, None, strategy_change

    def record_result(
        self,
        action_fingerprint: str,
        result: UnifiedToolResult | AgentResult,
        *,
        artifact_refs: list[str],
        evidence_ids: list[str],
        finding_ids: list[str],
    ) -> LoopDetection | None:
        current_refs = {
            *(f"artifact:{item}" for item in artifact_refs),
            *(f"evidence:{item}" for item in evidence_ids),
            *(f"finding:{item}" for item in finding_ids),
        }
        new_material = current_refs - self._material_refs
        self._material_refs.update(current_refs)
        fingerprint = result_fingerprint(result)
        result_count = self._result_counts.get(fingerprint, 0) + 1
        self._result_counts[fingerprint] = result_count

        if new_material:
            self._reset_progress_epoch()
            self._material_refs.update(current_refs)
            self._result_counts[fingerprint] = 1
            self._seen_results.add(fingerprint)
            return None

        if fingerprint not in self._seen_results:
            self._seen_results.add(fingerprint)
            self._no_progress_count = 0
            self._action_counts.clear()
            return None

        self._no_progress_count += 1
        if result_count >= self.config.repeated_result_threshold:
            return self._detect(
                LoopReason.REPEATED_RESULT,
                action_fingerprint=action_fingerprint,
                result_fingerprint=fingerprint,
                repeat_count=result_count,
            )
        if self._no_progress_count >= self.config.no_progress_threshold:
            return self._detect(
                LoopReason.NO_PROGRESS,
                action_fingerprint=action_fingerprint,
                result_fingerprint=fingerprint,
                repeat_count=self._no_progress_count,
            )
        return None

    def _detect(
        self,
        reason: LoopReason,
        *,
        action_fingerprint: str,
        result_fingerprint: str | None,
        repeat_count: int,
    ) -> LoopDetection:
        self._intervention_count += 1
        detection = LoopDetection(
            detection_id=str(uuid4()),
            reason=reason,
            action_fingerprint=action_fingerprint,
            result_fingerprint=result_fingerprint,
            repeat_count=repeat_count,
            no_progress_count=self._no_progress_count,
            intervention=self._intervention_count,
            terminal=self._intervention_count > self.config.max_interventions,
        )
        self._pending = detection
        return detection

    def _reset_progress_epoch(self) -> None:
        self._action_counts.clear()
        self._result_counts.clear()
        self._seen_results.clear()
        self._no_progress_count = 0
        self._intervention_count = 0
        self._pending = None


def action_fingerprint(action: AgentAction) -> str:
    if action.action == AgentActionType.TOOL:
        value: dict[str, Any] = {
            "action": action.action.value,
            "tool_id": action.tool_id,
            "arguments": action.arguments,
        }
    elif action.action == AgentActionType.DELEGATE:
        value = {
            "action": action.action.value,
            "role": None if action.role is None else action.role.value,
            "objective": _normalize_text(action.objective or ""),
            "context_refs": sorted(action.context_refs),
            "constraints": sorted(action.constraints),
            "expected_outputs": sorted(action.expected_outputs),
        }
    else:
        value = {
            "action": action.action.value,
            "summary": _normalize_text(action.summary),
            "evidence_ids": sorted(action.evidence_ids),
            "finding_ids": sorted(action.finding_ids),
        }
    return _fingerprint(value)


def result_fingerprint(result: UnifiedToolResult | AgentResult) -> str:
    if isinstance(result, UnifiedToolResult):
        value = {
            "kind": "tool",
            "tool_id": result.tool_id,
            "status": result.status.value,
            "text": _normalize_text(result.text),
            "data": result.data,
            "error_code": result.error_code,
            "error_message": _normalize_text(result.error_message or ""),
        }
    else:
        value = {
            "kind": "agent",
            "status": result.status.value,
            "summary": _normalize_text(result.summary),
            "data": result.data,
            "error_code": result.error_code,
            "error_message": _normalize_text(result.error_message or ""),
        }
    return _fingerprint(value)


def _fingerprint(value: Any) -> str:
    canonical = json.dumps(
        redact_tool_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _normalize_text(value: str) -> str:
    return " ".join(value.split())
