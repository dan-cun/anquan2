from __future__ import annotations

import json

from benchmark.prompt_diagnostics import (
    DEFAULT_SINGLE_PROMPT_TOKEN_BUDGET,
    DEFAULT_TOTAL_PROMPT_TOKEN_BUDGET,
    StructuredOutputError,
    analyze_events,
    budget_violations,
    classify_response,
    parse_json_object,
    validate_required_fields,
)


def _event(event_type: str, payload: dict) -> dict:
    return {"event_type": event_type, "payload": payload}


def _synthetic_baseline_events() -> list[dict]:
    findings = [{"finding_id": f"finding-{index}"} for index in range(275)]
    return [
        _event("input.ingested", {"artifact_count": 332}),
        _event(
            "capability.routed",
            {"allowed_tool_ids": [f"tool-{index}" for index in range(88)]},
        ),
        _event("analysis.completed", {"finding_count": len(findings), "evidence_count": 275}),
        _event("model.universal_primary.request", {"messages": [{"content": "x" * 80_000}]}),
        _event(
            "model.universal_primary.response",
            {
                "content": "",
                "raw": {
                    "choices": [{"finish_reason": "length"}],
                    "usage": {
                        "prompt_tokens": 58_853,
                        "completion_tokens": 4_000,
                        "completion_tokens_details": {"reasoning_tokens": 4_000},
                    },
                },
            },
        ),
        _event("report.generated", {"finding_count": 275, "evidence_count": 275}),
    ]


def test_synthetic_baseline_extracts_public_regression_counts() -> None:
    summary = analyze_events(_synthetic_baseline_events())

    assert summary["metrics"] == {
        "allowed_tool_count": 88,
        "artifact_count": 332,
        "evidence_count": 275,
        "finding_count": 275,
    }
    assert summary["stages"]["universal_primary"]["reasoning_only_responses"] == 1
    assert summary["stages"]["universal_primary"]["finish_reasons"] == {"length": 1}


def test_prompt_budget_gate_detects_the_historical_overflow() -> None:
    summary = analyze_events(_synthetic_baseline_events())

    violations = budget_violations(
        summary,
        single_prompt_tokens=DEFAULT_SINGLE_PROMPT_TOKEN_BUDGET,
        total_prompt_tokens=DEFAULT_TOTAL_PROMPT_TOKEN_BUDGET,
    )

    assert violations == ["single_prompt_tokens>32000"]
    assert summary["total_prompt_tokens"] == 58_853


def test_prompt_budget_gate_detects_total_run_overflow() -> None:
    events = [
        _event(
            "model.agent.pentester.response",
            {
                "content": "{}",
                "raw": {"usage": {"prompt_tokens": 60_000, "completion_tokens": 100}},
            },
        ),
        _event(
            "model.universal_primary.response",
            {
                "content": "{}",
                "raw": {"usage": {"prompt_tokens": 60_000, "completion_tokens": 100}},
            },
        ),
    ]
    summary = analyze_events(events)

    assert budget_violations(summary) == [
        "single_prompt_tokens>32000",
        "total_prompt_tokens>100000",
    ]
    assert summary["total_prompt_tokens"] == 120_000


def test_compact_canary_fits_both_prompt_budgets() -> None:
    events = [
        _event("model.universal_primary.request", {"messages": [{"content": "x" * 8_000}]}),
        _event(
            "model.universal_primary.response",
            {
                "content": "{}",
                "raw": {
                    "choices": [{"finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 2_000, "completion_tokens": 100},
                },
            },
        ),
        _event("model.report.request", {"messages": [{"content": "x" * 4_000}]}),
        _event(
            "model.report.response",
            {
                "content": "summary",
                "raw": {
                    "choices": [{"finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 1_000, "completion_tokens": 50},
                },
            },
        ),
    ]
    summary = analyze_events(events)

    assert budget_violations(summary) == []
    assert summary["total_prompt_tokens"] == 3_000


def test_llm_response_is_paired_to_request_stage_by_trace_id() -> None:
    events = [
        _event(
            "llm.request",
            {
                "trace_id": "trace-1",
                "trace_parameters": {"stage": "agent.pentester"},
                "messages": [{"content": "task"}],
            },
        ),
        _event(
            "llm.response",
            {
                "trace_id": "trace-1",
                "content": "{}",
                "raw": {"usage": {"prompt_tokens": 123, "completion_tokens": 4}},
            },
        ),
    ]

    summary = analyze_events(events)

    assert summary["stages"]["agent.pentester"]["responses"] == 1
    assert summary["stages"]["agent.pentester"]["total_prompt_tokens"] == 123
    assert "unknown" not in summary["stages"]


def test_diagnostics_never_exports_message_content() -> None:
    summary = analyze_events(
        [
            _event(
                "model.plan.request",
                {"messages": [{"content": "Bearer secret-value"}]},
            )
        ]
    )

    rendered = json.dumps(summary, ensure_ascii=True)
    assert "Bearer secret-value" not in rendered
    assert "messages" not in rendered
    assert "content" not in rendered


def test_reasoning_only_and_empty_responses_are_distinguished() -> None:
    assert classify_response(
        content="",
        raw={"usage": {"completion_tokens": 4, "completion_tokens_details": {"reasoning_tokens": 4}}},
    ) == "reasoning_only"
    assert classify_response(content="", raw={}) == "empty"
    assert classify_response(content="{}", raw={}) == "content"


def test_fenced_json_is_supported_without_accepting_prose() -> None:
    assert parse_json_object("```json\n{\"status\": \"success\"}\n```") == {
        "status": "success"
    }
    try:
        parse_json_object("Explanation: {\"status\": \"success\"}")
    except StructuredOutputError:
        pass
    else:
        raise AssertionError("prose around JSON must be rejected")


def test_wrong_schema_is_reported_as_a_structured_output_error() -> None:
    payload = parse_json_object('{"status":"success"}')
    try:
        validate_required_fields(payload, ("status", "executive_summary", "findings"))
    except StructuredOutputError as error:
        assert "executive_summary" in str(error)
    else:
        raise AssertionError("missing schema fields must be rejected")
