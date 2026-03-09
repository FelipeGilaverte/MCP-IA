from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from typer.testing import CliRunner

from automation_intel_mcp.cli import app


class _FakeAgencyGraph:
    def __init__(self) -> None:
        self.payloads: list[dict] = []

    def invoke(self, payload: dict) -> dict:
        self.payloads.append(payload)
        return {
            "niche_score": {"score": 80},
            "company_analysis": {
                "company_summary": "Summary",
                "external_research_used": payload.get("use_external_research", False),
                "external_research_mode": payload.get("external_research_mode"),
                "external_research_search_calls": 4 if payload.get("use_external_research") else 0,
            },
            "outreach": {"message": "msg"},
        }


class _FakeResearchGraph:
    def __init__(self) -> None:
        self.payloads: list[dict] = []

    def invoke(self, payload: dict) -> dict:
        self.payloads.append(payload)
        return {
            "result": {
                "query": payload["question"],
                "mode_requested": payload.get("mode", "auto"),
                "mode_used": payload.get("mode", "auto"),
                "search_strategy": "adaptive_auto:standard",
                "min_searches": 3,
                "max_searches": payload.get("max_searches") or 8,
                "search_calls": 4,
                "summary": "ok",
            }
        }


class CliTests(unittest.TestCase):
    def test_offer_command_outputs_json(self) -> None:
        runner = CliRunner()
        result = runner.invoke(app, ["offer", "clinica", "dor", "solucao", "R$ 1000", "alta"])
        self.assertEqual(result.exit_code, 0)
        payload = json.loads(result.stdout)
        self.assertIn("promise", payload)
        self.assertIn("channel_versions", payload)

    def test_batch_company_requires_headers(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp_dir:
            csv_path = Path(tmp_dir) / "input.csv"
            out_path = Path(tmp_dir) / "out.jsonl"
            csv_path.write_text("wrong,headers\n1,2\n", encoding="utf-8")
            result = runner.invoke(app, ["batch-company", str(csv_path), str(out_path)])
            self.assertNotEqual(result.exit_code, 0)
            self.assertIn("company_name, company_url, niche", result.stdout)

    def test_company_command_uses_external_research_mode(self) -> None:
        runner = CliRunner()
        fake_graph = _FakeAgencyGraph()
        with patch("automation_intel_mcp.cli.agency_graph", fake_graph):
            result = runner.invoke(
                app,
                ["company", "Acme", "https://acme.test", "clinica", "--external-research", "--external-research-mode", "standard"],
            )
        self.assertEqual(result.exit_code, 0)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["company_analysis"]["external_research_used"])
        self.assertEqual(payload["company_analysis"]["external_research_mode"], "standard")
        self.assertEqual(fake_graph.payloads[0]["external_research_mode"], "standard")

    def test_research_command_defaults_to_auto_mode(self) -> None:
        runner = CliRunner()
        fake_graph = _FakeResearchGraph()
        with patch("automation_intel_mcp.cli.research_graph", fake_graph):
            result = runner.invoke(app, ["research", "compare clinic crms"])
        self.assertEqual(result.exit_code, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["mode_requested"], "auto")
        self.assertEqual(fake_graph.payloads[0]["mode"], "auto")

    def test_research_command_passes_mode_and_caps(self) -> None:
        runner = CliRunner()
        fake_graph = _FakeResearchGraph()
        with patch("automation_intel_mcp.cli.research_graph", fake_graph):
            result = runner.invoke(
                app,
                ["research", "compare clinic crms", "--mode", "deep", "--max-searches", "9", "--execution-cost-cap", "0.03"],
            )
        self.assertEqual(result.exit_code, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["mode_requested"], "deep")
        self.assertEqual(fake_graph.payloads[0]["max_searches"], 9)
        self.assertEqual(fake_graph.payloads[0]["execution_cost_cap_usd"], 0.03)

    def test_deep_search_expensive_reports_disabled_state(self) -> None:
        runner = CliRunner()
        with patch(
            "automation_intel_mcp.cli.perplexity_client.deep_research_expensive",
            side_effect=RuntimeError("Premium research tools are disabled. Set ENABLE_PREMIUM_RESEARCH_TOOLS=true to enable them."),
        ):
            result = runner.invoke(app, ["deep-search-expensive", "market map", "--confirm-expensive"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("Premium research tools are disabled", result.stdout)

    def test_runserver_research_http_wires_arguments(self) -> None:
        runner = CliRunner()
        with patch("automation_intel_mcp.cli.research_server.main_streamable_http") as mocked:
            result = runner.invoke(
                app,
                [
                    "runserver-research-http",
                    "--host",
                    "0.0.0.0",
                    "--port",
                    "9100",
                    "--path",
                    "/mcp",
                    "--public-base-url",
                    "https://research.example.com",
                ],
            )
        self.assertEqual(result.exit_code, 0)
        mocked.assert_called_once_with(
            host="0.0.0.0",
            port=9100,
            path="/mcp",
            public_base_url="https://research.example.com",
        )

    def test_runserver_agency_http_wires_arguments(self) -> None:
        runner = CliRunner()
        with patch("automation_intel_mcp.cli.agency_server.main_streamable_http") as mocked:
            result = runner.invoke(
                app,
                [
                    "runserver-agency-http",
                    "--host",
                    "0.0.0.0",
                    "--port",
                    "9200",
                    "--path",
                    "/mcp",
                    "--public-base-url",
                    "https://agency.example.com",
                ],
            )
        self.assertEqual(result.exit_code, 0)
        mocked.assert_called_once_with(
            host="0.0.0.0",
            port=9200,
            path="/mcp",
            public_base_url="https://agency.example.com",
        )


if __name__ == "__main__":
    unittest.main()
