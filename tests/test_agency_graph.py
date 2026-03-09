from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from automation_intel_mcp.graphs.agency_graph import build_agency_graph
from automation_intel_mcp.models import ResearchWorkflowResult, WebPageSnapshot


class FakeFetcher:
    def fetch_page(self, url: str) -> WebPageSnapshot:
        html = """
        <html>
          <body>
            <a href='/contato'>Fale conosco</a>
            <a href='https://wa.me/5511999999999'>WhatsApp</a>
            <form action='/lead' method='post'>
              <input type='email' name='email' />
              <button type='submit'>Solicitar orcamento</button>
            </form>
          </body>
        </html>
        """
        return WebPageSnapshot(
            url=url,
            status_code=200,
            final_url=url,
            html=html,
            extracted_text="Clinica com agendamento, atendimento e servicos odontologicos.",
            excerpt="Clinica com agendamento",
        )


class FakeResearchGateway:
    def __init__(self) -> None:
        self.last_mode: str | None = None

    def research_company(self, company_name: str, niche: str | None, *, mode: str | None = None) -> ResearchWorkflowResult:
        self.last_mode = mode
        return ResearchWorkflowResult(
            query=company_name,
            question=company_name,
            intent="factual",
            mode_requested=mode or "auto",
            mode_used="standard",
            search_strategy="adaptive_auto:standard",
            min_searches=3,
            max_searches=8,
            search_calls=4,
            summary="External summary",
            findings=["External finding"],
            suggested_next_steps=[],
            usage={"execution_cost_usd": 0.02},
        )


class AgencyGraphTests(unittest.TestCase):
    def test_agency_graph_returns_company_analysis_and_outreach(self) -> None:
        gateway = FakeResearchGateway()
        graph = build_agency_graph(FakeFetcher(), research_gateway=gateway)
        result = graph.invoke(
            {
                "company_name": "Acme Dental",
                "company_url": "https://acme.test",
                "niche": "clinica odontologica",
                "use_external_research": True,
                "external_research_mode": "standard",
            }
        )
        self.assertIn("company_analysis", result)
        self.assertIn("outreach", result)
        analysis = result["company_analysis"]
        self.assertIn("company_summary", analysis)
        self.assertIn("contact_points", analysis)
        self.assertIn("confidence_notes", analysis)
        self.assertTrue(analysis["external_research_used"])
        self.assertEqual(analysis["external_research_mode"], "standard")
        self.assertEqual(analysis["external_research_search_calls"], 4)
        self.assertEqual(analysis["external_research_cost_usd"], 0.02)
        self.assertEqual(gateway.last_mode, "standard")


if __name__ == "__main__":
    unittest.main()
