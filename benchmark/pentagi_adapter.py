from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from benchmark.harness import (
    BenchmarkError,
    _safe_result_payload,
    atomic_write_json,
    build_case_archive,
    load_active_dataset,
    sha256_file,
    utc_stamp,
)


PENTAGI_TERMINAL_STATUSES = {"finished", "failed"}
SAFE_CASE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
SAFE_EXPERIMENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


@dataclass(frozen=True, slots=True)
class PentagiConfig:
    base_url: str
    provider: str
    api_token: str | None
    tls_verify: bool | str

    @property
    def configured(self) -> bool:
        return bool(self.api_token)


def _load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise BenchmarkError(f"Invalid PentAGI env line {line_number}: expected KEY=VALUE")
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def load_pentagi_config(path: Path) -> PentagiConfig:
    values = _load_env_file(path)

    def setting(name: str, default: str = "") -> str:
        return os.environ.get(name, values.get(name, default)).strip()

    base_url = setting("PENTAGI_BASE_URL", "https://127.0.0.1:8443").rstrip("/")
    provider = setting("PENTAGI_PROVIDER", "deepseek")
    token = setting("PENTAGI_API_TOKEN") or None
    verify_value = setting("PENTAGI_TLS_VERIFY", "true")
    if verify_value.casefold() in {"true", "1", "yes"}:
        tls_verify: bool | str = True
    elif verify_value.casefold() in {"false", "0", "no"}:
        tls_verify = False
    else:
        ca_path = Path(verify_value).expanduser().resolve()
        if not ca_path.is_file():
            raise BenchmarkError(f"PentAGI CA bundle does not exist: {ca_path}")
        tls_verify = str(ca_path)
    if not base_url.startswith("https://"):
        raise BenchmarkError("PentAGI base URL must use HTTPS")
    if not provider:
        raise BenchmarkError("PENTAGI_PROVIDER must not be empty")
    return PentagiConfig(base_url, provider, token, tls_verify)


def _client(config: PentagiConfig, *, authenticated: bool) -> httpx.Client:
    headers = {"Accept": "application/json"}
    if authenticated:
        if not config.api_token:
            raise BenchmarkError(
                "PENTAGI_API_TOKEN is not configured; create a dedicated token in PentAGI Settings"
            )
        headers["Authorization"] = f"Bearer {config.api_token}"
    return httpx.Client(
        base_url=config.base_url,
        headers=headers,
        verify=config.tls_verify,
        timeout=30.0,
    )


def _unwrap_response(response: httpx.Response) -> Any:
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise BenchmarkError("PentAGI returned a non-object response")
    if str(payload.get("status", "success")).casefold() != "success":
        raise BenchmarkError("PentAGI returned an unsuccessful response")
    return payload.get("data", payload)


def pentagi_preflight(config: PentagiConfig) -> dict[str, Any]:
    with _client(config, authenticated=False) as client:
        public_info = _unwrap_response(client.get("/api/v1/info"))
    report: dict[str, Any] = {
        "schema_version": "1.0",
        "checked_at": datetime.now(UTC).isoformat(),
        "target": "pentagi",
        "base_url": config.base_url,
        "provider": config.provider,
        "api_reachable": True,
        "token_configured": config.configured,
        "authenticated": False,
        "provider_available": False,
        "ready": False,
        "tls_verification": "disabled" if config.tls_verify is False else "enabled",
        "server_identity": {
            "type": public_info.get("type") if isinstance(public_info, dict) else None,
            "develop": public_info.get("develop") if isinstance(public_info, dict) else None,
        },
        "blockers": [],
    }
    if not config.configured:
        report["blockers"].append("PENTAGI_API_TOKEN is not configured")
        return report
    with _client(config, authenticated=True) as client:
        providers = _unwrap_response(client.get("/api/v1/providers/"))
        _unwrap_response(client.get("/api/v1/flows/", params={"limit": 1, "offset": 0}))
    provider_items = providers.get("providers", providers) if isinstance(providers, dict) else providers
    provider_names = {
        str(item.get("name") or item.get("id") or "")
        for item in (provider_items if isinstance(provider_items, list) else [])
        if isinstance(item, dict)
    }
    report["authenticated"] = True
    report["provider_available"] = config.provider in provider_names
    if not report["provider_available"]:
        report["blockers"].append(
            f"Configured provider is not available to the token owner: {config.provider}"
        )
    report["ready"] = not report["blockers"]
    return report


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in ("tasks", "items", "rows"):
            if isinstance(value.get(key), list):
                return value[key]
    return []


