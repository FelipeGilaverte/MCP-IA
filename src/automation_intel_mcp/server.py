from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from automation_intel_mcp.runtime import agency_graph, budget, research_graph, web_fetcher
from automation_intel_mcp.tools.agency_logic import build_commercial_offer, build_outreach, score_niche_locally

mcp = FastMCP("automation-intel-mcp")


@mcp.tool()
def research_raw_search(query: str, max_results: int | None = None) -> dict:
    """Return structured web results without LLM synthesis."""
    from automation_intel_mcp.runtime import perplexity_client

    return perplexity_client.raw_search(query, max_results=max_results)


@mcp.tool()
def web_extract_url(url: str) -> dict:
    """Fetch a public web page and extract its main readable text."""
    return web_fetcher.fetch_and_extract(url).model_dump()


@mcp.tool()
def agency_score_niche(niche: str) -> dict:
    """Estimate how attractive a niche is for an automation agency."""
    return score_niche_locally(niche).model_dump()


@mcp.tool()
def agency_analyze_company(
    company_name: str,
    company_url: str,
    niche: str,
    use_external_research: bool = False,
    external_research_mode: str = "auto",
) -> dict:
    """Analyze a public company website and optionally enrich it with conservative external research."""
    result = agency_graph.invoke(
        {
            "company_name": company_name,
            "company_url": company_url,
            "niche": niche,
            "use_external_research": use_external_research,
            "external_research_mode": external_research_mode,
        }
    )
    return {
        "niche_score": result.get("niche_score"),
        "company_analysis": result.get("company_analysis"),
        "outreach": result.get("outreach"),
    }


@mcp.tool()
def agency_generate_offer(
    niche: str,
    pain: str,
    solution: str,
    desired_ticket: str,
    urgency_level: str,
) -> dict:
    """Generate a stronger commercial offer with channel-ready variants."""
    return build_commercial_offer(
        niche=niche,
        pain=pain,
        solution=solution,
        desired_ticket=desired_ticket,
        urgency_level=urgency_level,
    ).model_dump()


@mcp.tool()
def agency_generate_outreach(
    company_name: str,
    niche: str,
    pain_summary: str,
    solution_summary: str,
    channel: str = "whatsapp",
) -> dict:
    """Generate a first-contact draft for WhatsApp or email."""
    return build_outreach(company_name, niche, pain_summary, solution_summary, channel).model_dump()


@mcp.tool()
def system_budget_status() -> dict:
    """Show the current month spend tracked locally by this project."""
    return budget.status()


@mcp.tool()
def graph_run_research(
    question: str,
    mode: str = "auto",
    max_searches: int | None = None,
    execution_cost_cap_usd: float | None = None,
    allow_exhaustive: bool = False,
) -> dict:
    """Legacy combined server: evidence-first research graph."""
    result = research_graph.invoke(
        {
            "question": question,
            "mode": mode,
            "max_searches": max_searches,
            "execution_cost_cap_usd": execution_cost_cap_usd,
            "allow_exhaustive": allow_exhaustive,
        }
    )
    return result.get("result", {})


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
