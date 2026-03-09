from __future__ import annotations

from typing import Any, TypedDict
from urllib.parse import urlparse

from langgraph.graph import END, START, StateGraph

from automation_intel_mcp.config import Settings
from automation_intel_mcp.models import ResearchWorkflowResult, SearchResult
from automation_intel_mcp.services.budget import BudgetTracker
from automation_intel_mcp.services.perplexity_client import PerplexityResearchClient

_MODE_ORDER = {"auto": 0, "quick": 1, "standard": 2, "deep": 3, "exhaustive": 4}


class ResearchGraphState(TypedDict, total=False):
    question: str
    mode: str
    max_searches: int
    execution_cost_cap_usd: float
    allow_exhaustive: bool
    json_output: bool
    extra_subqueries: list[str]
    intent: str
    mode_requested: str
    mode_used: str
    search_strategy: str
    min_searches: int
    soft_target_searches: int
    max_searches_resolved: int
    query_plan: list[str]
    subqueries: list[str]
    results_by_subquery: dict[str, list[dict[str, Any]]]
    deduped_sources: list[dict[str, Any]]
    usage_rows: list[dict[str, Any]]
    all_searches_cached: bool
    stop_reason: str
    coverage_summary: dict[str, Any]
    findings: list[str]
    gaps_or_uncertainties: list[str]
    suggested_next_steps: list[str]
    result: dict[str, Any]


def _normalize_mode(value: str | None, default_mode: str) -> str:
    normalized = (value or default_mode).strip().lower()
    if normalized not in _MODE_ORDER:
        raise ValueError(f"Unsupported research mode: {value}")
    return normalized


def _detect_intent(question: str) -> str:
    lowered = question.lower()
    if any(token in lowered for token in ["compare", "compar", "vs", "versus", "rank", "ranking"]):
        return "comparison"
    if any(token in lowered for token in ["recent", "latest", "ultimas", "recentes", "atual"]):
        return "recent_developments"
    if any(token in lowered for token in ["strategy", "strategic", "estrateg", "roadmap", "scenario", "cenario", "risco", "risk"]):
        return "strategic"
    if any(token in lowered for token in ["como", "what", "o que", "quem", "when", "quando", "quanto", "how", "who", "why"]):
        return "factual"
    return "exploratory"


def _complexity_score(question: str, intent: str) -> int:
    lowered = question.lower()
    score = 0
    score += 2 if len(question.split()) >= 10 else 0
    score += 2 if intent == "comparison" else 0
    score += 2 if intent == "strategic" else 0
    score += 1 if intent == "recent_developments" else 0
    score += 1 if any(token in lowered for token in ["official", "primary", "benchmark", "dataset", "evidence"]) else 0
    score += 1 if any(token in lowered for token in ["2024", "2025", "2026", "latest", "recent", "agora", "current"]) else 0
    return score


def _resolve_mode_policy(question: str, requested_mode: str, settings: Settings) -> dict[str, Any]:
    intent = _detect_intent(question)
    score = _complexity_score(question, intent)
    if requested_mode == "auto":
        mode_used = "quick" if score <= 2 else "standard"
        min_searches = settings.research_auto_min_searches
        soft_target = settings.research_auto_soft_target_searches
        max_searches = settings.research_auto_max_searches
        search_strategy = f"adaptive_auto:{mode_used}"
    elif requested_mode == "quick":
        mode_used = "quick"
        min_searches = min(2, settings.research_quick_max_searches)
        soft_target = settings.research_quick_max_searches
        max_searches = settings.research_quick_max_searches
        search_strategy = "fixed_quick"
    elif requested_mode == "standard":
        mode_used = "standard"
        min_searches = min(3, settings.research_standard_max_searches)
        soft_target = settings.research_standard_max_searches
        max_searches = settings.research_standard_max_searches
        search_strategy = "fixed_standard"
    elif requested_mode == "deep":
        mode_used = "deep"
        min_searches = min(4, settings.research_deep_max_searches)
        soft_target = min(8, settings.research_deep_max_searches)
        max_searches = settings.research_deep_max_searches
        search_strategy = "fixed_deep"
    else:
        mode_used = "exhaustive"
        min_searches = min(5, settings.research_exhaustive_max_searches)
        soft_target = min(12, settings.research_exhaustive_max_searches)
        max_searches = settings.research_exhaustive_max_searches
        search_strategy = "fixed_exhaustive"
    return {
        "intent": intent,
        "mode_used": mode_used,
        "min_searches": min_searches,
        "soft_target_searches": soft_target,
        "max_searches_resolved": max_searches,
        "search_strategy": search_strategy,
    }


