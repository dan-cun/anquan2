from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmark.harness import BenchmarkError
from benchmark.pentagi_adapter import (
    _record_failed_case,
    _register_batch_result,
    extract_structured_report,
    load_pentagi_config,
)


def test_load_pentagi_config_does_not_require_token(tmp_path: Path) -> None:
    env_file = tmp_path / "pentagi.env"
    env_file.write_text(
        "PENTAGI_BASE_URL=https://127.0.0.1:8443\n"
        "PENTAGI_PROVIDER=deepseek\n"
        "PENTAGI_TLS_VERIFY=false\n",
        encoding="utf-8",
    )
    config = load_pentagi_config(env_file)
    assert config.base_url == "https://127.0.0.1:8443"
    assert config.provider == "deepseek"
    assert config.api_token is None
    assert config.tls_verify is False


def test_extract_structured_report_requires_full_json_result() -> None:
    report, task_id = extract_structured_report(
        [
            {
                "id": 1,
                "status": "finished",
                "updated_at": "2026-07-21T00:00:00Z",
                "result": json.dumps(
                    {
                        "final_answer": "HTB{verified}",
                        "evidence": [{"kind": "command", "ref": "artifact-1"}],
                        "findings": [],
                        "reproduction_steps": ["Run the verifier"],
                    }
                ),
            }
        ]
    )
    assert task_id == "1"
    assert report["final_answer"] == "HTB{verified}"
    assert report["source_task_id"] == "1"


def test_extract_structured_report_does_not_search_free_text_for_flag() -> None:
    with pytest.raises(BenchmarkError):
        extract_structured_report(
            [
                {
                    "id": 1,
                    "status": "finished",
                    "result": "I found HTB{not-structured} in the logs.",
                }
            ]
        )


def test_extract_structured_report_rejects_non_list_evidence() -> None:
    with pytest.raises(BenchmarkError):
        extract_structured_report(
            [
                {
                    "id": 1,
                    "status": "finished",
                    "result": json.dumps(
                        {"final_answer": "HTB{verified}", "evidence": "claimed"}
                    ),
                }
            ]
        )


def test_register_batch_result_creates_batch_and_rejects_duplicates(tmp_path: Path) -> None:
    result = {
        "status": "completed",
        "usage": {"total_tokens": 10},
        "event_count": 0,
        "ledger_chain_valid": False,
    }
    result_path = tmp_path / "results" / "exp-1" / "round-1" / "CY-WEB-01" / "result.json"
    _register_batch_result(
        state_dir=tmp_path,
        experiment_id="exp-1",
        case_id="CY-WEB-01",
        result_path=result_path,
        result=result,
    )
    batch_path = tmp_path / "results" / "exp-1" / "batch-summary.json"
    batch = json.loads(batch_path.read_text(encoding="utf-8"))
    assert batch["run_mode"] == "PENTAGI_BASELINE"
    assert batch["completed_count"] == 1
    assert batch["results"][0]["case_id"] == "CY-WEB-01"
    with pytest.raises(BenchmarkError):
        _register_batch_result(
            state_dir=tmp_path,
            experiment_id="exp-1",
            case_id="CY-WEB-01",
            result_path=result_path,
            result=result,
        )


def test_failed_case_is_registered_in_the_denominator(tmp_path: Path) -> None:
    result = _record_failed_case(
        state_dir=tmp_path,
        experiment_id="exp-2",
        case_id="NYU-WEB-02",
        error=TimeoutError("case timed out"),
    )
    assert result["status"] == "failed"
    assert result["report"]["final_answer"] == ""
    batch = json.loads(
        (tmp_path / "results" / "exp-2" / "batch-summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert batch["completed_count"] == 1
    assert batch["results"][0]["case_id"] == "NYU-WEB-02"
