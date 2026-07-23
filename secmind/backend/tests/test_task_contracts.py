from app.schemas.runtime import CompletionMode, TaskRequest
from app.services.task_contracts import resolve_task_contract


def test_cybench_metadata_generates_exact_answer_contract() -> None:
    task = TaskRequest(
        objective="Solve the challenge and return the final flag",
        metadata={"case_id": "CY-WEB-01", "source": "CyBench"},
    )

    contract = resolve_task_contract(task)

    assert contract.completion_mode == CompletionMode.FINAL_ANSWER
    assert contract.expected_outputs == ["final_answer", "evidence", "reproduction_steps"]
    assert contract.evaluator == "cybench_final_answer_exact_match"
    assert contract.required_evidence == ["final_answer", "independent_verification"]
    assert len(contract.contract_sha256) == 64


def test_finding_task_generates_evidence_backed_contract() -> None:
    contract = resolve_task_contract(TaskRequest(objective="Audit this Python service"))

    assert contract.completion_mode == CompletionMode.FINDINGS
    assert contract.expected_outputs == ["security_report", "findings", "evidence"]
    assert contract.evaluator == "evidence_backed_findings"
    assert contract.required_evidence == [
        "verified_finding",
        "evidence_reference",
        "independent_review",
    ]


def test_explicit_contract_fields_override_inference() -> None:
    contract = resolve_task_contract(
        TaskRequest(
            objective="Inspect the supplied target",
            expected_outputs=["final_answer"],
            completion_mode=CompletionMode.FINAL_ANSWER,
            evaluator="final_answer_independent_verification",
            required_evidence=["final_answer", "independent_verification", "artifact"],
        )
    )

    assert contract.completion_mode == CompletionMode.FINAL_ANSWER
    assert contract.expected_outputs == ["final_answer"]
    assert contract.evaluator == "final_answer_independent_verification"
    assert contract.required_evidence[-1] == "artifact"
