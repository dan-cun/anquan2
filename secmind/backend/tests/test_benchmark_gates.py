from __future__ import annotations

import pytest

from benchmark_gates import checkpoint_gate


def test_checkpoint_gate_completes_one_hundred_serialization_roundtrips() -> None:
    result = checkpoint_gate(100)

    assert result["gate"] == "agent_checkpoint_roundtrip"
    assert result["iterations"] == 100
    assert result["serialization_errors"] == 0
    assert result["passed"] is True
    assert len(result["sha256"]) == 64


def test_checkpoint_gate_rejects_non_positive_iterations() -> None:
    with pytest.raises(ValueError, match="positive"):
        checkpoint_gate(0)
