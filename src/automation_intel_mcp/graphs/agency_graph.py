from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from automation_intel_mcp.models import ResearchWorkflowResult
from automation_intel_mcp.services.research_gateway import ResearchGateway
from automation_intel_mcp.services.web_fetcher import WebFetcher
from automation_intel_mcp.tools.agency_logic import analyze_company_site, score_niche_locally


class AgencyGraphState(TypedDict, total=False):
    niche: str
    company_name: str
    company_url: str
    use_external_research: bool
    external_research_mode: str
    niche_score: dict
    page_text: str
    page_html: str
    external_research: dict
    company_analysis: dict
    outreach: dict


def build_agency_graph(fetcher: WebFetcher, research_gateway: ResearchGateway | None = None):
    def score_niche(state: AgencyGraphState) -> AgencyGraphState:
        return {"niche_score": score_niche_locally(state["niche"]).model_dump()}

    def scrape_company(state: AgencyGraphState) -> AgencyGraphState:
        page = fetcher.fetch_page(state["company_url"])
        return {
            "page_text": page.extracted_text[:12000],
            "page_html": page.html,
        }

    def maybe_research(state: AgencyGraphState) -> AgencyGraphState:
        if research_gateway is None or not state.get("use_external_research", False):
            return {}
        result = research_gateway.research_company(
            state["company_name"],
            state.get("niche"),
            mode=state.get("external_research_mode"),
        )
        return {"external_research": result.model_dump()}

    def analyze_company(state: AgencyGraphState) -> AgencyGraphState:
        external_research = None
        if state.get("external_research"):
            external_research = ResearchWorkflowResult.model_validate(state["external_research"])
        analysis = analyze_company_site(
            company_name=state["company_name"],
            company_url=state["company_url"],
            niche=state.get("niche"),
            html=state.get("page_html", ""),
            extracted_text=state.get("page_text", ""),
            usage={},
            external_research=external_research,
            external_research_mode=external_research.mode_requested if external_research else None,
        )
        return {
            "company_analysis": analysis.model_dump(),
            "outreach": analysis.outreach,
        }

    graph = StateGraph(AgencyGraphState)
    graph.add_node("score_niche", score_niche)
    graph.add_node("scrape_company", scrape_company)
    graph.add_node("maybe_research", maybe_research)
    graph.add_node("analyze_company", analyze_company)

    graph.add_edge(START, "score_niche")
    graph.add_edge("score_niche", "scrape_company")
    graph.add_edge("scrape_company", "maybe_research")
    graph.add_edge("maybe_research", "analyze_company")
    graph.add_edge("analyze_company", END)
    return graph.compile()
