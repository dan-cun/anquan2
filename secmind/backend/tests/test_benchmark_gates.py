from __future__ import annotations

import pytest

from app.schemas.runtime import AgentState, AttachmentRef, TaskRequest
from benchmark_gates import _canary_settings, checkpoint_gate, cleanup_gate
from ledger.runtime_store import RuntimeLedgerStore


def test_checkpoint_gate_completes_one_hundred_serialization_roundtrips() -> None:
    result = checkpoint_gate(100)

    assert result["gate"] == "agent_checkpoint_roundtrip"
    assert result["iterations"] == 100
    assert result["serialization_errors"] == 0
    assert result["passed"] is True
    assert len(result["sha256"]) == 64


def test_checkpoint_gate_rejects_non_positive_iterations() -> None:
    with pytest.raises(ValueError, match="positive"):
        checkpoint_gate(0)


def test_canary_uses_an_isolated_ephemeral_runtime(tmp_path) -> None:
    settings = _canary_settings(tmp_path)

    assert settings.resolved_database_url == f"sqlite:///{(tmp_path / 'canary.db').as_posix()}"
    assert settings.resolved_ledger_dir == tmp_path / "ledger"
    assert settings.resolved_runtime_input_root == tmp_path / "inputs"
    assert settings.resolved_runtime_run_root == tmp_path / "runs"
    assert settings.resolved_runtime_upload_root == tmp_path / "uploads"
    assert settings.checkpoint_backend == "memory"
    assert settings.projection_enabled is False


def test_cleanup_gate_only_removes_isolated_sqlite_run(tmp_path, monkeypatch) -> None:
    database_url = f"sqlite:///{tmp_path / 'benchmark.db'}"
    run_root = tmp_path / "runs"
    upload_root = tmp_path / "uploads"
    run_id = "019f7b3b-c509-45a1-8d4f-f3a9f61969ea"
    upload_ref = "case-upload.zip"
    monkeypatch.setenv("SECMIND_APP_ENV", "benchmark")
    monkeypatch.setenv("SECMIND_DATABASE_URL", database_url)
    monkeypatch.setenv("SECMIND_CHECKPOINT_BACKEND", "memory")
    monkeypatch.setenv("SECMIND_RUNTIME_RUN_ROOT", str(run_root))
    monkeypatch.setenv("SECMIND_RUNTIME_UPLOAD_ROOT", str(upload_root))
    ledger = RuntimeLedgerStore(database_url)
    ledger.save_state(
        AgentState(
            run_id=run_id,
            task=TaskRequest(
                objective="cleanup test",
                attachments=[AttachmentRef(ref=upload_ref)],
            ),
        )
    )
    (run_root / run_id).mkdir(parents=True)
    upload_root.mkdir(parents=True)
    (upload_root / upload_ref).write_bytes(b"fixture")

    result = cleanup_gate(run_id)

    assert result["passed"] is True
    assert result["database_url_kind"] == "sqlite"
    assert ledger.load_state(run_id) is None
    assert not (run_root / run_id).exists()
    assert not (upload_root / upload_ref).exists()


def test_cleanup_gate_refuses_postgresql(monkeypatch) -> None:
    monkeypatch.setenv("SECMIND_APP_ENV", "benchmark")
    monkeypatch.setenv(
        "SECMIND_DATABASE_URL",
        "postgresql+psycopg://benchmark:secret@127.0.0.1:5432/benchmark",
    )

    with pytest.raises(RuntimeError, match="refuses non-SQLite"):
        cleanup_gate("019f7b3b-c509-45a1-8d4f-f3a9f61969ea")
