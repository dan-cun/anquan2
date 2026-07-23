from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.schemas.runtime import UniversalPrimaryResult


def _parse_fenced_json(content: str) -> dict[str, object]:
    cleaned = content.strip()
    assert cleaned.startswith("```json\n")
    assert cleaned.endswith("\n```")
    value = json.loads(cleaned[8:-4])
    assert isinstance(value, dict)
    return value


def test_primary_fenced_json_matches_the_runtime_schema() -> None:
    payload = _parse_fenced_json(
        "```json\n"
        '{"status":"success","executive_summary":"ok",'
        '"findings":[],"evidence_gaps":[],"limitations":[]}'
        "\n```"
    )
    result = UniversalPrimaryResult.model_validate(payload)
    assert result.status == "success"
    assert result.findings == []


def test_primary_wrong_schema_remains_strict() -> None:
    payload = json.loads('{"status":"success","findings":[]}')
    with pytest.raises(ValidationError):
        UniversalPrimaryResult.model_validate(payload)


def test_primary_missing_required_contract_fields_is_diagnosable() -> None:
    payload = json.loads('{"status":"success"}')
    with pytest.raises(ValidationError, match="executive_summary"):
        UniversalPrimaryResult.model_validate(payload)