def _max_results_for_mode(mode_used: str, settings: Settings) -> int:
    if mode_used in {"standard", "deep", "exhaustive"}:
        return settings.perplexity_raw_search_max_results
    return min(settings.perplexity_raw_search_max_results, 8)


def _domain_from_url(url: str | None) -> str:
    if not url:
        return "unknown"
    parsed = urlparse(url)
    return parsed.netloc.lower() or "unknown"


def _normalize_snippet(value: str | None) -> str:
    return " ".join((value or "").lower().split())


def _build_query_plan(question: str, intent: str, max_queries: int) -> list[str]:
    cleaned = question.strip().rstrip("?")
    templates = [
        "{q}",
        "main evidence and sources for: {q}",
        "risks and uncertainties for: {q}",
        "recent developments about: {q}",
        "official or primary sources for: {q}",
        "examples and case studies for: {q}",
        "metrics and benchmarks for: {q}",
        "implementation challenges for: {q}",
        "alternative viewpoints on: {q}",
        "source diversity check for: {q}",
    ]
    if intent == "comparison":
        templates.extend(
            [
                "side by side comparison criteria for: {q}",
                "pros and cons of leading options for: {q}",
            ]
        )
    if intent in {"strategic", "recent_developments"}:
        templates.extend(
            [
                "scenario analysis for: {q}",
                "historical context and major shifts for: {q}",
                "strategic risks and constraints for: {q}",
            ]
        )

    unique: list[str] = []
    for template in templates:
        candidate = template.format(q=cleaned)
        if candidate not in unique:
            unique.append(candidate)
    return unique[:max_queries]


