from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.collect_provenance import (
    ProvenanceError,
    _public_env,
    _tool_provenance,
    canonical_sha256,
)


def test_canonical_sha256_is_order_independent_for_object_keys() -> None:
    assert canonical_sha256({"b": 2, "a": 1}) == canonical_sha256({"a": 1, "b": 2})


def test_public_model_config_rejects_secret_fields(tmp_path: Path) -> None:
    path = tmp_path / "model.env"
    path.write_text("SECMIND_LLM_API_KEY=not-public\n", encoding="utf-8")

    with pytest.raises(ProvenanceError, match="Secret-like field"):
        _public_env(path)


def test_tool_provenance_hashes_sorted_public_definitions() -> None:
    first = {
        "tool_id": "native:a",
        "name": "a",
        "origin": "native",
        "schema_version": "1.0",
        "annotations": {},
    }
    second = {
        "tool_id": "mcp:local:b",
        "name": "b",
        "origin": "mcp",
        "schema_version": "2.0",
        "annotations": {"version": "2.1"},
    }

    forward = _tool_provenance([first, second])
    reverse = _tool_provenance([second, first])

    assert forward == reverse
    assert forward["count"] == 2
    assert forward["versions"] == [
        {"tool_id": "mcp:local:b", "version": "2.1"},
        {"tool_id": "native:a", "version": "1.0"},
    ]
    json.dumps(forward)
