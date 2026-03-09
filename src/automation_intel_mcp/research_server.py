from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from automation_intel_mcp.mcp_transport import configure_streamable_http_server
from automation_intel_mcp.runtime import budget, research_graph, web_fetcher
from automation_intel_mcp.runtime import settings as app_settings

mcp = FastMCP("automation-intel-research")


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
def graph_run_research(
    question: str,
    mode: str = "auto",
    max_searches: int | None = None,
    execution_cost_cap_usd: float | None = None,
    allow_exhaustive: bool = False,
) -> dict:
    """Default evidence-first research path using raw search only."""
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
        host=host or app_settings.research_mcp_http_host,
        port=port or app_settings.research_mcp_http_port,
        path=path or app_settings.research_mcp_http_path,
        public_base_url=public_base_url or app_settings.research_mcp_public_base_url,
        stateless_http=app_settings.mcp_stateless_http,
        json_response=app_settings.mcp_json_response,
    )
    main(transport="streamable-http")


if __name__ == "__main__":
    main()
