from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from benchmark.harness import (
    BenchmarkError,
    api_preflight,
    atomic_write_json,
    default_state_dir,
    load_active_dataset,
    run_smoke,
    utc_stamp,
)

TERMINAL_STATUSES = {"completed", "partial", "denied", "failed"}
CAPABILITY_UNAVAILABLE_STATUS = "capability_unavailable"


def _docker_gate(container: str, command: str, *arguments: str) -> dict[str, Any]:
    completed = subprocess.run(
        [
            "docker",
            "exec",
            container,
            "python",
            "-m",
            "benchmark_gates",
            command,
            *arguments,
        ],
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode:
        raise BenchmarkError(
            f"In-image {command} gate failed ({completed.returncode}): "
            f"{completed.stderr[-2000:]}\n{completed.stdout[-2000:]}"
        )
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise BenchmarkError(f"In-image {command} gate did not return JSON") from error


def _cleanup_benchmark_run(
    *,
    container: str,
    base_url: str,
    run_id: str,
    receipt_path: Path,
) -> dict[str, Any]:
    cleanup = _docker_gate(container, "cleanup", "--run-id", run_id)
    import httpx

    with httpx.Client(base_url=base_url.rstrip("/"), timeout=10.0) as client:
        response = client.get(f"/api/v1/runs/{run_id}")
    cleanup["api_returns_404"] = response.status_code == 404
    cleanup["passed"] = bool(cleanup.get("passed")) and cleanup["api_returns_404"]
    atomic_write_json(receipt_path, cleanup)
    if not cleanup["passed"]:
        raise BenchmarkError(f"Benchmark SQLite cleanup failed for run {run_id}")
    return cleanup


def _ledger_health(path: Path) -> dict[str, int | bool]:
    http_400_count = 0
    serialization_error_count = 0
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            event = json.loads(line)
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            diagnostics = (
                payload.get("diagnostics")
                if isinstance(payload.get("diagnostics"), dict)
                else {}
            )
            if str(event.get("event_type") or "").endswith(".error") and (
                diagnostics.get("status_code") == 400
            ):
                http_400_count += 1
            error_text = " ".join(
                str(payload.get(key) or "")
                for key in ("error", "error_type", "error_message")
            )
            if "serialization" in error_text.lower() or "msgpack" in error_text.lower():
                serialization_error_count += 1
    return {
        "http_400_count": http_400_count,
        "serialization_error_count": serialization_error_count,
    }


def _case_acceptance(result: dict[str, Any], ledger_path: Path) -> dict[str, Any]:
    report = result.get("report") if isinstance(result.get("report"), dict) else {}
    primary = (
        report.get("primary_result")
        if isinstance(report.get("primary_result"), dict)
        else {}
    )
    capability = (
        report.get("capability_plan")
        if isinstance(report.get("capability_plan"), dict)
        else {}
    )
    unavailable = (
        primary.get("status") == CAPABILITY_UNAVAILABLE_STATUS
        or capability.get("status") == CAPABILITY_UNAVAILABLE_STATUS
    )
    answer_or_unavailable = bool(
        report.get("final_answer") or primary.get("final_answer") or unavailable
    )
    completed_is_verified = (
        result.get("status") != "completed"
        or bool(report.get("final_answer_verified"))
        or (
            report.get("completion_mode") == "findings"
            and bool(report.get("review_converged"))
            and str(report.get("completion_gate_reason") or "").startswith(
                "Completion gate passed"
            )
        )
    )
    task_contract = (
        report.get("task_contract")
        if isinstance(report.get("task_contract"), dict)
        else {}
    )
    completion_checks = (
        report.get("completion_gate_checks")
        if isinstance(report.get("completion_gate_checks"), dict)
        else {}
    )
    contract_generated = all(
        task_contract.get(key)
        for key in (
            "completion_mode",
            "expected_outputs",
            "evaluator",
            "required_evidence",
            "contract_sha256",
        )
    )
    completed_satisfies_contract = result.get("status") != "completed" or (
        bool(completion_checks) and all(value is True for value in completion_checks.values())
    )
    ledger_health = _ledger_health(ledger_path)
    checks = {
        "terminal": str(result.get("status") or "").lower() in TERMINAL_STATUSES,
        "answer_or_capability_unavailable": answer_or_unavailable,
        "completed_is_independently_verified": completed_is_verified,
        "task_contract_generated": contract_generated,
        "completed_satisfies_task_contract": completed_satisfies_contract,
        "ledger_valid": bool(result.get("ledger_chain_valid")),
        "zero_http_400": ledger_health["http_400_count"] == 0,
        "zero_serialization_errors": ledger_health["serialization_error_count"] == 0,
    }
    return {
        "case_id": result.get("case_id"),
        "run_id": result.get("run_id"),
        "status": result.get("status"),
        "checks": checks,
        **ledger_health,
        "passed": all(checks.values()),
    }


def _run_exported_case(
    *,
    case_id: str,
    baseline: bool,
    experiment_id: str,
    args: argparse.Namespace,
    state_dir: Path,
    repo_root: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    result = run_smoke(
        case_id=case_id,
        base_url=args.base_url,
        state_dir=state_dir,
        repo_root=repo_root,
        timeout_seconds=args.timeout_seconds,
        cleanup=False,
        baseline=baseline,
        experiment_id=experiment_id,
    )
    result_dir = (
        state_dir / "results" / experiment_id / "round-1" / case_id
    )
    acceptance = _case_acceptance(result, result_dir / "ledger.jsonl")
    cleanup = _cleanup_benchmark_run(
        container=args.container,
        base_url=args.base_url,
        run_id=str(result["run_id"]),
        receipt_path=result_dir / "cleanup-receipt.json",
    )
    acceptance["cleanup"] = cleanup
    acceptance["checks"]["cleanup_verified"] = bool(cleanup["passed"])
    acceptance["passed"] = all(acceptance["checks"].values())
    return result, acceptance


def _run_twelve_case_gate(
    *,
    args: argparse.Namespace,
    state_dir: Path,
    repo_root: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    selection = json.loads(args.selection.resolve().read_text(encoding="utf-8"))
    active, cases = load_active_dataset(state_dir)
    case_ids = [str(item["case_id"]) for item in selection.get("cases", [])]
    if len(case_ids) != 12 or len(set(case_ids)) != 12:
        raise BenchmarkError("Baseline selection must contain exactly 12 unique cases")
    known_ids = {str(item["case_id"]) for item in cases}
    missing = sorted(set(case_ids) - known_ids)
    if missing:
        raise BenchmarkError(f"Baseline selection contains unknown cases: {', '.join(missing)}")
    if selection.get("dataset_sha256") != active["archive_sha256"]:
        raise BenchmarkError("Baseline selection does not match the active dataset")

    experiment_id = f"baseline-{selection['selection_id']}-{utc_stamp()}"
    batch_root = state_dir / "results" / experiment_id
    summary_path = batch_root / "batch-summary.json"
    batch: dict[str, Any] = {
        "schema_version": "1.0",
        "experiment_id": experiment_id,
        "selection_id": selection["selection_id"],
        "dataset_sha256": active["archive_sha256"],
        "case_count": 12,
        "completed_count": 0,
        "results": [],
        "started_at": datetime.now(UTC).isoformat(),
    }
    atomic_write_json(summary_path, batch)
    acceptance: list[dict[str, Any]] = []
    for position, case_id in enumerate(case_ids, start=1):
        result, accepted = _run_exported_case(
            case_id=case_id,
            baseline=True,
            experiment_id=experiment_id,
            args=args,
            state_dir=state_dir,
            repo_root=repo_root,
        )
        acceptance.append(accepted)
        entry = {
            "position": position,
            "case_id": case_id,
            "run_id": result["run_id"],
            "status": result["status"],
            "passed": accepted["passed"],
            "result_path": str(batch_root / "round-1" / case_id / "result.json"),
            "cleanup_verified": accepted["checks"]["cleanup_verified"],
        }
        batch["results"].append(entry)
        batch["completed_count"] = position
        atomic_write_json(summary_path, batch)
        if not accepted["passed"]:
            batch["stopped_at_case"] = case_id
            batch["finished_at"] = datetime.now(UTC).isoformat()
            atomic_write_json(summary_path, batch)
            raise BenchmarkError(f"12-case acceptance stopped at {case_id}")
    batch["finished_at"] = datetime.now(UTC).isoformat()
    batch["passed"] = True
    atomic_write_json(summary_path, batch)
    return batch, acceptance


def run_quality_gates(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = args.repo_root.resolve()
    state_dir = (args.state_dir or default_state_dir(repo_root)).resolve()
    gate_root = state_dir / "gates" / utc_stamp()
    gate_root.mkdir(parents=True, exist_ok=False)

    preflight = api_preflight(args.base_url, state_dir, repo_root)
    if not preflight.get("ready_for_static_smoke"):
        raise BenchmarkError("Preflight is not ready for the static smoke gate")
    canary = _docker_gate(args.container, "canary")
    checkpoint = _docker_gate(args.container, "checkpoint")
    atomic_write_json(gate_root / "canary.json", canary)
    atomic_write_json(gate_root / "checkpoint.json", checkpoint)
    if not canary.get("passed") or not checkpoint.get("passed"):
        raise BenchmarkError("Canary or checkpoint gate failed")

    experiment_id = f"quality-two-{utc_stamp()}"
    case_results: list[dict[str, Any]] = []
    for case_id, baseline in (
        (args.static_case, False),
        (args.dynamic_case, True),
    ):
        _, accepted = _run_exported_case(
            case_id=case_id,
            baseline=baseline,
            experiment_id=experiment_id,
            args=args,
            state_dir=state_dir,
            repo_root=repo_root,
        )
        case_results.append(accepted)
    two_case_passed = all(item["passed"] for item in case_results)
    atomic_write_json(gate_root / "two-case.json", case_results)
    if not two_case_passed:
        raise BenchmarkError("Static/dynamic two-case gate failed")

    baseline_result: dict[str, Any] | None = None
    baseline_acceptance: list[dict[str, Any]] = []
    if not args.stop_after_two:
        baseline_result, baseline_acceptance = _run_twelve_case_gate(
            args=args,
            state_dir=state_dir,
            repo_root=repo_root,
        )
        atomic_write_json(gate_root / "twelve-case.json", baseline_acceptance)
        if len(baseline_acceptance) != 12 or not all(
            item["passed"] for item in baseline_acceptance
        ):
            raise BenchmarkError("12-case acceptance gate failed")

    summary = {
        "schema_version": "1.0",
        "checked_at": datetime.now(UTC).isoformat(),
        "preflight": preflight,
        "canary": canary,
        "checkpoint": checkpoint,
        "two_case": case_results,
        "twelve_case": baseline_acceptance,
        "baseline_experiment_id": (
            baseline_result.get("experiment_id") if baseline_result else None
        ),
        "passed": True,
    }
    atomic_write_json(gate_root / "summary.json", summary)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run SecMind benchmark quality gates")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--base-url", default="http://127.0.0.1:18100")
    parser.add_argument("--container", default="secmind-benchmark-backend-1")
    parser.add_argument("--static-case", default="BB-01")
    parser.add_argument("--dynamic-case", default="CY-WEB-01")
    parser.add_argument(
        "--selection",
        type=Path,
        default=Path(__file__).resolve().parent / "selections" / "fused-12-v1.json",
    )
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--stop-after-two", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run_quality_gates(args)
    except Exception as error:
        print(
            json.dumps(
                {"passed": False, "error_type": type(error).__name__, "error": str(error)},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
