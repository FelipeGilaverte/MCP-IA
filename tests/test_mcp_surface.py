from __future__ import annotations

import sys
import unittest
from pathlib import Path

import anyio

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import automation_intel_mcp.research_server as research_server
import automation_intel_mcp.server as combined_server


async def _tool_names(mcp) -> set[str]:
    return {tool.name for tool in await mcp.list_tools()}


class MpcSurfaceTests(unittest.TestCase):
    def test_research_mcp_exposes_only_evidence_first_tools(self) -> None:
        tool_names = anyio.run(_tool_names, research_server.mcp)
        self.assertEqual(
            tool_names,
            {
                "research_raw_search",
                "web_extract_url",
                "graph_run_research",
                "research_get_run",
                "system_budget_status",
            },
        )
        self.assertNotIn("research_quick_search", tool_names)
        self.assertNotIn("research_deep_search_expensive", tool_names)

    def test_combined_mcp_exposes_expected_safe_surface(self) -> None:
        tool_names = anyio.run(_tool_names, combined_server.mcp)
        self.assertEqual(
            tool_names,
            {
                "research_raw_search",
                "web_extract_url",
                "graph_run_research",
                "agency_score_niche",
                "agency_analyze_company",
                "agency_generate_offer",
                "agency_generate_outreach",
                "system_budget_status",
            },
        )
        self.assertNotIn("research_quick_search", tool_names)
        self.assertNotIn("research_deep_search_expensive", tool_names)


if __name__ == "__main__":
    unittest.main()