def _strict_json_object(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def extract_structured_report(tasks: list[dict[str, Any]]) -> tuple[dict[str, Any], str]:
    candidates: list[tuple[str, str, dict[str, Any]]] = []
    for task in tasks:
        if str(task.get("status", "")).casefold() != "finished":
            continue
        parsed = _strict_json_object(task.get("result"))
        if parsed is None or not isinstance(parsed.get("final_answer"), str):
            continue
        final_answer = parsed["final_answer"].strip()
        if not final_answer:
            continue
        for field in ("evidence", "findings", "reproduction_steps"):
            if field in parsed and not isinstance(parsed[field], list):
                raise BenchmarkError(f"PentAGI report field must be a list: {field}")
        updated_at = str(task.get("updated_at") or task.get("updatedAt") or "")
        task_id = str(task.get("id") or "")
        candidates.append((updated_at, task_id, parsed))
    if not candidates:
        raise BenchmarkError(
            "No finished PentAGI task contains a strict JSON result with final_answer"
        )
    candidates.sort(key=lambda item: (item[0], item[1]))
    _updated_at, task_id, report = candidates[-1]
    normalized = {
        "final_answer": report["final_answer"].strip(),
        "evidence": list(report.get("evidence") or []),
        "findings": list(report.get("findings") or []),
        "reproduction_steps": list(report.get("reproduction_steps") or []),
        "source_task_id": task_id,
    }
    return normalized, task_id


def _register_batch_result(
    *,
    state_dir: Path,
    experiment_id: str,
    case_id: str,
    result_path: Path,
    result: dict[str, Any],
) -> None:
    batch_root = state_dir / "results" / experiment_id
    batch_path = batch_root / "batch-summary.json"
    if batch_path.is_file():
        batch = json.loads(batch_path.read_text(encoding="utf-8"))
    else:
        active_path = state_dir / "active-dataset.json"
        active = (
            json.loads(active_path.read_text(encoding="utf-8"))
            if active_path.is_file()
            else {}
        )
        batch = {
            "schema_version": "1.0",
            "experiment_id": experiment_id,
            "selection_id": "fused-12-v1",
            "dataset_sha256": active.get("archive_sha256"),
            "run_mode": "PENTAGI_BASELINE",
            "started_at": datetime.now(UTC).isoformat(),
            "case_count": 12,
            "completed_count": 0,
            "results": [],
        }
    results = batch.get("results")
    if not isinstance(results, list):
        raise BenchmarkError("PentAGI batch summary has an invalid results field")
    if any(str(item.get("case_id")) == case_id for item in results if isinstance(item, dict)):
        raise BenchmarkError(f"PentAGI batch already contains case: {case_id}")
    results.append(
        {
            "position": len(results) + 1,
            "case_id": case_id,
            "status": result["status"],
            "usage": result["usage"],
            "event_count": result["event_count"],
            "ledger_chain_valid": result["ledger_chain_valid"],
            "result_path": str(result_path),
            "cleanup_verified": False,
        }
    )
    batch["completed_count"] = len(results)
    batch["updated_at"] = datetime.now(UTC).isoformat()
    if len(results) == int(batch.get("case_count", 12)):
        batch["finished_at"] = batch["updated_at"]
    atomic_write_json(batch_path, batch)


def export_pentagi_flow(
    *,
    config: PentagiConfig,
    flow_id: str,
    case_id: str,
    experiment_id: str,
    state_dir: Path,
) -> dict[str, Any]:
    if not flow_id.isdigit() or int(flow_id) < 1:
        raise BenchmarkError("PentAGI flow ID must be a positive integer")
    if not SAFE_CASE_ID_RE.fullmatch(case_id):
        raise BenchmarkError("Unsafe case ID")
    if not SAFE_EXPERIMENT_ID_RE.fullmatch(experiment_id):
        raise BenchmarkError("Unsafe experiment ID")
    with _client(config, authenticated=True) as client:
        flow = _unwrap_response(client.get(f"/api/v1/flows/{flow_id}"))
        tasks_payload = _unwrap_response(client.get(f"/api/v1/flows/{flow_id}/tasks/"))
    if not isinstance(flow, dict):
        raise BenchmarkError("PentAGI flow response is not an object")
    pentagi_status = str(flow.get("status", "unknown")).casefold()
    if pentagi_status not in PENTAGI_TERMINAL_STATUSES:
        raise BenchmarkError(f"PentAGI flow is not terminal: {pentagi_status}")
    tasks = [item for item in _as_list(tasks_payload) if isinstance(item, dict)]
    extraction_error: str | None = None
    try:
        report, source_task_id = extract_structured_report(tasks)
    except BenchmarkError as error:
        report = {
            "final_answer": "",
            "evidence": [],
            "findings": [],
            "reproduction_steps": [],
            "source_task_id": None,
        }
        source_task_id = ""
        extraction_error = str(error)
    runtime_status = (
        "completed"
        if pentagi_status == "finished" and extraction_error is None
        else "partial"
        if pentagi_status == "finished"
        else "failed"
    )
    result = {
        "schema_version": "1.0",
        "experiment_id": experiment_id,
        "round": 1,
        "case_id": case_id,
        "run_id": f"pentagi-flow-{flow_id}",
        "status": runtime_status,
        "summary": {
            "target": "pentagi",
            "flow_id": flow_id,
            "flow_status": pentagi_status,
            "source_task_id": source_task_id,
            "report_extraction_error": extraction_error,
        },
        "report": report,
        "ledger_chain_valid": False,
        "event_count": 0,
        "usage": {
            "request_count": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
        "official_score": None,
        "score_status": "BASELINE_PENDING_EVALUATION",
        "finished_at": datetime.now(UTC).isoformat(),
    }
    _safe_result_payload(result)
    result_dir = state_dir / "results" / experiment_id / "round-1" / case_id
    result_dir.mkdir(parents=True, exist_ok=False)
    atomic_write_json(result_dir / "result.json", result)
    environment = {
        "experiment_id": experiment_id,
        "case_id": case_id,
        "target": "pentagi",
        "base_url": config.base_url,
        "provider": flow.get("model_provider_name") or config.provider,
        "model": flow.get("model"),
        "flow_id": flow_id,
        "started_at": flow.get("created_at"),
        "exported_at": datetime.now(UTC).isoformat(),
    }
    atomic_write_json(result_dir / "environment.json", environment)
    atomic_write_json(
        result_dir / "hashes.json",
        {
            "result.json": sha256_file(result_dir / "result.json"),
            "environment.json": sha256_file(result_dir / "environment.json"),
        },
    )
    _register_batch_result(
        state_dir=state_dir,
        experiment_id=experiment_id,
        case_id=case_id,
        result_path=result_dir / "result.json",
        result=result,
    )
    return result


def _upload_case_resource(
    client: httpx.Client,
    *,
    archive_path: Path,
    upload_name: str,
) -> dict[str, Any]:
    with archive_path.open("rb") as stream:
        payload = _unwrap_response(
            client.post(
                "/api/v1/resources/",
                files={"file": (upload_name, stream, "application/zip")},
            )
        )
    items = _as_list(payload)
    if len(items) != 1 or not isinstance(items[0], dict):
        raise BenchmarkError("PentAGI resource upload did not return exactly one item")
    item = items[0]
    if not str(item.get("id") or "").isdigit() or not str(item.get("path") or ""):
        raise BenchmarkError("PentAGI resource upload response is missing id or path")
    return item


def _case_prompt(case: dict[str, Any], resource_path: str) -> str:
    return "\n".join(
        [
            f"Authorized isolated security competition task: {case['case_id']}.",
            f"Objective: {case['objective']}",
            f"The public challenge archive is attached as resource: {resource_path}",
            "Analyze only this attached public challenge and its explicitly authorized target.",
            "Do not access benchmark evaluator files, private answers, or other challenge directories.",
            "Do not guess an answer when required tools or targets are unavailable.",
            "At completion, the Task result must be exactly one JSON object with no Markdown wrapper:",
            '{"final_answer":"exact answer or flag","evidence":[],"findings":[],"reproduction_steps":[]}',
            "Use an empty final_answer when the objective cannot be verified.",
        ]
    )


def _wait_for_flow(
    client: httpx.Client,
    *,
    flow_id: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        flow = _unwrap_response(client.get(f"/api/v1/flows/{flow_id}"))
        if not isinstance(flow, dict):
            raise BenchmarkError("PentAGI flow response is not an object")
        if str(flow.get("status", "")).casefold() in PENTAGI_TERMINAL_STATUSES:
            return flow
        time.sleep(2)
    try:
        _unwrap_response(
            client.put(f"/api/v1/flows/{flow_id}", json={"action": "stop"})
        )
    except httpx.HTTPError:
        pass
    raise BenchmarkError(f"PentAGI flow timed out after {timeout_seconds}s: {flow_id}")


def _cleanup_pentagi_case(
    client: httpx.Client,
    *,
    flow_id: str,
    resource_path: str,
    receipt_path: Path,
) -> dict[str, Any]:
    resource_removed = False
    flow_api_returns_404 = False
    try:
        _unwrap_response(client.delete("/api/v1/resources/", params={"path": resource_path}))
        resource_removed = True
    except httpx.HTTPError:
        resource_removed = False
    try:
        _unwrap_response(client.delete(f"/api/v1/flows/{flow_id}"))
        check = client.get(f"/api/v1/flows/{flow_id}")
        flow_api_returns_404 = check.status_code == 404
    except httpx.HTTPError:
        flow_api_returns_404 = False
    receipt = {
        "target": "pentagi",
        "flow_id": flow_id,
        "resource_path": resource_path,
        "resource_removed": resource_removed,
        "flow_api_returns_404": flow_api_returns_404,
        "database_records_removed": flow_api_returns_404,
        "checkpoint_records_removed": False,
        "workspace_removed": False,
        "upload_removed": resource_removed,
        "api_returns_404": flow_api_returns_404,
        "fully_verified": False,
        "limitation": (
            "PentAGI does not currently prove removal of its flow data directory or provide "
            "a checkpoint cleanup receipt"
        ),
        "cleaned_at": datetime.now(UTC).isoformat(),
    }
    atomic_write_json(receipt_path, receipt)
    return receipt


def run_pentagi_case(
    *,
    config: PentagiConfig,
    case_id: str,
    experiment_id: str,
    state_dir: Path,
    timeout_seconds: int,
    cleanup: bool,
) -> dict[str, Any]:
    active, cases = load_active_dataset(state_dir)
    case = next((item for item in cases if str(item["case_id"]) == case_id), None)
    if case is None:
        raise BenchmarkError(f"Unknown case: {case_id}")
    preflight = pentagi_preflight(config)
    if not preflight["ready"]:
        raise BenchmarkError("PentAGI preflight did not pass: " + "; ".join(preflight["blockers"]))
    archive_path = build_case_archive(case, active, state_dir)
    upload_name = f"{experiment_id}-{case_id}.zip"
    flow_id = ""
    resource_path = ""
    try:
        with _client(config, authenticated=True) as client:
            resource = _upload_case_resource(
                client,
                archive_path=archive_path,
                upload_name=upload_name,
            )
            resource_path = str(resource["path"])
            created = _unwrap_response(
                client.post(
                    "/api/v1/flows/",
                    json={
                        "input": _case_prompt(case, resource_path),
                        "provider": config.provider,
                        "resource_ids": [int(resource["id"])],
                    },
                )
            )
            if not isinstance(created, dict) or not str(created.get("id") or "").isdigit():
                raise BenchmarkError("PentAGI flow creation response is missing an ID")
            flow_id = str(created["id"])
            _wait_for_flow(client, flow_id=flow_id, timeout_seconds=timeout_seconds)
        result = export_pentagi_flow(
            config=config,
            flow_id=flow_id,
            case_id=case_id,
            experiment_id=experiment_id,
            state_dir=state_dir,
        )
    except Exception:
        if cleanup and resource_path:
            with _client(config, authenticated=True) as client:
                _cleanup_pentagi_case(
                    client,
                    flow_id=flow_id,
                    resource_path=resource_path,
                    receipt_path=(
                        state_dir
                        / "results"
                        / experiment_id
                        / "round-1"
                        / case_id
                        / "cleanup-receipt.json"
                    ),
                )
        raise
    if cleanup:
        with _client(config, authenticated=True) as client:
            _cleanup_pentagi_case(
                client,
                flow_id=flow_id,
                resource_path=resource_path,
                receipt_path=(
                    state_dir
                    / "results"
                    / experiment_id
                    / "round-1"
                    / case_id
                    / "cleanup-receipt.json"
                ),
            )
    return result


def _record_failed_case(
    *,
    state_dir: Path,
    experiment_id: str,
    case_id: str,
    error: Exception,
) -> dict[str, Any]:
    result_dir = state_dir / "results" / experiment_id / "round-1" / case_id
    result_path = result_dir / "result.json"
    if result_path.is_file():
        return json.loads(result_path.read_text(encoding="utf-8"))
    result_dir.mkdir(parents=True, exist_ok=True)
    result = {
        "schema_version": "1.0",
        "experiment_id": experiment_id,
        "round": 1,
        "case_id": case_id,
        "run_id": None,
        "status": "failed",
        "summary": {
            "target": "pentagi",
            "error_type": type(error).__name__,
            "error_message": str(error),
        },
        "report": {
            "final_answer": "",
            "evidence": [],
            "findings": [],
            "reproduction_steps": [],
        },
        "ledger_chain_valid": False,
        "event_count": 0,
        "usage": {
            "request_count": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
        "official_score": None,
        "score_status": "BASELINE_PENDING_EVALUATION",
        "finished_at": datetime.now(UTC).isoformat(),
    }
    _safe_result_payload(result)
    atomic_write_json(result_path, result)
    atomic_write_json(
        result_dir / "hashes.json",
        {"result.json": sha256_file(result_path)},
    )
    _register_batch_result(
        state_dir=state_dir,
        experiment_id=experiment_id,
        case_id=case_id,
        result_path=result_path,
        result=result,
    )
    return result


def run_pentagi_baseline(
    *,
    config: PentagiConfig,
    selection_path: Path,
    state_dir: Path,
    timeout_seconds: int,
    cleanup: bool,
) -> dict[str, Any]:
    selection = json.loads(selection_path.resolve().read_text(encoding="utf-8"))
    case_ids = [str(item["case_id"]) for item in selection.get("cases", [])]
    if len(case_ids) != 12 or len(set(case_ids)) != 12:
        raise BenchmarkError("PentAGI baseline selection must contain exactly 12 unique cases")
    experiment_id = f"baseline-{selection['selection_id']}-pentagi-{utc_stamp()}"
    outcomes: list[dict[str, Any]] = []
    for case_id in case_ids:
        try:
            result = run_pentagi_case(
                config=config,
                case_id=case_id,
                experiment_id=experiment_id,
                state_dir=state_dir,
                timeout_seconds=timeout_seconds,
                cleanup=cleanup,
            )
            outcomes.append({"case_id": case_id, "status": result["status"]})
        except Exception as error:
            _record_failed_case(
                state_dir=state_dir,
                experiment_id=experiment_id,
                case_id=case_id,
                error=error,
            )
            outcomes.append(
                {
                    "case_id": case_id,
                    "status": "harness_error",
                    "error_type": type(error).__name__,
                    "error_message": str(error),
                }
            )
    return {
        "experiment_id": experiment_id,
        "case_count": len(case_ids),
        "attempted_count": len(outcomes),
        "outcomes": outcomes,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PentAGI adapter for the private benchmark scorer")
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path(__file__).resolve().with_name("pentagi.env"),
    )
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=Path(__file__).resolve().parent / ".state",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("preflight", help="Check PentAGI API, token, and provider")
    export = commands.add_parser(
        "export-flow", help="Normalize one completed PentAGI flow for deterministic scoring"
    )
    export.add_argument("--flow-id", required=True)
    export.add_argument("--case-id", required=True)
    export.add_argument("--experiment-id", required=True)
    run_case = commands.add_parser(
        "run-case", help="Upload one public case, run PentAGI, and normalize its result"
    )
    run_case.add_argument("--case-id", required=True)
    run_case.add_argument("--experiment-id", required=True)
    run_case.add_argument("--timeout-seconds", type=int, default=1800)
    run_case.add_argument("--cleanup", action="store_true")
    baseline = commands.add_parser(
        "baseline", help="Run all 12 selected cases sequentially through PentAGI"
    )
    baseline.add_argument(
        "--selection",
        type=Path,
        default=Path(__file__).resolve().parent / "selections" / "fused-12-v1.json",
    )
    baseline.add_argument("--timeout-seconds", type=int, default=1800)
    baseline.add_argument("--cleanup", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config = load_pentagi_config(args.env_file.resolve())
        if args.command == "preflight":
            result = pentagi_preflight(config)
            atomic_write_json(args.state_dir.resolve() / "pentagi-preflight.json", result)
        elif args.command == "export-flow":
            result = export_pentagi_flow(
                config=config,
                flow_id=args.flow_id,
                case_id=args.case_id,
                experiment_id=args.experiment_id,
                state_dir=args.state_dir.resolve(),
            )
        elif args.command == "run-case":
            result = run_pentagi_case(
                config=config,
                case_id=args.case_id,
                experiment_id=args.experiment_id,
                state_dir=args.state_dir.resolve(),
                timeout_seconds=args.timeout_seconds,
                cleanup=args.cleanup,
            )
        else:
            result = run_pentagi_baseline(
                config=config,
                selection_path=args.selection,
                state_dir=args.state_dir.resolve(),
                timeout_seconds=args.timeout_seconds,
                cleanup=args.cleanup,
            )
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0 if result.get("ready", True) else 1
    except (BenchmarkError, httpx.HTTPError, OSError, ValueError) as error:
        print(f"pentagi adapter error: {type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
