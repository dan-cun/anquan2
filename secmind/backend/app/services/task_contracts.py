from __future__ import annotations

import hashlib
import json
from typing import Any

from app.schemas.runtime import CompletionMode, TaskContract, TaskRequest

FINAL_ANSWER_TERMS = (
    "final_answer",
    "final answer",
    "flag",
    "solution",
    "solve",
    "答案",
    "解题",
)

EVALUATOR_BY_CASE_PREFIX = {
    "CY-": "cybench_final_answer_exact_match",
    "NYU-": "nyu_flag_exact_match",
}


def _strings(value: Any) -> list[str]:
    if value is None:
        return []
    values = value if isinstance(value, list) else [value]
    normalized: list[str] = []
    for item in values:
        text = str(item).strip()
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def _metadata_value(task: TaskRequest, key: str) -> Any:
    direct = getattr(task, key, None)
    if key in task.model_fields_set and direct not in (None, [], ""):
        return direct
    return task.metadata.get(key)


def _completion_mode(task: TaskRequest, expected_outputs: list[str]) -> CompletionMode:
    explicit = _metadata_value(task, "completion_mode")
    if explicit:
        return CompletionMode(str(explicit))
    text = " ".join([task.objective, *expected_outputs]).lower()
    return (
        CompletionMode.FINAL_ANSWER
        if any(term in text for term in FINAL_ANSWER_TERMS)
        else CompletionMode.FINDINGS
    )


def _evaluator(task: TaskRequest, mode: CompletionMode, case_id: str | None) -> str:
    explicit = _metadata_value(task, "evaluator")
    if explicit:
        return str(explicit).strip()
    if case_id:
        for prefix, evaluator in EVALUATOR_BY_CASE_PREFIX.items():
            if case_id.upper().startswith(prefix):
                return evaluator
        return "manual_no_verified_evidence"
    return (
        "final_answer_independent_verification"
        if mode == CompletionMode.FINAL_ANSWER
        else "evidence_backed_findings"
    )


def resolve_task_contract(task: TaskRequest) -> TaskContract:
    supplied_outputs = _strings(_metadata_value(task, "expected_outputs"))
    provisional_outputs = supplied_outputs or [task.objective]
    mode = _completion_mode(task, provisional_outputs)
    expected_outputs = supplied_outputs or (
        ["final_answer", "evidence", "reproduction_steps"]
        if mode == CompletionMode.FINAL_ANSWER
        else ["security_report", "findings", "evidence"]
    )
    required_evidence = _strings(_metadata_value(task, "required_evidence")) or (
        ["final_answer", "independent_verification"]
        if mode == CompletionMode.FINAL_ANSWER
        else ["verified_finding", "evidence_reference", "independent_review"]
    )
    case_id_value = task.metadata.get("case_id")
    source_value = task.metadata.get("source")
    case_id = str(case_id_value).strip() if case_id_value else None
    source = str(source_value).strip() if source_value else None
    evaluator = _evaluator(task, mode, case_id)
    canonical = {
        "completion_mode": mode.value,
        "expected_outputs": expected_outputs,
        "evaluator": evaluator,
        "required_evidence": required_evidence,
        "case_id": case_id,
        "source": source,
    }
    digest = hashlib.sha256(
        json.dumps(
            canonical,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return TaskContract(**canonical, contract_sha256=digest)
