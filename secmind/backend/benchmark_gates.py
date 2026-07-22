from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import inspect, text

from agents.subgraph import AgentGraphState
from app.core.config import Settings
from app.schemas.agents import AgentRole
from app.schemas.runtime import AgentState, ExecutionReceipt, TaskRequest, UnitOutcomeStatus
from app.services.context import open_services
from ledger.runtime_store import RuntimeLedgerStore
from ledger.serialization import checkpoint_roundtrip

CANARY_ROLES = (
    AgentRole.PRIMARY_AGENT,
    AgentRole.CODER,
    AgentRole.PENTESTER,
    AgentRole.REPORTER,
)
UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}"
)
RUN_TABLES = (
    "context_snapshots",
    "task_notes",
    "task_todos",
    "skill_loads",
    "llm_usage",
    "llm_calls",
    "tool_calls",
    "approvals",
    "reports",
    "findings",
    "evidence",
    "artifacts",
    "agent_messages",
    "agent_delegations",
    "message_chains",
    "agent_instances",
    "projection_approvals",
    "projection_findings",
    "projection_llm_usage",
    "projection_offsets",
    "projection_steps",
    "projection_runs",
    "runtime_ledger_events",
    "runtime_runs",
)


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def checkpoint_gate(iterations: int = 100) -> dict[str, Any]:
    if iterations < 1:
        raise ValueError("iterations must be positive")
    runtime_state = AgentState(
        run_id="checkpoint-gate",
        flow_id="checkpoint-gate",
        task=TaskRequest(objective="Validate JSON-only checkpoint state"),
    )
    for index in range(iterations):
        runtime_state.receipts.append(
            ExecutionReceipt(
                unit_type="agent",
                unit_id=f"checkpoint-agent-{index}",
                status=UnitOutcomeStatus.SUCCESS,
                attempt=1,
            )
        )
        runtime_payload = checkpoint_roundtrip(
            {"runtime_state": runtime_state.model_dump(mode="json")}
        )
        agent_state: AgentGraphState = {
            "context_id": f"checkpoint-agent-{index}",
            "result": {
                "agent_instance_id": f"checkpoint-agent-{index}",
                "task_id": "checkpoint-task",
                "status": "completed",
                "summary": "checkpoint roundtrip passed",
            },
        }
        checkpoint_roundtrip(dict(agent_state))
        runtime_state = AgentState.model_validate(runtime_payload["runtime_state"])
    result = {
        "schema_version": "1.0",
        "gate": "agent_checkpoint_roundtrip",
        "iterations": iterations,
        "serialization_errors": 0,
        "passed": True,
        "checked_at": datetime.now(UTC).isoformat(),
    }
    result["sha256"] = _canonical_sha256(result)
    return result


def _safe_child(root: Path, name: str) -> Path:
    if Path(name).name != name or "/" in name or "\\" in name:
        raise ValueError(f"Unsafe benchmark cleanup target: {name}")
    resolved_root = root.resolve()
    target = (resolved_root / name).resolve()
    if target.parent != resolved_root:
        raise ValueError(f"Benchmark cleanup target escapes its root: {target}")
    return target


def cleanup_gate(run_id: str) -> dict[str, Any]:
    """Remove one exported run from the isolated benchmark SQLite runtime."""

    if not UUID_RE.fullmatch(run_id):
        raise ValueError("cleanup requires a canonical UUID run_id")
    settings = Settings()
    if not settings.resolved_database_url.startswith("sqlite:"):
        raise RuntimeError("benchmark cleanup refuses non-SQLite databases")
    ledger = RuntimeLedgerStore(settings.resolved_database_url)
    state = ledger.load_state(run_id)
    if state is None:
        raise RuntimeError(f"benchmark run is unavailable: {run_id}")
    upload_refs = [item.ref for item in state.task.attachments]
    upload_targets = [
        _safe_child(settings.resolved_runtime_upload_root, upload_ref)
        for upload_ref in upload_refs
    ]
    workspace_target = _safe_child(settings.resolved_runtime_run_root, run_id)

    remaining: dict[str, int] = {}
    with ledger.engine.begin() as connection:
        table_names = set(inspect(connection).get_table_names())
        if {"message_entries", "message_chains"}.issubset(table_names):
            connection.execute(
                text(
                    "DELETE FROM message_entries WHERE chain_id IN "
                    "(SELECT chain_id FROM message_chains WHERE run_id = :run_id)"
                ),
                {"run_id": run_id},
            )
        for table_name in RUN_TABLES:
            if table_name in table_names:
                connection.execute(
                    text(f'DELETE FROM "{table_name}" WHERE run_id = :run_id'),
                    {"run_id": run_id},
                )
        for table_name in RUN_TABLES:
            if table_name in table_names:
                count = connection.execute(
                    text(f'SELECT COUNT(*) FROM "{table_name}" WHERE run_id = :run_id'),
                    {"run_id": run_id},
                ).scalar_one()
                if count:
                    remaining[table_name] = int(count)
    if remaining:
        raise RuntimeError(f"benchmark cleanup left database records: {remaining}")

    if workspace_target.exists():
        shutil.rmtree(workspace_target)
    for target in upload_targets:
        if target.exists():
            target.unlink()
    workspace_removed = not workspace_target.exists()
    uploads_removed = all(not target.exists() for target in upload_targets)
    result = {
        "schema_version": "1.0",
        "gate": "benchmark_sqlite_cleanup",
        "run_id": run_id,
        "database_url_kind": "sqlite",
        "database_records_removed": ledger.load_state(run_id) is None,
        "checkpoint_records_removed": settings.checkpoint_backend == "memory",
        "workspace_removed": workspace_removed,
        "uploads_removed": uploads_removed,
        "upload_count": len(upload_targets),
        "cleaned_at": datetime.now(UTC).isoformat(),
    }
    result["passed"] = all(
        (
            result["database_records_removed"],
            result["checkpoint_records_removed"],
            workspace_removed,
            uploads_removed,
        )
    )
    result["sha256"] = _canonical_sha256(result)
    return result


