from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from automation_intel_mcp.mcp_transport import configure_streamable_http_server
from automation_intel_mcp.runtime import agency_graph, budget
from automation_intel_mcp.runtime import settings as app_settings
from automation_intel_mcp.tools.agency_logic import build_commercial_offer, build_outreach, score_niche_locally

mcp = FastMCP("automation-intel-agency")


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


def main(transport: str = "stdio") -> None:
    mcp.run(transport=transport)


def main_streamable_http(
    host: str | None = None,
    port: int | None = None,
    path: str | None = None,
    public_base_url: str | None = None,
) -> None:
    configure_streamable_http_server(
        mcp,
        host=host or app_settings.agency_mcp_http_host,
        port=port or app_settings.agency_mcp_http_port,
        path=path or app_settings.agency_mcp_http_path,
        public_base_url=public_base_url or app_settings.agency_mcp_public_base_url,
        stateless_http=app_settings.mcp_stateless_http,
        json_response=app_settings.mcp_json_response,
    )
    main(transport="streamable-http")


if __name__ == "__main__":
    main()
