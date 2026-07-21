from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from alembic import command
from ledger.runtime_store import Base, RuntimeEventRow, RuntimeLedgerStore


def test_alembic_creates_runtime_and_projection_schema(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("SECMIND_DATABASE_URL", raising=False)
    monkeypatch.delenv("SECMIND_RUNTIME_DATABASE_URL", raising=False)
    database_url = f"sqlite:///{tmp_path / 'migrated.db'}"
    backend_root = Path(__file__).resolve().parents[1]
    config = Config(str(backend_root / "alembic" / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)

    command.upgrade(config, "head")

    ledger = RuntimeLedgerStore(database_url, auto_create_schema=False)
    tables = set(inspect(ledger.engine).get_table_names())
    assert {
        "alembic_version",
        "runtime_ledger_events",
        "runtime_runs",
        "projection_runs",
        "projection_steps",
        "projection_approvals",
        "projection_findings",
        "projection_llm_usage",
        "projection_offsets",
    }.issubset(tables)
    runtime_columns = {
        item["name"] for item in inspect(ledger.engine).get_columns("runtime_ledger_events")
    }
    assert {
        "schema_version",
        "flow_id",
        "correlation_id",
        "causation_id",
        "decision_id",
        "agent_instance_id",
        "task_id",
        "tool_invocation_id",
        "visibility",
    } <= runtime_columns

    event = ledger.append(
        "migration-run",
        "run.queued",
        {"objective": "verify schema", "flow_id": "flow-1"},
        context={"correlation_id": "operation-1"},
    )
    assert event.sequence == 1
    assert event.context.flow_id == "flow-1"
    assert event.context.correlation_id == "operation-1"
    assert ledger.verify("migration-run") is True

    with Session(ledger.engine) as session:
        row = session.get(RuntimeEventRow, event.event_id)
        assert row is not None
        row.correlation_id = "tampered-operation"
        session.commit()

    assert ledger.verify("migration-run") is False


def test_postgres_store_never_calls_create_all(monkeypatch) -> None:
    def fail_create_all(*args, **kwargs) -> None:
        raise AssertionError("PostgreSQL schema must be managed by Alembic")

    monkeypatch.setattr(Base.metadata, "create_all", fail_create_all)
    ledger = RuntimeLedgerStore(
        "postgresql+psycopg://secmind:unused@127.0.0.1:1/secmind"
    )
    ledger.engine.dispose()
