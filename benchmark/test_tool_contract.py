from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

import pytest

from scripts.audit_mcp_contract import ContractAuditError, validate_audit


def test_repository_declares_exact_7_10_78_88_contract() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    contract = json.loads(
        (repo_root / "config" / "runtime-contract.json").read_text(encoding="utf-8")
    )
    config = json.loads((repo_root / "config" / "mcp-servers.json").read_text(encoding="utf-8"))

    server_ids = contract["expected_mcp_server_ids"]
    per_server = contract["expected_mcp_tool_counts"]
    native_ids = contract["expected_native_tool_ids"]
    configured = [item for item in config["servers"] if item.get("enabled", True)]

    assert len(server_ids) == len(set(server_ids)) == 7
    assert set(per_server) == set(server_ids)
    assert sum(per_server.values()) == contract["expected_mcp_tool_count"] == 78
    assert len(native_ids) == len(set(native_ids)) == contract["expected_native_tool_count"] == 10
    assert all(tool_id.startswith("native:") for tool_id in native_ids)
    assert 10 + 78 == contract["expected_tool_count"] == 88
    assert {item["server_id"] for item in configured} == set(server_ids)
    assert {urlparse(item["url"]).port for item in configured} == set(range(9011, 9018))
    assert len(contract["expected_mcp_tool_definitions_sha256"]) == 64


def test_contract_validation_rejects_duplicate_tool_ids() -> None:
    tool = {
        "tool_id": "mcp:server:one",
        "server_id": "server",
        "name": "one",
        "description": "",
        "server_version": "1.0",
        "declared_version": "unavailable",
        "version_source": "not_declared_by_mcp_tool",
        "input_schema": {},
        "output_schema": {},
        "annotations": {},
        "schema_sha256": "schema",
    }
    contract = {
        "expected_tool_count": 3,
        "expected_native_tool_count": 1,
        "expected_mcp_tool_count": 2,
    }
    servers = [{"tools": [tool, tool]}]

    with pytest.raises(ContractAuditError, match="Duplicate MCP Tool IDs"):
        validate_audit(contract, servers)


def test_contract_validation_rejects_invalid_arithmetic() -> None:
    contract = {
        "expected_tool_count": 88,
        "expected_native_tool_count": 10,
        "expected_mcp_tool_count": 77,
    }

    with pytest.raises(ContractAuditError, match="Invalid contract arithmetic"):
        validate_audit(contract, [])