def _merge_query_plan(base_plan: list[str], extra_queries: list[str] | None, max_queries: int) -> list[str]:
    extras = [query for query in (extra_queries or []) if query]
    if not extras:
        return list(base_plan[:max_queries])

    reserved_slots = min(len(extras), max(1, min(max_queries // 3, 3)))
    merged: list[str] = []

    for candidate in extras:
        if candidate not in merged:
            merged.append(candidate)
        if len(merged) >= reserved_slots:
            break

    for candidate in base_plan:
        if candidate and candidate not in merged:
            merged.append(candidate)
        if len(merged) >= max_queries:
            return merged

    for candidate in extras:
        if candidate and candidate not in merged:
            merged.append(candidate)
        if len(merged) >= max_queries:
            break
    return merged


def _aggregate_usage(rows: list[dict[str, Any]], max_searches: int, execution_cost_cap_usd: float) -> dict[str, Any]:
    billed_total = round(sum(float((row or {}).get("billed_cost_usd") or 0.0) for row in rows), 8)
    estimated_total = round(sum(float((row or {}).get("estimated_cost_usd") or 0.0) for row in rows), 8)
    actual_total = round(sum(float((row or {}).get("actual_cost_usd") or 0.0) for row in rows), 8)
    providers = sorted({str((row or {}).get("provider")) for row in rows if (row or {}).get("provider")})
    operations = [str((row or {}).get("operation")) for row in rows if (row or {}).get("operation")]
    month_total = rows[-1].get("month_total_usd") if rows else None
    return {
        "providers": providers,
        "operations": operations,
        "search_calls": len(rows),
        "billed_cost_usd": billed_total,
        "estimated_cost_usd": estimated_total or None,
        "actual_cost_usd": actual_total or None,
        "execution_cost_usd": billed_total,
        "execution_cost_cap_usd": execution_cost_cap_usd,
        "max_searches": max_searches,
        "month_total_usd": month_total,
        "cost_source": "estimated" if estimated_total and not actual_total else "mixed" if estimated_total and actual_total else "actual" if actual_total else None,
    }


def _build_findings(sources: list[dict[str, Any]]) -> list[str]:
    findings: list[str] = []
    for item in sources[:8]:
        title = (item.get("title") or "Untitled source").strip()
        snippet = " ".join(str(item.get("snippet") or "").split())
        domain = _domain_from_url(item.get("url"))
        findings.append(f"{title} [{domain}]: {snippet[:220]}" if snippet else f"{title} [{domain}]")
    return findings


def _build_gaps(coverage_summary: dict[str, Any]) -> list[str]:
    gaps: list[str] = []
    if coverage_summary.get("unique_sources", 0) < 4:
        gaps.append("Few unique sources were found; coverage may still be shallow.")
    if coverage_summary.get("source_diversity_score", 0.0) < 0.4:
        gaps.append("Source diversity is limited; the evidence may be clustered around a small set of domains.")
    if coverage_summary.get("promotional_sources", 0) > 0:
        gaps.append("Some sources appear promotional or vendor-authored, so claims may need independent validation.")
    if not gaps:
        gaps.append("The evidence set is usable, but key claims should still be validated against primary or official sources.")
    return gaps[:3]


def _build_next_steps(intent: str) -> list[str]:
    steps = [
        "Use the deduplicated sources and snippets as context for GPT/OpenAI reasoning later.",
        "Open the most relevant primary or official sources to validate the strongest claims.",
    ]
    if intent == "comparison":
        steps.append("Ask GPT to compare the collected evidence side by side using explicit criteria.")
    elif intent in {"strategic", "recent_developments"}:
        steps.append("Ask GPT to map scenarios, tradeoffs, and uncertainties from the evidence set.")
    else:
        steps.append("Ask GPT to identify what remains uncertain and what primary evidence should be checked next.")
    return steps


def _needs_more_searches(coverage_summary: dict[str, Any], search_calls: int, min_searches: int, soft_target: int) -> bool:
    if search_calls < min_searches:
        return True
    if coverage_summary.get("execution_cap_reached"):
        return False
    if coverage_summary.get("good_coverage"):
        return False
    if search_calls < soft_target:
        return True
    if coverage_summary.get("new_sources_last_call", 0) <= 1 and coverage_summary.get("source_diversity_score", 0.0) >= 0.5:
        return False
    return coverage_summary.get("unique_sources", 0) < 6


def build_research_graph(client: PerplexityResearchClient, settings: Settings, budget: BudgetTracker):
    def classify_and_plan(state: ResearchGraphState) -> ResearchGraphState:
        requested_mode = _normalize_mode(state.get("mode"), settings.research_default_mode)
        allow_exhaustive = bool(state.get("allow_exhaustive", False))
        if requested_mode == "exhaustive" and not allow_exhaustive:
            raise RuntimeError("Exhaustive research requires --allow-exhaustive or explicit confirmation.")

        policy = _resolve_mode_policy(state["question"], requested_mode, settings)
        max_searches = policy["max_searches_resolved"]
        requested_max = state.get("max_searches")
        if requested_max is not None:
            max_searches = min(int(requested_max), max_searches)
        execution_cost_cap_usd = float(state.get("execution_cost_cap_usd") or settings.research_default_execution_cost_cap_usd)
        base_query_plan = _build_query_plan(state["question"], policy["intent"], max_searches)
        query_plan = _merge_query_plan(base_query_plan, state.get("extra_subqueries"), max_searches)
        return {
            "intent": policy["intent"],
            "mode_requested": requested_mode,
            "mode_used": policy["mode_used"],
            "search_strategy": policy["search_strategy"],
            "min_searches": min(policy["min_searches"], max_searches),
            "soft_target_searches": min(policy["soft_target_searches"], max_searches),
            "max_searches_resolved": max_searches,
            "execution_cost_cap_usd": execution_cost_cap_usd,
            "query_plan": query_plan,
            "subqueries": query_plan,
        }

    def gather_evidence(state: ResearchGraphState) -> ResearchGraphState:
        deduped_by_url: dict[str, dict[str, Any]] = {}
        seen_snippets: set[str] = set()
        duplicate_snippet_count = 0
        duplicate_url_count = 0
        repeated_domain_hits = 0
        promotional_sources = 0
        all_searches_cached = True
        usage_rows: list[dict[str, Any]] = []
        results_by_subquery: dict[str, list[dict[str, Any]]] = {}
        new_sources_per_call: list[int] = []
        stop_reason = "max_searches_reached"
        max_results = _max_results_for_mode(state["mode_used"], settings)
        execution_cap = float(state["execution_cost_cap_usd"])

        for query in state.get("query_plan") or [state["question"]]:
            current_execution_cost = round(sum(float((row or {}).get("billed_cost_usd") or 0.0) for row in usage_rows), 8)
            if current_execution_cost >= execution_cap:
                stop_reason = "execution_cost_cap_reached"
                break
            if budget.current_month_total() >= budget.hard_limit_usd:
                stop_reason = "monthly_hard_budget_reached"
                break

            response = client.raw_search(query, max_results=max_results)
            all_searches_cached = all_searches_cached and bool(response.get("cached", False))
            usage = response.get("usage")
            if isinstance(usage, dict):
                usage_rows.append(usage)

            bucket: list[dict[str, Any]] = []
            new_sources_this_call = 0
            for item in response.get("results") or []:
                if not isinstance(item, dict):
                    continue
                normalized = SearchResult.model_validate(item).model_dump()
                bucket.append(normalized)
                url = normalized.get("url")
                snippet_key = _normalize_snippet(normalized.get("snippet"))
                if any(token in f"{normalized.get('title', '')} {normalized.get('snippet', '')}".lower() for token in ["demo", "teste gratis", "free trial", "saiba mais", "quero conhecer"]):
                    promotional_sources += 1
                domain = _domain_from_url(url)
                if domain != "unknown" and sum(1 for source in deduped_by_url.values() if _domain_from_url(source.get("url")) == domain) >= 2:
                    repeated_domain_hits += 1
                if snippet_key and snippet_key in seen_snippets:
                    duplicate_snippet_count += 1
                elif snippet_key:
                    seen_snippets.add(snippet_key)
                if url and url in deduped_by_url:
                    duplicate_url_count += 1
                    continue
                if url:
                    deduped_by_url[url] = normalized
                    new_sources_this_call += 1
            results_by_subquery[query] = bucket
            new_sources_per_call.append(new_sources_this_call)

            unique_sources = len(deduped_by_url)
            unique_domains = len({_domain_from_url(item.get("url")) for item in deduped_by_url.values()})
            diversity_score = round(unique_domains / max(unique_sources, 1), 2)
            current_execution_cost = round(sum(float((row or {}).get("billed_cost_usd") or 0.0) for row in usage_rows), 8)
            execution_cap_reached = current_execution_cost >= execution_cap
            good_coverage = unique_sources >= 6 and unique_domains >= 4 and diversity_score >= 0.5
            coverage_summary = {
                "unique_sources": unique_sources,
                "unique_domains": unique_domains,
                "duplicate_urls": duplicate_url_count,
                "duplicate_snippets": duplicate_snippet_count,
                "repeated_domain_hits": repeated_domain_hits,
                "promotional_sources": promotional_sources,
                "source_diversity_score": diversity_score,
                "new_sources_per_call": list(new_sources_per_call),
                "new_sources_last_call": new_sources_this_call,
                "good_coverage": good_coverage,
                "execution_cap_reached": execution_cap_reached,
            }
            if execution_cap_reached:
                stop_reason = "execution_cost_cap_reached"
                break
            if repeated_domain_hits >= max(3, len(usage_rows)) and new_sources_this_call <= 1:
                stop_reason = "repeated_domains"
                break
            if duplicate_snippet_count >= max(3, len(usage_rows)) and new_sources_this_call <= 1:
                stop_reason = "repeated_snippets"
                break
            if state["mode_requested"] == "auto":
                if not _needs_more_searches(coverage_summary, len(usage_rows), state["min_searches"], state["soft_target_searches"]):
                    stop_reason = "good_coverage" if good_coverage else "diminishing_returns"
                    break
            else:
                if len(usage_rows) >= state["min_searches"] and good_coverage and new_sources_this_call <= 1:
                    stop_reason = "good_coverage"
                    break
                if len(usage_rows) >= state["min_searches"] and len(new_sources_per_call) >= 2 and sum(new_sources_per_call[-2:]) <= 1:
                    stop_reason = "diminishing_returns"
                    break

        deduped_sources = list(deduped_by_url.values())
        unique_domains = len({_domain_from_url(item.get("url")) for item in deduped_sources})
        total_seen = len(deduped_sources) + duplicate_url_count
        coverage_summary = {
            "unique_sources": len(deduped_sources),
            "unique_domains": unique_domains,
            "duplicate_urls": duplicate_url_count,
            "duplicate_snippets": duplicate_snippet_count,
            "repeated_domain_hits": repeated_domain_hits,
            "promotional_sources": promotional_sources,
            "source_diversity_score": round(unique_domains / max(len(deduped_sources), 1), 2) if deduped_sources else 0.0,
            "new_sources_per_call": new_sources_per_call,
            "new_sources_last_call": new_sources_per_call[-1] if new_sources_per_call else 0,
            "duplicate_ratio": round((duplicate_url_count + duplicate_snippet_count) / max(total_seen + duplicate_snippet_count, 1), 2),
            "good_coverage": len(deduped_sources) >= 6 and unique_domains >= 4,
            "stop_reason": stop_reason,
        }
        return {
            "results_by_subquery": results_by_subquery,
            "deduped_sources": deduped_sources,
            "usage_rows": usage_rows,
            "all_searches_cached": all_searches_cached and bool(usage_rows),
            "stop_reason": stop_reason,
            "coverage_summary": coverage_summary,
            "findings": _build_findings(deduped_sources),
            "gaps_or_uncertainties": _build_gaps(coverage_summary),
            "suggested_next_steps": _build_next_steps(state["intent"]),
        }

    def finalize(state: ResearchGraphState) -> ResearchGraphState:
        usage = _aggregate_usage(
            state.get("usage_rows") or [],
            max_searches=state["max_searches_resolved"],
            execution_cost_cap_usd=state["execution_cost_cap_usd"],
        )
        summary = (
            f"Collected {state.get('coverage_summary', {}).get('unique_sources', 0)} deduplicated sources across "
            f"{len(state.get('results_by_subquery') or {})} search passes; stop reason: {state.get('stop_reason', 'unknown')}."
        )
        results_by_subquery = {
            query: [SearchResult.model_validate(item) for item in items]
            for query, items in (state.get("results_by_subquery") or {}).items()
        }
        deduped_sources = [SearchResult.model_validate(item) for item in state.get("deduped_sources") or []]
        result = ResearchWorkflowResult(
            query=state["question"],
            question=state["question"],
            intent=state["intent"],
            mode_requested=state["mode_requested"],
            mode_used=state["mode_used"],
            search_strategy=state["search_strategy"],
            min_searches=state["min_searches"],
            max_searches=state["max_searches_resolved"],
            search_calls=len(state.get("usage_rows") or []),
            subqueries=state.get("subqueries") or [],
            subtopics=state.get("subqueries") or [],
            results_by_subquery=results_by_subquery,
            deduped_sources=deduped_sources,
            sources=deduped_sources,
            coverage_summary=state.get("coverage_summary") or {},
            findings=state.get("findings") or [],
            gaps_or_uncertainties=state.get("gaps_or_uncertainties") or [],
            suggested_next_steps=state.get("suggested_next_steps") or [],
            usage=usage,
            cached=bool(state.get("all_searches_cached", False)),
            summary=summary,
            depth=state["mode_requested"],
        )
        return {"result": result.model_dump()}

    graph = StateGraph(ResearchGraphState)
    graph.add_node("classify_and_plan", classify_and_plan)
    graph.add_node("gather_evidence", gather_evidence)
    graph.add_node("finalize", finalize)
    graph.add_edge(START, "classify_and_plan")
    graph.add_edge("classify_and_plan", "gather_evidence")
    graph.add_edge("gather_evidence", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile()