async def model_canary_gate() -> dict[str, Any]:
    settings = Settings()
    role_results: list[dict[str, Any]] = []
    async with open_services(settings) as services:
        metadata = services.llm_provider.metadata()
        for role in CANARY_ROLES:
            flow = services.flows.create_flow(title=f"Benchmark canary: {role.value}")
            run_id = str(uuid4())
            error_type: str | None = None
            status = "failed"
            try:
                _, result = await services.collaboration.submit(
                    flow_id=flow.id,
                    run_id=run_id,
                    objective=(
                        "This is a model transport canary. Do not use tools or delegate. "
                        "Return one valid complete action with the summary 'canary ok'."
                    ),
                    expected_outputs=["valid AgentAction JSON"],
                    metadata={
                        "benchmark_gate": "four-role-canary",
                        "allowed_tool_ids": [],
                    },
                    role=role,
                )
                status = result.status.value
            except Exception as error:
                error_type = type(error).__name__
            events = services.runtime_ledger.events(run_id, limit=1_000_000)
            request_count = sum(item.event_type == "llm.request" for item in events)
            http_400_count = sum(
                item.event_type == "llm.error"
                and isinstance(item.payload.get("diagnostics"), dict)
                and item.payload["diagnostics"].get("status_code") == 400
                for item in events
            )
            role_results.append(
                {
                    "role": role.value,
                    "run_id": run_id,
                    "status": status,
                    "request_count": request_count,
                    "http_400_count": http_400_count,
                    "ledger_valid": services.runtime_ledger.verify(run_id),
                    "error_type": error_type,
                }
            )
    passed = bool(metadata.get("configured")) and all(
        item["request_count"] > 0
        and item["http_400_count"] == 0
        and item["ledger_valid"]
        for item in role_results
    )
    result = {
        "schema_version": "1.0",
        "gate": "four_role_model_canary",
        "provider": metadata.get("provider") or metadata.get("name"),
        "model": metadata.get("model"),
        "model_configured": bool(metadata.get("configured")),
        "roles": role_results,
        "http_400_count": sum(item["http_400_count"] for item in role_results),
        "passed": passed,
        "checked_at": datetime.now(UTC).isoformat(),
    }
    result["sha256"] = _canonical_sha256(result)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SecMind in-image benchmark quality gates")
    subcommands = parser.add_subparsers(dest="command", required=True)
    checkpoint = subcommands.add_parser("checkpoint")
    checkpoint.add_argument("--iterations", type=int, default=100)
    cleanup = subcommands.add_parser("cleanup")
    cleanup.add_argument("--run-id", required=True)
    subcommands.add_parser("canary")
    subcommands.add_parser("all")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "checkpoint":
        result: Any = checkpoint_gate(args.iterations)
    elif args.command == "cleanup":
        result = cleanup_gate(args.run_id)
    elif args.command == "canary":
        result = asyncio.run(model_canary_gate())
    else:
        checkpoint = checkpoint_gate(100)
        canary = asyncio.run(model_canary_gate())
        result = {
            "schema_version": "1.0",
            "checkpoint": checkpoint,
            "canary": canary,
            "passed": checkpoint["passed"] and canary["passed"],
        }
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
