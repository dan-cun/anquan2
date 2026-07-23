from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from benchmark.pentagi_docx_report import ReportError, load_report_data


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _evaluation(root: Path, *, target: str | None) -> Path:
    evaluation = root / "evaluation.json"
    _write_json(
        evaluation,
        {
            "scores": [
                {
                    "case_id": "CY-WEB-01",
                    "category": "Web安全",
                    "runtime_status": "completed",
                    "score": 80,
                    "max_score": 100,
                }
            ],
            "equal_weight_category_score": 0.8,
        },
    )
    _write_json(
        root / "round-1" / "CY-WEB-01" / "result.json",
        {
            "status": "completed",
            "summary": {"target": target} if target else {},
            "report": {
                "final_answer": "verified",
                "evidence": [{"id": "ev-1"}],
                "findings": [],
            },
            "ledger_chain_valid": False,
            "usage": {"request_count": 2, "total_tokens": 1234},
        },
    )
    _write_json(
        root / "round-1" / "CY-WEB-01" / "environment.json",
        {"target": target, "provider": "deepseek", "model": "deepseek-v4-flash"},
    )
    return evaluation


class PentagiDocxReportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_pentagi_target_is_accepted(self) -> None:
        data = load_report_data(_evaluation(self.root, target="pentagi"))
        self.assertFalse(data.preview)
        self.assertEqual(data.observed_targets, {"pentagi"})
        self.assertEqual(data.final_answer_count, 1)
        self.assertEqual(data.evidence_count, 1)
        self.assertEqual(data.total_tokens, 1234)

    def test_non_pentagi_target_is_rejected(self) -> None:
        evaluation = _evaluation(self.root, target="secmind")
        with self.assertRaisesRegex(ReportError, "Refusing to label"):
            load_report_data(evaluation)

    def test_unlabeled_data_requires_preview(self) -> None:
        evaluation = _evaluation(self.root, target=None)
        with self.assertRaisesRegex(ReportError, "unlabeled"):
            load_report_data(evaluation)
        self.assertTrue(load_report_data(evaluation, preview=True).preview)


if __name__ == "__main__":
    unittest.main()
