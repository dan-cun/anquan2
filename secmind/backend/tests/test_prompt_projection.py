from __future__ import annotations

import json
from pathlib import Path

from agents.native import _tool_result_observation, project_tool_data
from agents.registry import ROLE_DESCRIPTORS
from agents.tool_catalog import render_tool_catalog
from app.schemas.agents import AgentRole
from app.schemas.runtime import AgentState, CompletionMode, InputArtifact, TaskRequest
from app.schemas.tools import (
    ToolExecutionStatus,
    ToolOrigin,
    UnifiedToolDefinition,
    UnifiedToolResult,
)
from app.services.capabilities import CapabilityRouter
from app.services.collaboration import _deduplicated_findings
from app.services.workspace_context import (
    relevant_workspace_chunks,
    workspace_manifest_projection,
)


def _artifact(path: str, content: str) -> InputArtifact:
    return InputArtifact(
        original_name=Path(path).name,
        relative_path=path,
        sha256=(path.encode("utf-8").hex() + "0" * 64)[:64],
        size_bytes=len(content.encode("utf-8")),
        media_type="text/plain",
    )


def _definition(tool_id: str, *, description: str = "Scan source") -> UnifiedToolDefinition:
    return UnifiedToolDefinition(
        tool_id=tool_id,
        name=tool_id.rpartition(":")[2],
        description=description,
        origin=ToolOrigin.MCP,
        server_id="test-server",
        input_schema={
            "type": "object",
            "properties": {"target": {"type": "string"}},
            "required": ["target"],
        },
        output_schema={
            "type": "object",
            "properties": {"findings": {"type": "array", "items": {"type": "object"}}},
        },
        annotations={
            "risk_level": 1,
            "timeout_seconds": 120,
            "internal_metadata": "x" * 2_000,
        },
    )


def _descriptor(role: AgentRole):
    return next(item for item in ROLE_DESCRIPTORS if item.role == role)


def test_workspace_projection_is_bounded_and_prioritizes_relevant_source(
    tmp_path: Path,
) -> None:
    files = {
        "src/http_parser.py": "def parse_request(data):\n    return data\n" * 50,
        "tests/test_http.py": "def test_request():\n    assert True\n" * 100,
        "docs/security.md": "HTTP request parser notes\n" * 100,
    }
    artifacts = []
    for relative_path, content in files.items():
        target = tmp_path / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        artifacts.append(_artifact(relative_path, content))
    state = AgentState(
        run_id="run-projection",
        workspace=str(tmp_path),
        task=TaskRequest(objective="Audit the HTTP request parser"),
        input_artifacts=artifacts,
    )

    manifest = workspace_manifest_projection(state, max_files=2)
    chunks, failures = relevant_workspace_chunks(
        state,
        max_files=2,
        max_chars_per_file=600,
        max_total_chars=1_000,
    )

    assert manifest["file_count"] == 3
    assert manifest["omitted_file_count"] == 1
    assert manifest["files"][0]["path"] == "src/http_parser.py"
    assert all("content" not in item for item in manifest["files"])
    assert chunks[0]["path"] == "src/http_parser.py"
    assert sum(len(str(item["content"])) for item in chunks) <= 1_000
    assert failures == []


def test_code_audit_selects_a_subset_without_changing_the_88_tool_contract() -> None:
    tool_ids = [
        "native:bandit_python_audit",
        "mcp:local-semgrep:semgrep_scan",
        "mcp:local-web-security:gitleaks_detect",
        "mcp:local-security-extended:trivy_scan",
        "mcp:local-security-extended:osv_scan",
        "native:independent_verify",
        "native:notes.record",
        "native:context.compress",
        "mcp:local-chrome-devtools:click",
        "mcp:local-cyberchef:bake_recipe",
    ]
    tool_ids.extend(f"mcp:unrelated:tool_{index}" for index in range(78))
    assert len(tool_ids) == 88

    plan = CapabilityRouter().route(
        TaskRequest(objective="Audit this Python repository for vulnerabilities"),
        [_artifact("src/main.py", "print('ok')")],
        [{"tool_id": tool_id} for tool_id in tool_ids],
        CompletionMode.FINDINGS,
    )

    assert plan.task_kind == "code_audit"
    assert "native:bandit_python_audit" in plan.allowed_tool_ids
    assert "mcp:local-semgrep:semgrep_scan" in plan.allowed_tool_ids
    assert "native:independent_verify" in plan.allowed_tool_ids
    assert "mcp:local-chrome-devtools:click" not in plan.allowed_tool_ids
    assert "mcp:local-cyberchef:bake_recipe" not in plan.allowed_tool_ids
    assert len(plan.allowed_tool_ids) < len(tool_ids)


