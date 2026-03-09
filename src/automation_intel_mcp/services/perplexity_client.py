from __future__ import annotations

import json
from typing import Any

from perplexity import Perplexity

from automation_intel_mcp.config import Settings
from automation_intel_mcp.models import ResearchResponse, SearchResult
from automation_intel_mcp.services.budget import BudgetTracker
from automation_intel_mcp.services.cache import FileCache


class PerplexityResearchClient:
    def __init__(self, settings: Settings, cache: FileCache, budget: BudgetTracker) -> None:
        self.settings = settings
        self.cache = cache
        self.budget = budget
        self.client = Perplexity(api_key=settings.perplexity_api_key) if settings.perplexity_api_key else None

    def _require_client(self) -> Perplexity:
        if self.client is None:
            raise RuntimeError("PERPLEXITY_API_KEY is missing. Add it to your .env file.")
        return self.client

    @staticmethod
    def _obj_to_dict(obj: Any) -> dict[str, Any]:
        if isinstance(obj, dict):
            return obj
        if hasattr(obj, "model_dump"):
            return obj.model_dump()
        if hasattr(obj, "to_dict"):
            return obj.to_dict()
        return json.loads(json.dumps(obj, default=str))

    @staticmethod
    def _extract_cost(payload: dict[str, Any]) -> float | None:
        usage = payload.get("usage") or {}
        cost = usage.get("cost") or {}
        if isinstance(cost, dict):
            total_cost = cost.get("total_cost")
            if total_cost is not None:
                return float(total_cost)
            numeric_values = [float(value) for value in cost.values() if isinstance(value, (int, float))]
            if numeric_values:
                return float(sum(numeric_values))
            return None
        if isinstance(cost, (int, float)):
            return float(cost)
        return None

    @staticmethod
    def _extract_citations(payload: dict[str, Any]) -> list[str]:
        citations: list[str] = []
        for result in payload.get("search_results") or []:
            url = result.get("url")
            if url and url not in citations:
                citations.append(url)
        return citations

    @staticmethod
    def _extract_search_results(payload: dict[str, Any]) -> list[SearchResult]:
        results: list[SearchResult] = []
        for item in payload.get("search_results") or []:
            try:
                results.append(SearchResult.model_validate(item))
            except Exception:
                continue
        return results

    def _record_budget(
        self,
        operation: str,
        payload: dict[str, Any],
        estimated_cost_usd: float,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        actual_cost = self._extract_cost(payload)
        return self.budget.record(
            "perplexity",
            operation,
            actual_cost_usd=actual_cost,
            estimated_cost_usd=None if actual_cost is not None else estimated_cost_usd,
            metadata=metadata,
        )

    def raw_search(
        self,
        query: str,
        *,
        max_results: int | None = None,
        search_domain_filter: list[str] | None = None,
        search_language_filter: list[str] | None = None,
        max_tokens_per_page: int = 1024,
    ) -> dict[str, Any]:
        effective_max_results = max_results or self.settings.perplexity_raw_search_max_results
        cache_key = {
            "endpoint": "search.create",
            "query": query,
            "max_results": effective_max_results,
            "search_domain_filter": search_domain_filter,
            "search_language_filter": search_language_filter,
            "max_tokens_per_page": max_tokens_per_page,
        }
        cached = self.cache.get(cache_key)
        if cached is not None:
            cached["cached"] = True
            return cached

        self.budget.ensure_within_budget()
        client = self._require_client()
        response = client.search.create(
            query=query,
            max_results=effective_max_results,
            search_domain_filter=search_domain_filter,
            search_language_filter=search_language_filter,
            max_tokens_per_page=max_tokens_per_page,
        )
        payload = self._obj_to_dict(response)
        budget_meta = self._record_budget(
            operation="raw_search",
            payload=payload,
            estimated_cost_usd=self.settings.perplexity_estimated_raw_search_cost_usd,
            metadata={"query": query, "max_results": effective_max_results},
        )
        result = {
            "mode": "raw-search",
            "query": query,
            "results": payload.get("results", []),
            "usage": budget_meta,
            "cached": False,
        }
        self.cache.set(cache_key, result)
        return result

    def ask_sonar(
        self,
        question: str,
        *,
        model: str | None = None,
        search_type: str = "fast",
        system_prompt: str | None = None,
        max_output_tokens: int | None = None,
        operation_name: str = "quick_search",
        estimated_cost_usd: float | None = None,
        mode: str = "quick",
        extra_budget_metadata: dict[str, Any] | None = None,
    ) -> ResearchResponse:
        actual_model = model or self.settings.perplexity_default_model
        max_output_tokens = max_output_tokens or self.settings.default_max_output_tokens
        cache_key = {
            "endpoint": "chat.completions.create",
            "question": question,
            "model": actual_model,
            "search_type": search_type,
            "system_prompt": system_prompt,
            "max_output_tokens": max_output_tokens,
            "operation_name": operation_name,
        }
        cached = self.cache.get(cache_key)
        if cached is not None:
            cached["cached"] = True
            return ResearchResponse.model_validate(cached)

        self.budget.ensure_within_budget()
        client = self._require_client()
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": question})

        response = client.chat.completions.create(
            model=actual_model,
            messages=messages,
            max_tokens=max_output_tokens,
            web_search_options={"search_type": search_type},
        )
        payload = self._obj_to_dict(response)
        answer = ((payload.get("choices") or [{}])[0].get("message", {}).get("content", ""))
        budget_meta = self._record_budget(
            operation=operation_name,
            payload=payload,
            estimated_cost_usd=estimated_cost_usd or self.settings.perplexity_estimated_quick_search_cost_usd,
            metadata={
                "question": question,
                "model": actual_model,
                "search_type": search_type,
                **(extra_budget_metadata or {}),
            },
        )
        result = ResearchResponse(
            mode=mode,
            model=actual_model,
            answer=answer,
            citations=self._extract_citations(payload),
            search_results=self._extract_search_results(payload),
            usage={**(payload.get("usage") or {}), **budget_meta},
            cached=False,
        )
        self.cache.set(cache_key, result.model_dump())
        return result

    def deep_research_expensive(
        self,
        question: str,
        *,
        confirm_expensive: bool = False,
        max_output_tokens: int | None = None,
    ) -> ResearchResponse:
        if not self.settings.enable_premium_research_tools:
            raise RuntimeError("Premium research tools are disabled. Set ENABLE_PREMIUM_RESEARCH_TOOLS=true to allow this path.")
        if not confirm_expensive:
            raise RuntimeError("Expensive deep research requires confirm_expensive=True.")
        return self.ask_sonar(
            question,
            model=self.settings.perplexity_deep_model,
            search_type="fast",
            system_prompt=(
                "Perform premium deep research. Return a structured report with executive summary, findings, risks, and next steps."
            ),
            max_output_tokens=max_output_tokens or self.settings.default_deep_max_output_tokens,
            operation_name="deep_search_expensive_premium",
            estimated_cost_usd=self.settings.perplexity_estimated_deep_search_cost_usd,
            mode="deep-expensive",
            extra_budget_metadata={
                "premium_label": self.settings.perplexity_deep_search_premium_label,
                "confirm_expensive": True,
            },
        )
