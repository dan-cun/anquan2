from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmark.harness import (
    BenchmarkError,
    _cleanup_sql,
    _directory_digest,
    _safe_member_path,
    _safe_result_payload,
    _token_usage,
    _validate_upload_ref,
    score_benchmark_java,
)


def test_safe_member_path_rejects_traversal() -> None:
    with pytest.raises(BenchmarkError):
        _safe_member_path("../../private/answer.json")


def test_directory_digest_is_stable(tmp_path: Path) -> None:
    root = tmp_path / "case"
    root.mkdir()
    (root / "b.py").write_text("print('b')\n", encoding="utf-8")
    (root / "a.py").write_text("print('a')\n", encoding="utf-8")
    first = _directory_digest(root)
    second = _directory_digest(root)
    assert first == second
    assert first[1:] == (2, 24)


def test_upload_ref_requires_uuid_prefixed_single_component() -> None:
    _validate_upload_ref("019f7b3b-c509-45a1-8d4f-f3a9f61969ea-BB-01.zip")
    with pytest.raises(BenchmarkError):
        _validate_upload_ref("../BB-01.zip")
    with pytest.raises(BenchmarkError):
        _validate_upload_ref("BB-01.zip")


def test_result_secret_scan_accepts_metadata_and_rejects_credentials() -> None:
    _safe_result_payload({"provider": "deepseek", "configured": True})
    _safe_result_payload({"finding": "possible password = 'demo' in public source"})
    with pytest.raises(BenchmarkError):
        _safe_result_payload({"authorization": "Bearer test-secret-value"})


def test_cleanup_sql_is_run_scoped_and_preserves_configuration() -> None:
    run_id = "019f7b3b-c509-45a1-8d4f-f3a9f61969ea"
    sql = _cleanup_sql(run_id)
    assert f"WHERE run_id = '{run_id}'" in sql
    for table in ("prompts", "prompt_versions", "mcp_servers", "mcp_capabilities", "skills"):
        assert f"'{table}'" not in sql


def test_token_usage_accepts_openai_aliases() -> None:
    events = [
        {
            "event_type": "llm.response",
            "payload": {"raw": {"usage": {"input_tokens": 10, "output_tokens": 4}}},
        }
    ]
    assert _token_usage(events) == {
        "request_count": 1,
        "prompt_tokens": 10,
        "completion_tokens": 4,
        "total_tokens": 14,
    }


def test_exact_cwe_scoring(tmp_path: Path) -> None:
    expected = tmp_path / "expected.csv"
    expected.write_text(
        "# test name, category, real vulnerability, cwe\n"
        "BenchmarkTest00001,sqli,true,89\n"
        "BenchmarkTest00002,sqli,false,89\n",
        encoding="utf-8",
    )
    predictions = tmp_path / "predictions.jsonl"
    predictions.write_text(
        json.dumps({"case_id": "BenchmarkTest00001", "cwe_ids": [89]})
        + "\n"
        + json.dumps({"case_id": "BenchmarkTest00002", "cwe_ids": []})
        + "\n",
        encoding="utf-8",
    )
    result = score_benchmark_java(expected, predictions)
    assert result["coverage"] == 1.0
    assert result["exact_cwe_f1"] == 1.0
