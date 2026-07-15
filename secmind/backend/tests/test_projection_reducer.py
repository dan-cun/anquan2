from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from ledger.projections import ProjectionReducer, projection_snapshot
from ledger.runtime_store import LedgerIntegrityError, RuntimeEventRow, RuntimeLedgerStore


def append_run_events(ledger: RuntimeLedgerStore, run_id: str) -> None:
    ledger.append(run_id, "run.queued", {"objective": "audit Python"}, actor="api")
    ledger.append(run_id, "scenario.classified", {"scenario": "code_audit"})
    ledger.append(
        run_id,
        "plan.created",
        {
            "steps": [
                {
                    "step_id": "audit-python",
                    "objective": "Run static analysis",
                    "agent_role": "executor",
                    "risk_hint": 2,
                }
            ]
        },
    )
    ledger.append(run_id, "step.selected", {"step_id": "audit-python", "index": 0})
    ledger.append(
        run_id,
        "approval.requested",
        {
            "request_id": "approval-1",
            "step_id": "audit-python",
            "tool_name": "bandit",
            "risk_level": 2,
            "reason": "operator approval required",
        },
    )
    ledger.append(
        run_id,
        "approval.resolved",
        {"request_id": "approval-1", "decision": "approve", "reason": "authorized"},
        actor="operator",
    )
    ledger.append(run_id, "tool.started", {"tool": "bandit"})
    ledger.append(
        run_id,
        "finding.recorded",
        {
            "finding_id": "finding-1",
            "rule_id": "B602",
            "severity": "HIGH",
            "confidence": "HIGH",
            "path": "app.py",
            "line": 10,
            "title": "Shell execution",
            "description": "Untrusted shell command",
            "remediation": "Use an argument list",
        },
    )
    ledger.append(
        run_id,
        "llm.response",
        {
            "provider": "qwen",
            "model": "qwen-plus",
            "raw": {
                "usage": {
                    "prompt_tokens": 20,
                    "completion_tokens": 5,
                    "total_tokens": 25,
                }
            },
        },
    )
    ledger.append(
        run_id,
        "verification.completed",
        {"step_id": "audit-python", "error": None},
    )
    ledger.append(
        run_id,
        "report.generated",
        {"status": "completed", "finding_count": 1},
    )


def test_projection_is_incremental_and_rebuilds_from_events(tmp_path) -> None:
    ledger = RuntimeLedgerStore(f"sqlite:///{tmp_path / 'runtime.db'}")
    append_run_events(ledger, "run-1")
    reducer = ProjectionReducer(ledger, batch_size=3)

    assert reducer.project_run("run-1") == 11
    first = projection_snapshot(ledger, "run-1")
    assert first["run"]["status"] == "completed"
    assert first["run"]["finding_count"] == 1
    assert first["steps"][0]["status"] == "completed"
    assert first["approvals"][0]["decision"] == "approve"
    assert first["findings"][0]["rule_id"] == "B602"
    assert first["llm_usage"][0]["total_tokens"] == 25
    assert reducer.offset("run-1") == 11

    assert reducer.project_run("run-1") == 0
    reducer.clear("run-1")
    assert projection_snapshot(ledger, "run-1")["run"] is None
    assert reducer.rebuild("run-1") == 11
    assert projection_snapshot(ledger, "run-1") == first


def test_projection_consumes_only_new_events(tmp_path) -> None:
    ledger = RuntimeLedgerStore(f"sqlite:///{tmp_path / 'runtime.db'}")
    append_run_events(ledger, "run-1")
    reducer = ProjectionReducer(ledger)
    reducer.project_run("run-1")

    ledger.append(
        "run-1",
        "llm.response",
        {
            "provider": "qwen",
            "model": "qwen-plus",
            "raw": {"usage": {"input_tokens": 3, "output_tokens": 2}},
        },
    )

    assert reducer.project_run("run-1") == 1
    usage = projection_snapshot(ledger, "run-1")["llm_usage"][0]
    assert usage["request_count"] == 2
    assert usage["total_tokens"] == 30


def test_damaged_hash_chain_blocks_replay_and_preserves_projection(tmp_path) -> None:
    ledger = RuntimeLedgerStore(f"sqlite:///{tmp_path / 'runtime.db'}")
    append_run_events(ledger, "run-1")
    reducer = ProjectionReducer(ledger)
    reducer.project_run("run-1")
    before = projection_snapshot(ledger, "run-1")

    with Session(ledger.engine) as session:
        row = session.get(RuntimeEventRow, ledger.events("run-1")[0].event_id)
        assert row is not None
        row.payload_json = '{"objective":"tampered"}'
        session.commit()

    with pytest.raises(LedgerIntegrityError, match="hash-chain verification failed"):
        ledger.replay_events("run-1")
    with pytest.raises(LedgerIntegrityError, match="hash-chain verification failed"):
        reducer.rebuild("run-1")
    assert projection_snapshot(ledger, "run-1") == before
