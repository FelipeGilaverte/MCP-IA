from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from automation_intel_mcp.config import Settings
from automation_intel_mcp.services.budget import BudgetTracker
from automation_intel_mcp.services.cache import FileCache
from automation_intel_mcp.services.perplexity_client import PerplexityResearchClient


class _FakeSearchAPI:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create(self, **kwargs) -> dict:
        self.calls.append(kwargs)
        return {
            "results": [
                {
                    "title": "Acme",
                    "url": "https://example.com/acme",
                    "snippet": "Example result",
                }
            ],
            "usage": {},
        }


class _FakeChatCompletions:
    def create(self, **kwargs) -> dict:
        return {
            "choices": [{"message": {"content": "Premium answer"}}],
            "search_results": [{"title": "Acme", "url": "https://example.com/acme", "snippet": "Example"}],
            "usage": {"cost": {"total_cost": 1.23}},
        }


class _FakeChatAPI:
    def __init__(self) -> None:
        self.completions = _FakeChatCompletions()


class _FakePerplexityClient:
    def __init__(self) -> None:
        self.search = _FakeSearchAPI()
        self.chat = _FakeChatAPI()


class PerplexityClientTests(unittest.TestCase):
    def test_raw_search_records_estimated_cost_and_uses_configured_max_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(
                PERPLEXITY_API_KEY="fake-key",
                CACHE_DIR=tmp_dir,
                PERPLEXITY_ESTIMATED_RAW_SEARCH_COST_USD=0.007,
                PERPLEXITY_RAW_SEARCH_MAX_RESULTS=7,
            )
            cache = FileCache(Path(tmp_dir), enabled=True, ttl_hours=24)
            budget = BudgetTracker(Path(tmp_dir), soft_limit_usd=1.0, hard_limit_usd=2.0)
            client = PerplexityResearchClient(settings, cache, budget)
            fake_api = _FakePerplexityClient()
            client.client = fake_api

            result = client.raw_search("clinica odontologica")

            self.assertEqual(result["mode"], "raw-search")
            self.assertFalse(result["cached"])
            self.assertTrue(result["results"])
            self.assertEqual(result["usage"]["provider"], "perplexity")
            self.assertEqual(result["usage"]["operation"], "raw_search")
            self.assertEqual(result["usage"]["cost_source"], "estimated")
            self.assertAlmostEqual(result["usage"]["estimated_cost_usd"], 0.007)
            self.assertEqual(fake_api.search.calls[0]["max_results"], 7)

            log_path = Path(tmp_dir) / "usage_costs.jsonl"
            row = json.loads(log_path.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(row["provider"], "perplexity")
            self.assertEqual(row["operation"], "raw_search")
            self.assertEqual(row["metadata"]["query"], "clinica odontologica")
            self.assertAlmostEqual(row["billed_cost_usd"], 0.007)

    def test_deep_search_expensive_is_env_gated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            disabled_settings = Settings(PERPLEXITY_API_KEY="fake-key", CACHE_DIR=tmp_dir)
            cache = FileCache(Path(tmp_dir), enabled=True, ttl_hours=24)
            budget = BudgetTracker(Path(tmp_dir), soft_limit_usd=1.0, hard_limit_usd=2.0)
            disabled_client = PerplexityResearchClient(disabled_settings, cache, budget)
            disabled_client.client = _FakePerplexityClient()

            with self.assertRaises(RuntimeError):
                disabled_client.deep_research_expensive("market map", confirm_expensive=True)

            enabled_settings = Settings(
                PERPLEXITY_API_KEY="fake-key",
                CACHE_DIR=tmp_dir,
                ENABLE_PREMIUM_RESEARCH_TOOLS=True,
            )
            enabled_client = PerplexityResearchClient(enabled_settings, cache, budget)
            enabled_client.client = _FakePerplexityClient()

            with self.assertRaises(RuntimeError):
                enabled_client.deep_research_expensive("market map")

            result = enabled_client.deep_research_expensive("market map", confirm_expensive=True)
            self.assertEqual(result.mode, "deep-expensive")
            self.assertEqual(result.usage["operation"], "deep_search_expensive_premium")
            self.assertAlmostEqual(result.usage["actual_cost_usd"], 1.23)


if __name__ == "__main__":
    unittest.main()