def test_compact_tool_catalog_keeps_invocation_contract_and_omits_output_noise() -> None:
    definitions = [
        _definition("mcp:local-semgrep:semgrep_scan", description="S" * 2_000),
        _definition("native:bandit_python_audit", description="B" * 2_000),
    ]

    complete, _ = render_tool_catalog(_descriptor(AgentRole.ASSISTANT), definitions)
    compact, digest = render_tool_catalog(
        _descriptor(AgentRole.ASSISTANT),
        definitions,
        compact=True,
    )
    payload = json.loads(compact.split("\n", 1)[1])

    assert len(digest) == 64
    assert len(compact) < len(complete) / 2
    assert payload["catalog_mode"] == "invocation"
    assert payload["tools"][0]["input_schema"]["required"] == ["target"]
    assert payload["tools"][0]["output_schema"]["type"] == "object"
    assert "internal_metadata" not in payload["tools"][0]["annotations"]
    assert len(payload["tools"][0]["description"]) <= 320


def test_bandit_projection_deduplicates_sorts_and_preserves_full_result() -> None:
    duplicate = {
        "finding_id": "low-1",
        "rule_id": "B101",
        "severity": "LOW",
        "confidence": "HIGH",
        "path": "tests/test_http.py",
        "line": 10,
        "title": "assert_used",
        "description": "Use of assert detected",
        "evidence_ids": ["e-low"],
        "raw": {"code": "assert True", "noise": "x" * 20_000},
    }
    findings = [duplicate, {**duplicate, "finding_id": "low-duplicate"}]
    findings.append(
        {
            "finding_id": "high-1",
            "rule_id": "B602",
            "severity": "HIGH",
            "confidence": "HIGH",
            "path": "src/runner.py",
            "line": 40,
            "title": "subprocess_popen_with_shell_equals_true",
            "description": "shell=True can permit command injection",
            "evidence_ids": ["e-high"],
            "raw": {"code": "subprocess.run(value, shell=True)"},
        }
    )
    findings.extend(
        {
            "finding_id": f"medium-{index}",
            "rule_id": "B608",
            "severity": "MEDIUM",
            "confidence": "MEDIUM",
            "path": f"src/query_{index}.py",
            "line": index + 1,
            "title": "sql_expression",
            "description": "Possible SQL expression",
            "evidence_ids": [f"e-{index}"],
            "raw": {"code": "query = value"},
        }
        for index in range(25)
    )
    full_data = {"findings": findings, "metrics": {"loc": 9_870}}
    result = UnifiedToolResult(
        invocation_id="invocation-1",
        tool_id="native:bandit_python_audit",
        status=ToolExecutionStatus.COMPLETED,
        text="Bandit completed",
        data=full_data,
        evidence_ids=[f"evidence-{index}" for index in range(100)],
    )

    projection = project_tool_data(full_data)
    observation = _tool_result_observation(result)

    assert projection["finding_summary"] == {
        "reported_count": 28,
        "unique_count": 27,
        "included_count": 20,
        "omitted_count": 7,
        "severity_counts": {"HIGH": 1, "LOW": 1, "MEDIUM": 25},
    }
    assert projection["findings"][0]["severity"] == "HIGH"
    assert all("raw" not in item for item in projection["findings"])
    assert len(json.dumps(projection)) < len(json.dumps(full_data)) / 5
    assert len(observation.evidence_ids) == 64
    assert observation.metadata["evidence_id_count"] == 100
    assert result.data == full_data


def test_collaboration_finding_projection_is_deduplicated_and_severity_sorted() -> None:
    findings = [
        {
            "finding_id": "low-1",
            "rule_id": "B101",
            "severity": "LOW",
            "path": "tests/test_a.py",
            "line": 3,
            "title": "assert_used",
        },
        {
            "finding_id": "high-1",
            "rule_id": "B602",
            "severity": "HIGH",
            "path": "src/run.py",
            "line": 8,
            "title": "shell_true",
        },
        {
            "finding_id": "low-2",
            "rule_id": "B101",
            "severity": "LOW",
            "path": "tests/test_a.py",
            "line": 3,
            "title": "assert_used",
        },
    ]

    projected = _deduplicated_findings(findings)

    assert [item["finding_id"] for item in projected] == ["high-1", "low-1"]
