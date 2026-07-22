from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from benchmark.harness import BenchmarkError
from benchmark.quality_gates import _case_acceptance, run_quality_gates


def write_ledger(tmp_path, events):
    path = tmp_path / "ledger.jsonl"
    path.write_text(
        "".join(json.dumps(item) + "\n" for item in events),
        encoding="utf-8",
    )
    return path


def test_completed_answer_requires_and_accepts_independent_verification(tmp_path) -> None:
    result = {
        "case_id": "case-1",
        "run_id": "run-1",
        "status": "completed",
        "ledger_chain_valid": True,
        "report": {
            "final_answer": "answer",
            "final_answer_verified": True,
            "completion_mode": "final_answer",
            "primary_result": {"status": "success", "final_answer": "answer"},
        },
    }

    accepted = _case_acceptance(result, write_ledger(tmp_path, []))

    assert accepted["passed"] is True


def test_partial_capability_unavailable_is_an_explicit_terminal_result(tmp_path) -> None:
    result = {
        "case_id": "case-2",
        "run_id": "run-2",
        "status": "partial",
        "ledger_chain_valid": True,
        "report": {
            "final_answer": None,
            "final_answer_verified": False,
            "primary_result": {"status": "capability_unavailable"},
            "capability_plan": {"status": "capability_unavailable"},
        },
    }

    accepted = _case_acceptance(result, write_ledger(tmp_path, []))

    assert accepted["passed"] is True


def test_capability_plan_alone_can_report_explicit_unavailability(tmp_path) -> None:
    result = {
        "case_id": "case-capability",
        "run_id": "run-capability",
        "status": "partial",
        "ledger_chain_valid": True,
        "report": {
            "final_answer": None,
            "primary_result": {},
            "capability_plan": {"status": "capability_unavailable"},
        },
    }

    accepted = _case_acceptance(result, write_ledger(tmp_path, []))

    assert accepted["passed"] is True
    assert accepted["checks"]["answer_or_capability_unavailable"] is True


def test_unverified_completed_answer_fails_acceptance(tmp_path) -> None:
    result = {
        "case_id": "case-unverified",
        "run_id": "run-unverified",
        "status": "completed",
        "ledger_chain_valid": True,
        "report": {
            "final_answer": "answer",
            "final_answer_verified": False,
            "completion_mode": "final_answer",
            "primary_result": {"status": "success", "final_answer": "answer"},
        },
    }

    accepted = _case_acceptance(result, write_ledger(tmp_path, []))

    assert accepted["passed"] is False
    assert accepted["checks"]["completed_is_independently_verified"] is False


def test_http_400_in_ledger_fails_case_acceptance(tmp_path) -> None:
    result = {
        "case_id": "case-3",
        "run_id": "run-3",
        "status": "partial",
        "ledger_chain_valid": True,
        "report": {
            "primary_result": {"status": "capability_unavailable"},
            "capability_plan": {"status": "capability_unavailable"},
        },
    }
    ledger = write_ledger(
        tmp_path,
        [
            {
                "event_type": "model.universal_primary.error",
                "payload": {"diagnostics": {"status_code": 400}},
            }
        ],
    )

    accepted = _case_acceptance(result, ledger)

    assert accepted["passed"] is False
    assert accepted["http_400_count"] == 1


def test_serialization_error_in_ledger_fails_case_acceptance(tmp_path) -> None:
    result = {
        "case_id": "case-serialization",
        "run_id": "run-serialization",
        "status": "partial",
        "ledger_chain_valid": True,
        "report": {
            "primary_result": {"status": "capability_unavailable"},
            "capability_plan": {"status": "capability_unavailable"},
        },
    }
    ledger = write_ledger(
        tmp_path,
        [
            {
                "event_type": "runtime.checkpoint.error",
                "payload": {"error_message": "ormsgpack serialization failed"},
            }
        ],
    )

    accepted = _case_acceptance(result, ledger)

    assert accepted["passed"] is False
    assert accepted["serialization_error_count"] == 1
    assert accepted["checks"]["zero_serialization_errors"] is False


def quality_gate_args(tmp_path: Path) -> argparse.Namespace:
    return argparse.Namespace(
        repo_root=tmp_path,
        state_dir=tmp_path / "state",
        base_url="http://127.0.0.1:18100",
        container="benchmark",
        static_case="BB-01",
        dynamic_case="CY-WEB-01",
        selection=tmp_path / "selection.json",
        timeout_seconds=30,
        stop_after_two=False,
    )


def test_two_case_failure_never_starts_twelve_cases(tmp_path, monkeypatch) -> None:
    call_order: list[str] = []
    acceptances = iter((True, False))

    monkeypatch.setattr(
        "benchmark.quality_gates.api_preflight",
        lambda *_args: {"ready_for_static_smoke": True},
    )
    monkeypatch.setattr(
        "benchmark.quality_gates._docker_gate",
        lambda *_args: {"passed": True},
    )

    def run_case(**kwargs):
        call_order.append(str(kwargs["case_id"]))
        passed = next(acceptances)
        return {}, {"passed": passed}

    def run_twelve(**_kwargs):
        call_order.append("twelve")
        return {}, []

    monkeypatch.setattr("benchmark.quality_gates._run_exported_case", run_case)
    monkeypatch.setattr("benchmark.quality_gates._run_twelve_case_gate", run_twelve)

    with pytest.raises(BenchmarkError, match="two-case"):
        run_quality_gates(quality_gate_args(tmp_path))

    assert call_order == ["BB-01", "CY-WEB-01"]


def test_twelve_cases_start_only_after_both_two_case_acceptances_pass(
    tmp_path, monkeypatch
) -> None:
    call_order: list[str] = []

    monkeypatch.setattr(
        "benchmark.quality_gates.api_preflight",
        lambda *_args: {"ready_for_static_smoke": True},
    )
    monkeypatch.setattr(
        "benchmark.quality_gates._docker_gate",
        lambda *_args: {"passed": True},
    )

    def run_case(**kwargs):
        call_order.append(str(kwargs["case_id"]))
        return {}, {"passed": True}

    def run_twelve(**_kwargs):
        call_order.append("twelve")
        acceptance = [{"passed": True} for _ in range(12)]
        return {"experiment_id": "baseline-test"}, acceptance

    monkeypatch.setattr("benchmark.quality_gates._run_exported_case", run_case)
    monkeypatch.setattr("benchmark.quality_gates._run_twelve_case_gate", run_twelve)

    result = run_quality_gates(quality_gate_args(tmp_path))

    assert result["passed"] is True
    assert call_order == ["BB-01", "CY-WEB-01", "twelve"]
