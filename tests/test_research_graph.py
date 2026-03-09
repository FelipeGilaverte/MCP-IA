from __future__ import annotations

import inspect
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from automation_intel_mcp.config import Settings
from automation_intel_mcp.graphs import research_graph as research_graph_module
from automation_intel_mcp.graphs.research_graph import _build_query_plan, _merge_query_plan, build_research_graph
from automation_intel_mcp.services.agency_research_templates import build_agency_business_queries
from automation_intel_mcp.services.budget import BudgetTracker


class StrongEvidenceClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def raw_search(self, query: str, *, max_results: int | None = None) -> dict:
        self.calls.append(query)
        root = abs(hash(query))
        return {
            "cached": False,
            "results": [
                {
                    "title": f"Source {len(self.calls)}A",
                    "url": f"https://a{len(self.calls)}.example.com/{root}",
                    "snippet": f"Unique snippet A for {query}",
                },
                {
                    "title": f"Source {len(self.calls)}B",
                    "url": f"https://b{len(self.calls)}.example.com/{root}",
                    "snippet": f"Unique snippet B for {query}",
                },
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


class WeakEvidenceClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def raw_search(self, query: str, *, max_results: int | None = None) -> dict:
        self.calls.append(query)
        return {
            "cached": False,
            "results": [
                {
                    "title": "Repeated source",
                    "url": "https://repeat.example.com/1",
                    "snippet": "Repeated snippet about the same topic.",
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


class ResearchGraphTests(unittest.TestCase):
    def _graph(self, tmp_dir: str, client) -> object:
        settings = Settings(CACHE_DIR=tmp_dir)
        budget = BudgetTracker(Path(tmp_dir), soft_limit_usd=1.0, hard_limit_usd=2.0)
        return build_research_graph(client, settings, budget)

    def test_query_plan_is_domain_neutral(self) -> None:
        plan = _build_query_plan("battery chemistry", "factual", 20)
        self.assertIn("main evidence and sources for: battery chemistry", plan)
        self.assertIn("alternative viewpoints on: battery chemistry", plan)
        self.assertNotIn("commercial implications of: battery chemistry", plan)
        self.assertNotIn("buyer concerns and objections for: battery chemistry", plan)
        self.assertNotIn("pricing and packaging signals for: battery chemistry", plan)
        self.assertNotIn("market demand indicators for: battery chemistry", plan)

    def test_business_templates_are_not_defined_in_generic_research_core(self) -> None:
        source = inspect.getsource(research_graph_module)
        self.assertNotIn("commercial implications of:", source)
        self.assertNotIn("buyer concerns and objections for:", source)
        self.assertNotIn("pricing and packaging signals for:", source)
        self.assertNotIn("market demand indicators for:", source)

    def test_merge_query_plan_reserves_slots_for_agency_queries(self) -> None:
        base_plan = _build_query_plan("clinic software", "factual", 4)
        extras = build_agency_business_queries("clinic software", max_queries=3)
        merged = _merge_query_plan(base_plan, extras, max_queries=4)
        self.assertEqual(len(merged), 4)
        self.assertTrue(any(query in merged for query in extras))
        self.assertTrue(any(query in merged for query in base_plan))

    def test_graph_executes_agency_queries_when_extra_subqueries_are_provided(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            client = StrongEvidenceClient()
            graph = self._graph(tmp_dir, client)
            extras = build_agency_business_queries("clinic software", max_queries=3)
            result = graph.invoke(
                {
                    "question": "clinic software",
                    "mode": "quick",
                    "max_searches": 4,
                    "extra_subqueries": extras,
                }
            )["result"]
        self.assertEqual(len(result["subqueries"]), 4)
        self.assertTrue(any(query in result["subqueries"] for query in extras))
        self.assertTrue(any(query in client.calls for query in extras))
        self.assertEqual(client.calls, result["subqueries"][: len(client.calls)])

    def test_auto_is_default_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            client = StrongEvidenceClient()
            graph = self._graph(tmp_dir, client)
            result = graph.invoke({"question": "compare clinic CRMs"})["result"]
        self.assertEqual(result["mode_requested"], "auto")
        self.assertIn(result["mode_used"], {"quick", "standard"})
        self.assertEqual(result["search_strategy"].split(":")[0], "adaptive_auto")
        self.assertGreaterEqual(result["search_calls"], 3)
        self.assertLessEqual(result["search_calls"], 8)

    def test_auto_stops_early_when_evidence_is_good(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            client = StrongEvidenceClient()
            graph = self._graph(tmp_dir, client)
            result = graph.invoke({"question": "crm odontologico", "mode": "auto"})["result"]
        self.assertLess(result["search_calls"], 8)
        self.assertIn(result["coverage_summary"]["stop_reason"], {"good_coverage", "diminishing_returns"})

    def test_auto_escalates_when_evidence_is_weak(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            client = WeakEvidenceClient()
            graph = self._graph(tmp_dir, client)
            result = graph.invoke({"question": "crm odontologico", "mode": "auto"})["result"]
        self.assertGreaterEqual(result["search_calls"], 6)
        self.assertLessEqual(result["search_calls"], 8)

    def test_exhaustive_requires_explicit_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            client = StrongEvidenceClient()
            graph = self._graph(tmp_dir, client)
            with self.assertRaises(RuntimeError):
                graph.invoke({"question": "market map", "mode": "exhaustive"})

    def test_execution_cost_cap_is_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            client = WeakEvidenceClient()
            graph = self._graph(tmp_dir, client)
            result = graph.invoke(
                {
                    "question": "market map",
                    "mode": "deep",
                    "execution_cost_cap_usd": 0.01,
                }
            )["result"]
        self.assertLessEqual(result["search_calls"], 2)
        self.assertEqual(result["usage"]["execution_cost_cap_usd"], 0.01)
        self.assertEqual(result["coverage_summary"]["stop_reason"], "execution_cost_cap_reached")

    def test_run_id_and_storage_are_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            client = StrongEvidenceClient()
            graph = self._graph(tmp_dir, client)
            result = graph.invoke({"question": "crm odontologico", "mode": "auto"})["result"]
            run_path = Path(tmp_dir) / "research_runs" / f"{result['run_id']}.json"
            self.assertTrue(result["run_id"].startswith("research_"))
            self.assertTrue(result["storage"]["full_payload_stored"])
            self.assertTrue(run_path.exists())

    def test_top_sources_include_structural_scores_and_clusters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            client = StrongEvidenceClient()
            graph = self._graph(tmp_dir, client)
            result = graph.invoke(
                {
                    "question": "crm odontologico pricing growth",
                    "mode": "auto",
                    "focus_topics": ["pricing", "growth"],
                }
            )["result"]
        self.assertTrue(result["top_sources"])
        first = result["top_sources"][0]
        self.assertIn("source_type", first)
        self.assertIn("final_score", first)
        self.assertIn("evidence_strength", first)
        self.assertIsInstance(result["clusters"], list)


if __name__ == "__main__":
    unittest.main()
