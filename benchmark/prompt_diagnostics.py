"""Non-sensitive prompt and model-output diagnostics for benchmark ledgers.

This module intentionally emits only aggregate measurements. It never copies
message content, raw provider responses, or credentials into its output.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from math import ceil
from pathlib import Path
from typing import Any, Iterable


DEFAULT_SINGLE_PROMPT_TOKEN_BUDGET = 32_000
DEFAULT_TOTAL_PROMPT_TOKEN_BUDGET = 100_000


class StructuredOutputError(ValueError):
    """Raised when a model response is not a JSON object."""


@dataclass
class _StageAccumulator:
    requests: int = 0
    responses: int = 0
    errors: int = 0
    total_message_chars: int = 0
    max_message_chars: int = 0
    total_prompt_tokens: int = 0
    max_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    reasoning_only_responses: int = 0
    empty_responses: int = 0
    finish_reasons: Counter[str] = field(default_factory=Counter)
    error_types: Counter[str] = field(default_factory=Counter)


def estimate_prompt_tokens(char_count: int) -> int:
    """Return a conservative, deterministic token estimate for a text size."""

    return ceil(max(0, char_count) / 4)


def classify_response(*, content: str | None, raw: dict[str, Any] | None = None) -> str:
    """Classify response availability without retaining response text."""

    normalized = content or ""
    if normalized.strip():
        return "content"
    raw = raw or {}
    usage = raw.get("usage") if isinstance(raw.get("usage"), dict) else {}
    details = usage.get("completion_tokens_details")
    reasoning_tokens = details.get("reasoning_tokens", 0) if isinstance(details, dict) else 0
    if reasoning_tokens or usage.get("completion_tokens", 0):
        return "reasoning_only"
    return "empty"


def strip_json_fence(content: str) -> str:
    """Remove one Markdown JSON fence while rejecting surrounding prose."""

    cleaned = content.strip().lstrip("\ufeff")
    if not cleaned.startswith("```"):
        return cleaned
    first_newline = cleaned.find("\n")
    if first_newline < 0 or not cleaned.endswith("```"):
        raise StructuredOutputError("incomplete JSON code fence")
    body = cleaned[first_newline + 1 : -3].strip()
    if not body:
        raise StructuredOutputError("empty JSON code fence")
    return body


def parse_json_object(content: str) -> dict[str, Any]:
    """Parse strict JSON or one complete Markdown JSON fence."""

    try:
        value = json.loads(strip_json_fence(content))
    except (json.JSONDecodeError, StructuredOutputError) as error:
        raise StructuredOutputError("response is not one JSON object") from error
    if not isinstance(value, dict):
        raise StructuredOutputError("structured response must be a JSON object")
    return value


def validate_required_fields(payload: dict[str, Any], required: Iterable[str]) -> None:
    """Apply a small schema gate for diagnostics without accepting extra semantics."""

    missing = sorted(name for name in required if name not in payload)
    if missing:
        raise StructuredOutputError("missing required fields: " + ", ".join(missing))


def _usage(raw: dict[str, Any]) -> dict[str, Any]:
    usage = raw.get("usage")
    return usage if isinstance(usage, dict) else {}


def _stage_from_event(event_type: str, payload: dict[str, Any]) -> str:
    if event_type.startswith("model."):
        return event_type.removeprefix("model.").rsplit(".", 1)[0]
    trace = payload.get("trace_parameters")
    if isinstance(trace, dict) and trace.get("stage"):
        return str(trace["stage"])
    return "unknown"


def analyze_events(events: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate non-sensitive measurements from runtime events."""

    stages: dict[str, _StageAccumulator] = defaultdict(_StageAccumulator)
    metrics: dict[str, int] = {}
    trace_stages: dict[str, str] = {}
    total_prompt_tokens = 0
    total_message_chars = 0

    for event in events:
        event_type = str(event.get("event_type") or "")
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue

        if event_type == "input.ingested":
            if isinstance(payload.get("artifact_count"), int):
                metrics["artifact_count"] = payload["artifact_count"]
        elif event_type == "capability.routed":
            allowed = payload.get("allowed_tool_ids")
            if isinstance(allowed, list):
                metrics["allowed_tool_count"] = len(allowed)
        elif event_type in {"analysis.completed", "report.generated"}:
            if isinstance(payload.get("finding_count"), int):
                metrics["finding_count"] = payload["finding_count"]
            if isinstance(payload.get("evidence_count"), int):
                metrics["evidence_count"] = payload["evidence_count"]

        is_request = event_type == "llm.request" or (
            event_type.startswith("model.") and event_type.endswith(".request")
        )
        is_response = event_type == "llm.response" or (
            event_type.startswith("model.") and event_type.endswith(".response")
        )
        is_error = event_type == "llm.error" or (
            event_type.startswith("model.") and event_type.endswith(".error")
        )
        if not (is_request or is_response or is_error):
            continue

        trace_id = str(payload.get("trace_id") or "")
        stage = _stage_from_event(event_type, payload)
        if event_type == "llm.request" and trace_id:
            trace_stages[trace_id] = stage
        elif event_type.startswith("llm.") and trace_id in trace_stages:
            stage = trace_stages[trace_id]
        current = stages[stage]
        if is_request:
            messages = payload.get("messages")
            message_chars = (
                sum(
                    len(str(item.get("content") or ""))
                    for item in messages
                    if isinstance(item, dict)
                )
                if isinstance(messages, list)
                else 0
            )
            current.requests += 1
            current.total_message_chars += message_chars
            current.max_message_chars = max(current.max_message_chars, message_chars)
            total_message_chars += message_chars
        elif is_response:
            current.responses += 1
            content = payload.get("content")
            raw = payload.get("raw") if isinstance(payload.get("raw"), dict) else {}
            usage = _usage(raw)
            prompt_tokens = int(usage.get("prompt_tokens") or 0)
            completion_tokens = int(usage.get("completion_tokens") or 0)
            current.total_prompt_tokens += prompt_tokens
            current.max_prompt_tokens = max(current.max_prompt_tokens, prompt_tokens)
            current.total_completion_tokens += completion_tokens
            total_prompt_tokens += prompt_tokens
            classification = classify_response(content=content, raw=raw)
            if classification == "reasoning_only":
                current.reasoning_only_responses += 1
            elif classification == "empty":
                current.empty_responses += 1
            finish_reason = raw.get("choices", [{}])[0].get("finish_reason") if isinstance(
                raw.get("choices"), list
            ) and raw.get("choices") else None
            if finish_reason:
                current.finish_reasons[str(finish_reason)] += 1
        else:
            current.errors += 1
            error_type = str(payload.get("error_type") or "unknown")
            current.error_types[error_type] += 1

    stage_output: dict[str, Any] = {}
    for name in sorted(stages):
        item = stages[name]
        stage_output[name] = {
            "requests": item.requests,
            "responses": item.responses,
            "errors": item.errors,
            "total_message_chars": item.total_message_chars,
            "max_message_chars": item.max_message_chars,
            "total_prompt_tokens": item.total_prompt_tokens,
            "max_prompt_tokens": item.max_prompt_tokens,
            "total_completion_tokens": item.total_completion_tokens,
            "reasoning_only_responses": item.reasoning_only_responses,
            "empty_responses": item.empty_responses,
            "finish_reasons": dict(sorted(item.finish_reasons.items())),
            "error_types": dict(sorted(item.error_types.items())),
        }
    return {
        "schema_version": "prompt-diagnostics-v1",
        "metrics": metrics,
        "request_count": sum(item.requests for item in stages.values()),
        "response_count": sum(item.responses for item in stages.values()),
        "error_count": sum(item.errors for item in stages.values()),
        "total_message_chars": total_message_chars,
        "total_prompt_tokens": total_prompt_tokens,
        "max_prompt_tokens": max(
            (item.max_prompt_tokens for item in stages.values()), default=0
        ),
        "stages": stage_output,
    }


def budget_violations(
    summary: dict[str, Any],
    *,
    single_prompt_tokens: int = DEFAULT_SINGLE_PROMPT_TOKEN_BUDGET,
    total_prompt_tokens: int = DEFAULT_TOTAL_PROMPT_TOKEN_BUDGET,
) -> list[str]:
    """Return deterministic budget failures without changing the source data."""

    violations: list[str] = []
    maximum = int(summary.get("max_prompt_tokens") or 0)
    total = int(summary.get("total_prompt_tokens") or 0)
    if maximum > single_prompt_tokens:
        violations.append(f"single_prompt_tokens>{single_prompt_tokens}")
    if total > total_prompt_tokens:
        violations.append(f"total_prompt_tokens>{total_prompt_tokens}")
    return violations


def analyze_ledger(path: Path) -> dict[str, Any]:
    events = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                events.append(json.loads(line))
    return analyze_events(events)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    summary = analyze_ledger(args.ledger)
    summary["budget_violations"] = budget_violations(summary)
    rendered = json.dumps(summary, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
