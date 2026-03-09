from __future__ import annotations

from automation_intel_mcp.config import get_settings
from automation_intel_mcp.graphs.agency_graph import build_agency_graph
from automation_intel_mcp.graphs.research_graph import build_research_graph
from automation_intel_mcp.services.budget import BudgetTracker
from automation_intel_mcp.services.cache import FileCache
from automation_intel_mcp.services.perplexity_client import PerplexityResearchClient
from automation_intel_mcp.services.research_gateway import ResearchGateway
from automation_intel_mcp.services.run_store import ResearchRunStore
from automation_intel_mcp.services.web_fetcher import WebFetcher

settings = get_settings()
cache = FileCache(settings.cache_dir, enabled=settings.cache_enabled, ttl_hours=settings.cache_ttl_hours)
budget = BudgetTracker(settings.cache_dir, settings.budget_soft_limit_usd, settings.budget_hard_limit_usd)
perplexity_client = PerplexityResearchClient(settings, cache, budget)
web_fetcher = WebFetcher(settings, cache)
research_run_store = ResearchRunStore(settings.cache_dir, ttl_hours=settings.cache_ttl_hours)
research_graph = build_research_graph(perplexity_client, settings, budget, web_fetcher=web_fetcher, run_store=research_run_store)
research_gateway = ResearchGateway(research_graph, settings)
agency_graph = build_agency_graph(
    web_fetcher,
    research_gateway=research_gateway if settings.agency_enable_external_research else None,
)
