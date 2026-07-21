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
    run_baseline_selection,
    run_smoke,
    utc_stamp,
)

TERMINAL_STATUSES = {"completed", "partial", "denied", "failed"}
CAPABILITY_UNAVAILABLE_STATUS = "capability_unavailable"


def _docker_gate(container: str, command: str) -> dict[str, Any]:
    completed = subprocess.run(
        ["docker", "exec", container, "python", "-m", "benchmark_gates", command],
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
    ledger_health = _ledger_health(ledger_path)
    checks = {
        "terminal": str(result.get("status") or "").lower() in TERMINAL_STATUSES,
        "answer_or_capability_unavailable": answer_or_unavailable,
        "completed_is_independently_verified": completed_is_verified,
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
        result = run_smoke(
            case_id=case_id,
            base_url=args.base_url,
            state_dir=state_dir,
            repo_root=repo_root,
            timeout_seconds=args.timeout_seconds,
            cleanup=True,
            baseline=baseline,
            experiment_id=experiment_id,
        )
        ledger_path = (
            state_dir
            / "results"
            / experiment_id
            / "round-1"
            / case_id
            / "ledger.jsonl"
        )
        case_results.append(_case_acceptance(result, ledger_path))
    two_case_passed = all(item["passed"] for item in case_results)
    atomic_write_json(gate_root / "two-case.json", case_results)
    if not two_case_passed:
        raise BenchmarkError("Static/dynamic two-case gate failed")

    baseline_result: dict[str, Any] | None = None
    baseline_acceptance: list[dict[str, Any]] = []
    if not args.stop_after_two:
        baseline_result = run_baseline_selection(
            selection_path=args.selection,
            base_url=args.base_url,
            state_dir=state_dir,
            repo_root=repo_root,
            timeout_seconds=args.timeout_seconds,
        )
        for item in baseline_result["results"]:
            result_path = Path(str(item["result_path"]))
            result = json.loads(result_path.read_text(encoding="utf-8"))
            baseline_acceptance.append(
                _case_acceptance(result, result_path.with_name("ledger.jsonl"))
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
