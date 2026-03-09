from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from automation_intel_mcp.config import Settings
from automation_intel_mcp.graphs.research_graph import build_research_graph
from automation_intel_mcp.services.budget import BudgetTracker
from automation_intel_mcp.services.research_gateway import ResearchGateway


class _RecordingClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def raw_search(self, query: str, *, max_results: int | None = None) -> dict:
        self.calls.append(query)
        return {
            "cached": False,
            "results": [
                {
                    "title": f"Source for {query}",
                    "url": f"https://example.com/{abs(hash(query))}",
                    "snippet": f"Snippet for {query}",
                }
            ],
            "usage": {
                "provider": "perplexity",
                "operation": "raw_search",
                "billed_cost_usd": 0.005,
                "estimated_cost_usd": 0.005,
                "cost_source": "estimated",
                "month_total_usd": round(len(self.calls) * 0.005, 3),
            },
        }


class ResearchGatewayTests(unittest.TestCase):
    def test_agency_gateway_clamps_deep_to_standard_and_executes_business_queries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            client = _RecordingClient()
            settings = Settings(CACHE_DIR=tmp_dir, AGENCY_EXTERNAL_RESEARCH_MAX_MODE="standard")
            budget = BudgetTracker(Path(tmp_dir), soft_limit_usd=1.0, hard_limit_usd=2.0)
            graph = build_research_graph(client, settings, budget)
            gateway = ResearchGateway(graph, settings)

            result = gateway.research_company("Acme", "clinica", mode="deep")

        self.assertEqual(result.mode_requested, "standard")
        self.assertLessEqual(len(result.subqueries), 8)
        self.assertTrue(any("commercial implications of:" in query for query in result.subqueries))
        self.assertTrue(any("commercial implications of:" in query for query in client.calls))
        self.assertTrue(any("Company: Acme" in query for query in result.subqueries))

    def test_agency_gateway_defaults_to_auto_and_preserves_generic_queries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            client = _RecordingClient()
            settings = Settings(CACHE_DIR=tmp_dir)
            budget = BudgetTracker(Path(tmp_dir), soft_limit_usd=1.0, hard_limit_usd=2.0)
            graph = build_research_graph(client, settings, budget)
            gateway = ResearchGateway(graph, settings)

            result = gateway.research_company("Acme", "clinica")

        self.assertEqual(result.mode_requested, "auto")
        self.assertTrue(any(query.startswith("main evidence and sources for:") for query in result.subqueries))
        self.assertTrue(any("commercial implications of:" in query for query in result.subqueries))


if __name__ == "__main__":
    unittest.main()
