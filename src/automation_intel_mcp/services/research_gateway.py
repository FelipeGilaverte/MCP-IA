from __future__ import annotations

from automation_intel_mcp.config import Settings
from automation_intel_mcp.models import ResearchWorkflowResult
from automation_intel_mcp.services.agency_research_templates import build_agency_business_queries

_MODE_RANK = {
    "auto": 0,
    "quick": 1,
    "standard": 2,
    "deep": 3,
    "exhaustive": 4,
}


class ResearchGateway:
    def __init__(self, research_graph, settings: Settings) -> None:
        self.research_graph = research_graph
        self.settings = settings

    def _normalize_mode(self, requested_mode: str | None) -> str:
        mode = (requested_mode or self.settings.agency_external_research_default_mode).strip().lower()
        if mode not in _MODE_RANK:
            mode = self.settings.agency_external_research_default_mode
        max_mode = self.settings.agency_external_research_max_mode.strip().lower()
        if max_mode not in _MODE_RANK:
            max_mode = "standard"
        if _MODE_RANK[mode] > _MODE_RANK[max_mode]:
            return max_mode
        if mode == "deep":
            return max_mode
        if mode == "exhaustive":
            return max_mode
        return mode

    def research_company(
        self,
        company_name: str,
        niche: str | None,
        *,
        mode: str | None = None,
    ) -> ResearchWorkflowResult:
        normalized_mode = self._normalize_mode(mode)
        question = (
            f"Company: {company_name}. Niche: {niche or 'unknown'}. "
            f"Gather external signals about positioning, likely service model, and key commercial risks."
        )
        result = self.research_graph.invoke(
            {
                "question": question,
                "mode": normalized_mode,
                "extra_subqueries": build_agency_business_queries(question, max_queries=6),
                "allow_exhaustive": False,
            }
        ).get("result", {})
        return ResearchWorkflowResult.model_validate(result)
