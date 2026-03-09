from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from automation_intel_mcp.services.budget import BudgetTracker


class BudgetTrackerTests(unittest.TestCase):
    def test_record_actual_cost(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tracker = BudgetTracker(Path(tmp_dir), soft_limit_usd=1.0, hard_limit_usd=2.0)
            record = tracker.record(
                "perplexity",
                "quick_search",
                actual_cost_usd=0.12,
                metadata={"query": "test"},
            )
            self.assertEqual(record["provider"], "perplexity")
            self.assertEqual(record["operation"], "quick_search")
            self.assertEqual(record["cost_source"], "actual")
            self.assertAlmostEqual(record["billed_cost_usd"], 0.12)
            self.assertAlmostEqual(tracker.current_month_total(), 0.12)

    def test_record_estimated_cost_when_actual_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tracker = BudgetTracker(Path(tmp_dir), soft_limit_usd=0.005, hard_limit_usd=1.0)
            record = tracker.record(
                "perplexity",
                "raw_search",
                estimated_cost_usd=0.005,
                metadata={"query": "fallback"},
            )
            self.assertEqual(record["cost_source"], "estimated")
            self.assertAlmostEqual(record["estimated_cost_usd"], 0.005)
            self.assertTrue(record["soft_limit_reached"])
            payload = json.loads((Path(tmp_dir) / "usage_costs.jsonl").read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(payload["provider"], "perplexity")
            self.assertEqual(payload["operation"], "raw_search")
            self.assertAlmostEqual(payload["billed_cost_usd"], 0.005)

    def test_record_requires_cost_information(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tracker = BudgetTracker(Path(tmp_dir), soft_limit_usd=1.0, hard_limit_usd=2.0)
            with self.assertRaises(ValueError):
                tracker.record("perplexity", "invalid")


if __name__ == "__main__":
    unittest.main()
