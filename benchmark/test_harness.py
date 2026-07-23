from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from benchmark.harness import (
    BenchmarkError,
    _benchmark_cleanup_script,
    _cleanup_sql,
    _directory_digest,
    _exact_answer_matches,
    _private_case_directory,
    _safe_member_path,
    _safe_result_payload,
    _token_usage,
    _validate_upload_ref,
    canonical_sha256,
    load_runtime_contract,
    local_version_summaries,
    ordered_json_sha256,
    render_evaluation_markdown,
    render_report_file,
    runtime_contract_checks,
    score_benchmark_java,
    tool_catalog_summary,
    write_evaluation_exports,
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


def test_exact_answer_match_requires_the_structured_final_answer() -> None:
    assert _exact_answer_matches("HTB{known-answer}", "HTB{known-answer}")
    assert not _exact_answer_matches("The answer is HTB{known-answer}", "HTB{known-answer}")
    assert not _exact_answer_matches("HTB{known-answer}", "short")


def test_private_case_directory_requires_private_public_layout(tmp_path: Path) -> None:
    (tmp_path / "题目集_Agent可见").mkdir()
    case = tmp_path / "评测端_禁止提供给Agent" / "01_Web安全" / "CY-WEB-01"
    case.mkdir(parents=True)
    assert _private_case_directory(tmp_path, "CY-WEB-01") == case.resolve()
    with pytest.raises(BenchmarkError):
        _private_case_directory(tmp_path, "CY-WEB-02")


def test_cleanup_sql_is_run_scoped_and_preserves_configuration() -> None:
    run_id = "019f7b3b-c509-45a1-8d4f-f3a9f61969ea"
    sql = _cleanup_sql(run_id)
    assert f"WHERE run_id = '{run_id}'" in sql
    for table in ("prompts", "prompt_versions", "mcp_servers", "mcp_capabilities", "skills"):
        assert f"'{table}'" not in sql


def test_benchmark_cleanup_targets_isolated_sqlite_and_preserves_configuration() -> None:
    script = _benchmark_cleanup_script()

    assert "/app/data/benchmark.db" in script
    assert "import sqlite3" in script
    assert "PRAGMA foreign_key_check" in script
    for table in ("prompts", "prompt_versions", "mcp_servers", "mcp_capabilities", "skills"):
        assert f'"{table}"' not in script


def test_benchmark_cleanup_removes_flow_graph_with_self_referencing_agents(
    tmp_path: Path,
) -> None:
    database = tmp_path / "benchmark.db"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE flows (id TEXT PRIMARY KEY);
        CREATE TABLE tasks (
            id TEXT PRIMARY KEY,
            flow_id TEXT NOT NULL REFERENCES flows(id) ON DELETE RESTRICT
        );
        CREATE TABLE agent_instances (
            instance_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            flow_id TEXT NOT NULL REFERENCES flows(id) ON DELETE RESTRICT,
            task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE RESTRICT,
            parent_instance_id TEXT REFERENCES agent_instances(instance_id) ON DELETE RESTRICT
        );
        CREATE TABLE message_chains (
            chain_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            flow_id TEXT NOT NULL REFERENCES flows(id) ON DELETE RESTRICT,
            task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE RESTRICT,
            agent_instance_id TEXT REFERENCES agent_instances(instance_id) ON DELETE RESTRICT
        );
        CREATE TABLE message_entries (
            entry_id TEXT PRIMARY KEY,
            chain_id TEXT NOT NULL REFERENCES message_chains(chain_id) ON DELETE RESTRICT
        );
        CREATE TABLE runtime_runs (
            run_id TEXT PRIMARY KEY,
            state_json TEXT NOT NULL
        );
        CREATE TABLE prompts (prompt_key TEXT PRIMARY KEY);
        INSERT INTO flows VALUES ('flow-1');
        INSERT INTO tasks VALUES ('task-1', 'flow-1');
        INSERT INTO agent_instances VALUES
            ('agent-parent', 'run-1', 'flow-1', 'task-1', NULL),
            ('agent-child', 'run-1', 'flow-1', 'task-1', 'agent-parent');
        INSERT INTO message_chains VALUES
            ('chain-1', 'run-1', 'flow-1', 'task-1', 'agent-child');
        INSERT INTO message_entries VALUES ('entry-1', 'chain-1');
        INSERT INTO runtime_runs VALUES
            ('run-1', '{"flow_id":"flow-1","task_id":"task-1"}');
        INSERT INTO prompts VALUES ('global-prompt');
        """
    )
    connection.close()

    runs_root = tmp_path / "runs"
    uploads_root = tmp_path / "uploads"
    (runs_root / "run-1").mkdir(parents=True)
    uploads_root.mkdir()
    (uploads_root / "upload.zip").write_bytes(b"input")

    subprocess.run(
        [
            sys.executable,
            "-c",
            _benchmark_cleanup_script(),
            "run-1",
            "upload.zip",
            str(database),
            str(runs_root),
            str(uploads_root),
        ],
        check=True,
    )

    connection = sqlite3.connect(database)
    for table in (
        "runtime_runs",
        "message_entries",
        "message_chains",
        "agent_instances",
        "tasks",
        "flows",
    ):
        assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    assert connection.execute("SELECT prompt_key FROM prompts").fetchone() == (
        "global-prompt",
    )
    assert list(connection.execute("PRAGMA foreign_key_check")) == []
    connection.close()
    assert not (runs_root / "run-1").exists()
    assert not (uploads_root / "upload.zip").exists()


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


def test_version_summaries_exclude_secrets_and_hash_public_config(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "prompt.xlsx").write_bytes(b"prompt-version")
    (tmp_path / "config" / "model.env").write_text(
        "SECMIND_LLM_MODEL=worker\nSECMIND_LLM_PROVIDER=test\n",
        encoding="utf-8",
    )
    (tmp_path / "config" / "mcp.json").write_text(
        '{\n  "servers": [{"server_id": "local"}]\n}\n',
        encoding="utf-8",
    )
    contract = {
        "version_sources": {
            "prompt": {"version": "p1", "path": "prompt.xlsx"},
            "model": {"version": "m1", "path": "config/model.env"},
            "mcp": {"version": "t1", "path": "config/mcp.json"},
        }
    }

    summaries = local_version_summaries(tmp_path, contract)

    expected_config = {
        "SECMIND_LLM_MODEL": "worker",
        "SECMIND_LLM_PROVIDER": "test",
    }
    assert summaries["model"]["config"] == expected_config
    assert summaries["model"]["sha256"] == canonical_sha256(expected_config)
    assert summaries["model"]["config_sha256"] == canonical_sha256(expected_config)
    assert summaries["mcp"]["sha256"] == ordered_json_sha256(
        {"servers": [{"server_id": "local"}]}
    )

    (tmp_path / "config" / "model.env").write_text(
        "SECMIND_LLM_API_KEY=must-not-be-public\n",
        encoding="utf-8",
    )
    with pytest.raises(BenchmarkError, match="Sensitive setting"):
        local_version_summaries(tmp_path, contract)


def test_runtime_contract_checks_all_provenance_dimensions() -> None:
    tools = [
        {"tool_id": "native:one", "name": "one", "origin": "native"},
        {
            "tool_id": "mcp:server:two",
            "name": "two",
            "origin": "mcp",
            "server_id": "server",
            "input_schema": {"type": "object"},
        },
    ]
    catalog = tool_catalog_summary(tools)
    versions = {"prompt": {"version": "p1", "sha256": "abc"}}
    contract = {
        "expected_mcp_server_ids": ["server"],
        "expected_tool_count": 2,
        "expected_native_tool_count": 1,
        "expected_mcp_tool_count": 1,
    }
    deployment = {
        "source_commit": "commit-1",
        "image": {"digest": "sha256:image-1"},
        "versions": versions,
    }

    checks = runtime_contract_checks(
        contract=contract,
        deployment=deployment,
        versions=versions,
        catalog=catalog,
        actual_server_ids=["server"],
        connected_server_ids=["server"],
        runtime_commit="commit-1",
        runtime_image_digest="sha256:image-1",
        git_head="commit-1",
        git_dirty=False,
    )

    assert all(checks.values())
    mismatched = runtime_contract_checks(
        contract=contract,
        deployment=deployment,
        versions=versions,
        catalog={**catalog, "count": 3},
        actual_server_ids=["wrong-server"],
        connected_server_ids=[],
        runtime_commit="wrong-commit",
        runtime_image_digest="sha256:wrong-image",
        git_head="commit-1",
        git_dirty=True,
    )
    assert not mismatched["server_ids_match"]
    assert not mismatched["all_expected_servers_connected"]
    assert not mismatched["tool_count_matches"]
    assert not mismatched["source_commit_matches"]
    assert not mismatched["image_digest_matches"]
    assert not mismatched["source_worktree_clean"]


def test_repository_runtime_contract_declares_reliable_kernel() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    kernel = load_runtime_contract(repo_root)["reliable_kernel"]

    assert kernel["state_owner"] == "runtime_ledger"
    assert kernel["graph_checkpoint_fields"] == [
        "run_id",
        "flow_id",
        "state_revision",
        "confirmation",
        "route",
        "denied",
    ]
    assert kernel["model_max_attempts_env"] == "SECMIND_LLM_MAX_ATTEMPTS"
    assert kernel["default_model_max_attempts"] == 2
    assert kernel["tool_retry_policy"] == "idempotent_only"
    assert kernel["completion_gate_checks"] == [
        "review_converged",
        "evidence_closure",
        "task_contract",
    ]


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


def test_evaluation_exports_include_coverage_and_manual_review(tmp_path: Path) -> None:
    evaluation = {
        "experiment_id": "baseline-fused-12-test",
        "report_status": "READY_WITH_MANUAL_REVIEW",
        "expected_case_count": 2,
        "scored_case_count": 2,
        "raw_score_rate": 0.575,
        "fully_automated": False,
        "missing_case_ids": [],
        "duplicate_case_ids": [],
        "unexpected_case_ids": [],
        "manual_review_cases": ["BB-02"],
        "category_score_rates": {"Web安全": 1.0, "真实仓库漏洞": 0.15},
        "scores": [
            {
                "case_id": "CY-WEB-01",
                "category": "Web安全",
                "runtime_status": "completed",
                "evaluator": "cybench_final_answer_exact_match",
                "score_status": "AUTOMATED_EXACT_MATCH",
                "automated": True,
                "goal_met": True,
                "evidence_count": 1,
                "finding_count": 1,
                "score": 100,
                "false_completion": False,
            },
            {
                "case_id": "BB-02",
                "category": "真实仓库漏洞",
                "runtime_status": "partial",
                "evaluator": "manual_no_verified_evidence",
                "score_status": "MANUAL_REVIEW_REQUIRED",
                "automated": False,
                "goal_met": False,
                "evidence_count": 0,
                "finding_count": 0,
                "score": 15,
                "false_completion": False,
            },
        ],
    }

    report = render_evaluation_markdown(evaluation)
    assert "题目覆盖：2/2" in report
    assert "BB-02" in report
    assert "57.50%" in report

    write_evaluation_exports(tmp_path, evaluation)
    assert len((tmp_path / "task-scores.jsonl").read_text(encoding="utf-8").splitlines()) == 2
    assert "score_status" in (tmp_path / "task-scores.csv").read_text(encoding="utf-8")
    assert (tmp_path / "report.md").read_text(encoding="utf-8") == report

    evaluation_path = tmp_path / "evaluation.json"
    evaluation_path.write_text(json.dumps(evaluation, ensure_ascii=False), encoding="utf-8")
    rendered_path = tmp_path / "rendered.md"
    result = render_report_file(evaluation_path, rendered_path)
    assert result["report_status"] == "READY_WITH_MANUAL_REVIEW"
    assert rendered_path.read_text(encoding="utf-8") == report
