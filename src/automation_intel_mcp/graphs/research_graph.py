from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, TypedDict
from urllib.parse import urlparse

from langgraph.graph import END, START, StateGraph

from automation_intel_mcp.config import Settings
from automation_intel_mcp.models import ResearchCluster, ResearchContradiction, ResearchWorkflowResult, SearchResult
from automation_intel_mcp.services.budget import BudgetTracker
from automation_intel_mcp.services.perplexity_client import PerplexityResearchClient
from automation_intel_mcp.services.research_features import (
    build_raw_evidence_preview,
    canonicalize_url,
    classify_source_type,
    content_similarity,
    detect_numeric_claims,
    detect_topics,
    evidence_strength,
    extract_key_points,
    looks_promotional,
    score_credibility,
    score_final,
    score_freshness,
    score_relevance,
    title_similarity,
    tokenize_query_terms,
)
from automation_intel_mcp.services.run_store import ResearchRunStore
from automation_intel_mcp.services.web_fetcher import WebFetcher

logger = logging.getLogger(__name__)
_MODE_ORDER = {"auto": 0, "quick": 1, "standard": 2, "deep": 3, "exhaustive": 4}


class ResearchGraphState(TypedDict, total=False):
    question: str
    subqueries: list[str]
    focus_topics: list[str]
    mode: str
    max_searches: int
    execution_cost_cap_usd: float
    allow_exhaustive: bool
    extra_subqueries: list[str]
    return_full_payload: bool
    run_id: str
    started_at: str
    plan_hash: str
    intent: str
    mode_requested: str
    mode_used: str
    search_strategy: str
    min_searches: int
    soft_target_searches: int
    max_searches_resolved: int
    input_flags: dict[str, bool]
    query_plan: list[str]
    results_by_subquery: dict[str, list[dict[str, Any]]]
    full_results_by_subquery: dict[str, list[dict[str, Any]]]
    deduped_sources: list[dict[str, Any]]
    top_sources: list[dict[str, Any]]
    raw_results_flat: list[dict[str, Any]]
    usage_rows: list[dict[str, Any]]
    all_searches_cached: bool
    stop_reason: str
    coverage_summary: dict[str, Any]
    findings: list[str]
    gaps_or_uncertainties: list[str]
    warnings: list[str]
    clusters: list[dict[str, Any]]
    contradictions: list[dict[str, Any]]
    suggested_next_steps: list[str]
    results_summary: dict[str, Any]
    full_payload: dict[str, Any]
    result: dict[str, Any]


def _log_event(event: str, **fields: Any) -> None:
    logger.info(json.dumps({"event": event, **fields}, ensure_ascii=False, default=str))


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
    if any(token in lowered for token in ["strategy", "strategic", "estrateg", "roadmap", "scenario", "cenario", "risk", "risco"]):
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
    return settings.perplexity_raw_search_max_results if mode_used in {"standard", "deep", "exhaustive"} else min(settings.perplexity_raw_search_max_results, 8)


def _domain_from_url(url: str | None) -> str:
    if not url:
        return "unknown"
    parsed = urlparse(url)
    return parsed.netloc.lower() or "unknown"


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
        templates.extend(["side by side comparison criteria for: {q}", "pros and cons of leading options for: {q}"])
    if intent in {"strategic", "recent_developments"}:
        templates.extend(["scenario analysis for: {q}", "historical context and major shifts for: {q}", "strategic risks and constraints for: {q}"])
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


def _build_plan_hash(question: str, mode_requested: str, subqueries: list[str], focus_topics: list[str], max_searches: int) -> str:
    raw = json.dumps({"question": question, "mode_requested": mode_requested, "subqueries": subqueries, "focus_topics": focus_topics, "max_searches": max_searches}, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _aggregate_usage(rows: list[dict[str, Any]], *, run_id: str, max_searches: int, execution_cost_cap_usd: float, budget: BudgetTracker) -> dict[str, Any]:
    billed_total = round(sum(float((row or {}).get("billed_cost_usd") or 0.0) for row in rows), 8)
    estimated_total = round(sum(float((row or {}).get("estimated_cost_usd") or 0.0) for row in rows), 8)
    actual_total = round(sum(float((row or {}).get("actual_cost_usd") or 0.0) for row in rows), 8)
    providers = sorted({str((row or {}).get("provider")) for row in rows if (row or {}).get("provider")})
    operations = [str((row or {}).get("operation")) for row in rows if (row or {}).get("operation")]
    return {
        "providers": providers,
        "operations": operations,
        "search_calls": len(rows),
        "billed_cost_usd": billed_total,
        "estimated_cost_usd": estimated_total or None,
        "actual_cost_usd": actual_total or None,
        "execution_cost_usd": billed_total,
        "execution_cost_cap_usd": execution_cost_cap_usd,
        "provider_search_cost_usd": billed_total,
        "provider_extraction_cost_usd": 0.0,
        "total_cost_usd": billed_total,
        "max_searches": max_searches,
        "month_total_usd": budget.current_month_total(),
        "today_total_usd": budget.current_day_total(),
        "last_run_cost_usd": budget.last_run_cost(),
        "cost_source": "estimated" if estimated_total and not actual_total else "mixed" if estimated_total and actual_total else "actual" if actual_total else None,
        "run_id": run_id,
    }


def _build_findings(sources: list[dict[str, Any]]) -> list[str]:
    return [f"{(item.get('title') or 'Untitled source').strip()} [{_domain_from_url(item.get('canonical_url') or item.get('url'))}]: {' '.join(str(item.get('snippet') or '').split())[:220]}" for item in sources[:8]]


def _build_gaps(coverage_summary: dict[str, Any]) -> list[str]:
    gaps: list[str] = []
    if coverage_summary.get("unique_sources", 0) < 4:
        gaps.append("Poucas fontes únicas foram encontradas; a cobertura ainda pode estar rasa.")
    if coverage_summary.get("primary_sources", 0) == 0:
        gaps.append("Não foi encontrada fonte primária clara entre as principais evidências.")
    if coverage_summary.get("dated_sources", 0) < 2:
        gaps.append("A cobertura temporal é limitada; poucas fontes com data foram identificadas.")
    return gaps[:4]


def _build_warnings(coverage_summary: dict[str, Any], contradictions: list[dict[str, Any]]) -> list[str]:
    warnings: list[str] = []
    if coverage_summary.get("promotional_sources", 0) >= 2:
        warnings.append("Muitas fontes parecem promocionais ou vendor-authored.")
    if coverage_summary.get("duplicate_ratio", 0.0) >= 0.35:
        warnings.append("Há muitos duplicados ou near-duplicates na coleta.")
    if contradictions:
        warnings.append("Foram detectadas divergências entre fontes sobre números ou claims explícitos.")
    if coverage_summary.get("source_diversity_score", 0.0) < 0.4:
        warnings.append("A diversidade de domínios está baixa.")
    return warnings[:4]


def _build_next_steps(intent: str) -> list[str]:
    steps = ["Use o run_id e as top_sources como contexto para o GPT/OpenAI raciocinar depois.", "Abra as fontes primárias ou oficiais mais bem posicionadas para validar os claims principais."]
    if intent == "comparison":
        steps.append("Peça ao GPT para comparar as fontes em critérios explícitos usando as evidências coletadas.")
    elif intent in {"strategic", "recent_developments"}:
        steps.append("Peça ao GPT para mapear cenários, tradeoffs e incertezas a partir dos clusters e contradições.")
    else:
        steps.append("Peça ao GPT para identificar o que ainda está incerto e quais fontes primárias faltam.")
    return steps


def _needs_more_searches(coverage_summary: dict[str, Any], search_calls: int, min_searches: int, soft_target: int) -> bool:
    if search_calls < min_searches:
        return True
    if coverage_summary.get("execution_cap_reached") or coverage_summary.get("good_coverage"):
        return False
    if search_calls < soft_target:
        return True
    if coverage_summary.get("new_sources_last_call", 0) <= 1 and coverage_summary.get("source_diversity_score", 0.0) >= 0.5:
        return False
    return coverage_summary.get("unique_sources", 0) < 6


def _preview_results_by_subquery(results_by_subquery: dict[str, list[dict[str, Any]]], per_query: int = 2) -> dict[str, list[dict[str, Any]]]:
    return {query: items[:per_query] for query, items in results_by_subquery.items()}

def _cluster_sources(sources: list[dict[str, Any]], focus_topics: list[str] | None) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    for item in sources:
        topics = detect_topics(item.get("title"), item.get("snippet"), item.get("main_text"), focus_topics=focus_topics)
        for topic in topics:
            buckets.setdefault(topic, []).append(item)
    clusters: list[dict[str, Any]] = []
    for topic, items in buckets.items():
        urls = [str(item.get("canonical_url") or item.get("url") or "") for item in items if item.get("url")]
        clusters.append(ResearchCluster(topic=topic, source_count=len(items), top_urls=urls[:5]).model_dump())
    clusters.sort(key=lambda item: (-item["source_count"], item["topic"]))
    return clusters


def _detect_contradictions(sources: list[dict[str, Any]], focus_topics: list[str] | None) -> list[dict[str, Any]]:
    contradictions: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for idx, source_a in enumerate(sources):
        topics_a = detect_topics(source_a.get("title"), source_a.get("snippet"), source_a.get("main_text"), focus_topics=focus_topics)
        claims_a = detect_numeric_claims(source_a.get("snippet"), source_a.get("main_text"))
        if not claims_a:
            continue
        for source_b in sources[idx + 1 :]:
            if canonicalize_url(source_a.get("url")) == canonicalize_url(source_b.get("url")):
                continue
            topics_b = detect_topics(source_b.get("title"), source_b.get("snippet"), source_b.get("main_text"), focus_topics=focus_topics)
            common_topics = [topic for topic in topics_a if topic in topics_b]
            claims_b = detect_numeric_claims(source_b.get("snippet"), source_b.get("main_text"))
            if not common_topics or not claims_b or claims_a[0] == claims_b[0]:
                continue
            topic = common_topics[0]
            key = f"{topic}:{claims_a[0]}:{claims_b[0]}"
            if key in seen_keys:
                continue
            seen_keys.add(key)
            contradictions.append(
                ResearchContradiction(
                    topic=topic,
                    claim_a=f"{claims_a[0]} — {str(source_a.get('snippet') or source_a.get('title') or '')[:160]}",
                    source_a=str(source_a.get("canonical_url") or source_a.get("url") or ""),
                    claim_b=f"{claims_b[0]} — {str(source_b.get('snippet') or source_b.get('title') or '')[:160]}",
                    source_b=str(source_b.get("canonical_url") or source_b.get("url") or ""),
                    notes="Contradição estrutural detectada em números ou percentuais; o GPT deve resolver a interpretação final.",
                ).model_dump()
            )
            if len(contradictions) >= 5:
                return contradictions
    return contradictions


def build_research_graph(
    client: PerplexityResearchClient,
    settings: Settings,
    budget: BudgetTracker,
    *,
    web_fetcher: WebFetcher | None = None,
    run_store: ResearchRunStore | None = None,
):
    store = run_store or ResearchRunStore(settings.cache_dir, ttl_hours=settings.cache_ttl_hours)

    def classify_and_plan(state: ResearchGraphState) -> ResearchGraphState:
        requested_mode = _normalize_mode(state.get("mode"), settings.research_default_mode)
        allow_exhaustive = bool(state.get("allow_exhaustive", False))
        if requested_mode == "exhaustive" and not allow_exhaustive:
            raise RuntimeError("Exhaustive research requires --allow-exhaustive or explicit confirmation.")

        question = state["question"]
        input_subqueries = [item for item in state.get("subqueries") or [] if item]
        extra_subqueries = [item for item in state.get("extra_subqueries") or [] if item]
        focus_topics = [item for item in state.get("focus_topics") or [] if item]
        policy = _resolve_mode_policy(question, requested_mode, settings)
        max_searches = policy["max_searches_resolved"]
        requested_max = state.get("max_searches")
        if requested_max is not None:
            max_searches = min(int(requested_max), max_searches)
        execution_cost_cap_usd = float(state.get("execution_cost_cap_usd") or settings.research_default_execution_cost_cap_usd)
        base_query_plan = _build_query_plan(question, policy["intent"], max_searches)
        merged_plan = _merge_query_plan(base_query_plan, input_subqueries or extra_subqueries, max_searches)
        run_id = store.generate_run_id()
        plan_hash = _build_plan_hash(question, requested_mode, merged_plan, focus_topics, max_searches)
        input_flags = {"subqueries_provided": bool(input_subqueries), "focus_topics_provided": bool(focus_topics)}
        _log_event("research_run_started", run_id=run_id, question=question, mode_requested=requested_mode, max_searches=max_searches, subqueries=merged_plan)
        return {
            "run_id": run_id,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "plan_hash": plan_hash,
            "intent": policy["intent"],
            "mode_requested": requested_mode,
            "mode_used": policy["mode_used"],
            "search_strategy": policy["search_strategy"],
            "min_searches": min(policy["min_searches"], max_searches),
            "soft_target_searches": min(policy["soft_target_searches"], max_searches),
            "max_searches_resolved": max_searches,
            "execution_cost_cap_usd": execution_cost_cap_usd,
            "input_flags": input_flags,
            "query_plan": merged_plan,
            "subqueries": merged_plan,
            "focus_topics": focus_topics,
            "return_full_payload": bool(state.get("return_full_payload", False)),
        }

    def gather_evidence(state: ResearchGraphState) -> ResearchGraphState:
        deduped_candidates: list[dict[str, Any]] = []
        seen_canonical_urls: set[str] = set()
        duplicate_snippet_count = 0
        duplicate_url_count = 0
        duplicate_title_count = 0
        duplicate_content_count = 0
        repeated_domain_hits = 0
        promotional_sources = 0
        failed_extractions = 0
        extracted_pages = 0
        all_searches_cached = True
        usage_rows: list[dict[str, Any]] = []
        results_by_subquery: dict[str, list[dict[str, Any]]] = {}
        raw_results_flat: list[dict[str, Any]] = []
        new_sources_per_call: list[int] = []
        stop_reason = "max_searches_reached"
        max_results = _max_results_for_mode(state["mode_used"], settings)
        execution_cap = float(state["execution_cost_cap_usd"])
        query_terms = tokenize_query_terms(state["question"], *(state.get("focus_topics") or []))

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
                normalized["canonical_url"] = canonicalize_url(normalized.get("canonical_url") or normalized.get("url"))
                normalized["source_type"] = normalized.get("source_type") or classify_source_type(normalized.get("canonical_url"), normalized.get("title"), normalized.get("snippet"))
                normalized["relevance_score"] = normalized.get("relevance_score") or score_relevance(query_terms, normalized.get("title"), normalized.get("snippet"), normalized.get("url"))
                normalized["credibility_score"] = normalized.get("credibility_score") or score_credibility(normalized["source_type"], normalized.get("extraction_quality") or "low")
                normalized["freshness_score"] = normalized.get("freshness_score") or score_freshness(normalized.get("published_at") or normalized.get("date"), normalized.get("last_updated"))
                normalized["final_score"] = normalized.get("final_score") or score_final(float(normalized["relevance_score"]), float(normalized["credibility_score"]), float(normalized["freshness_score"]))
                normalized["evidence_strength"] = normalized.get("evidence_strength") or evidence_strength(float(normalized["final_score"]), normalized.get("extraction_quality") or "low")
                normalized["key_points"] = normalized.get("key_points") or extract_key_points(normalized.get("snippet"), normalized.get("title"))
                if looks_promotional(normalized.get("title"), normalized.get("snippet")):
                    promotional_sources += 1
                bucket.append(normalized)
                raw_results_flat.append(normalized)
                canonical_url = normalized.get("canonical_url") or normalized.get("url")
                if canonical_url and canonical_url in seen_canonical_urls:
                    duplicate_url_count += 1
                    continue
                if any(title_similarity(normalized.get("title"), existing.get("title")) >= 0.94 for existing in deduped_candidates):
                    duplicate_title_count += 1
                    continue
                if any(content_similarity(normalized.get("snippet"), existing.get("snippet")) >= 0.97 for existing in deduped_candidates):
                    duplicate_snippet_count += 1
                    continue
                domain = _domain_from_url(canonical_url)
                if domain != "unknown" and sum(1 for source in deduped_candidates if _domain_from_url(source.get("canonical_url") or source.get("url")) == domain) >= 2:
                    repeated_domain_hits += 1
                if canonical_url:
                    seen_canonical_urls.add(canonical_url)
                deduped_candidates.append(normalized)
                new_sources_this_call += 1

            results_by_subquery[query] = bucket
            new_sources_per_call.append(new_sources_this_call)
            unique_sources = len(deduped_candidates)
            unique_domains = len({_domain_from_url(item.get("canonical_url") or item.get("url")) for item in deduped_candidates})
            diversity_score = round(unique_domains / max(unique_sources, 1), 2)
            current_execution_cost = round(sum(float((row or {}).get("billed_cost_usd") or 0.0) for row in usage_rows), 8)
            execution_cap_reached = current_execution_cost >= execution_cap
            good_coverage = unique_sources >= 6 and unique_domains >= 4 and diversity_score >= 0.5
            coverage_summary = {"unique_sources": unique_sources, "unique_domains": unique_domains, "duplicate_urls": duplicate_url_count, "duplicate_titles": duplicate_title_count, "duplicate_snippets": duplicate_snippet_count, "duplicate_content": duplicate_content_count, "repeated_domain_hits": repeated_domain_hits, "promotional_sources": promotional_sources, "source_diversity_score": diversity_score, "new_sources_per_call": list(new_sources_per_call), "new_sources_last_call": new_sources_this_call, "good_coverage": good_coverage, "execution_cap_reached": execution_cap_reached}
            _log_event("research_search_call", run_id=state["run_id"], query=query, results_count=len(bucket), deduped_sources=unique_sources, search_calls=len(usage_rows), cached=response.get("cached", False), execution_cost=current_execution_cost)
            if execution_cap_reached:
                stop_reason = "execution_cost_cap_reached"
                break
            if repeated_domain_hits >= max(3, len(usage_rows)) and new_sources_this_call <= 1:
                stop_reason = "repeated_domains"
                break
            if (
                len(usage_rows) >= max(state["soft_target_searches"], state["min_searches"])
                and duplicate_snippet_count >= max(5, len(usage_rows) * 2)
                and new_sources_this_call <= 1
                and unique_sources < 4
            ):
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

        deduped_candidates.sort(key=lambda item: float(item.get("final_score") or 0.0), reverse=True)
        for candidate in deduped_candidates[: min(len(deduped_candidates), 8)]:
            if not web_fetcher:
                continue
            try:
                page = web_fetcher.fetch_page(str(candidate.get("canonical_url") or candidate.get("url")))
                extracted_pages += 1
                candidate["canonical_url"] = page.canonical_url or candidate.get("canonical_url")
                candidate["published_at"] = candidate.get("published_at") or page.published_at or candidate.get("date")
                candidate["last_updated"] = candidate.get("last_updated") or page.last_updated
                candidate["main_text"] = page.main_text
                candidate["content_hash"] = page.content_hash
                candidate["extraction_quality"] = page.extraction_quality
                candidate["relevance_score"] = score_relevance(query_terms, candidate.get("title"), candidate.get("snippet"), page.main_text, candidate.get("url"))
                candidate["credibility_score"] = score_credibility(candidate.get("source_type") or "vendor", page.extraction_quality)
                candidate["freshness_score"] = score_freshness(candidate.get("published_at"), candidate.get("last_updated"))
                candidate["final_score"] = score_final(float(candidate["relevance_score"]), float(candidate["credibility_score"]), float(candidate["freshness_score"]))
                candidate["evidence_strength"] = evidence_strength(float(candidate["final_score"]), page.extraction_quality)
                candidate["key_points"] = extract_key_points(candidate.get("snippet"), page.main_text)
            except Exception as exc:
                failed_extractions += 1
                candidate["extraction_quality"] = candidate.get("extraction_quality") or "low"
                candidate.setdefault("key_points", extract_key_points(candidate.get("snippet")))
                _log_event("research_extraction_failed", run_id=state["run_id"], url=candidate.get("url"), error=str(exc))

        deduped_sources: list[dict[str, Any]] = []
        seen_content_hashes: set[str] = set()
        for candidate in deduped_candidates:
            current_hash = candidate.get("content_hash")
            if current_hash and current_hash in seen_content_hashes:
                duplicate_content_count += 1
                continue
            if current_hash:
                seen_content_hashes.add(current_hash)
            if any(title_similarity(candidate.get("title"), existing.get("title")) >= 0.96 for existing in deduped_sources):
                continue
            deduped_sources.append(candidate)

        deduped_sources.sort(key=lambda item: float(item.get("final_score") or 0.0), reverse=True)
        top_sources = deduped_sources[:8]
        clusters = _cluster_sources(deduped_sources, state.get("focus_topics"))
        contradictions = _detect_contradictions(deduped_sources, state.get("focus_topics"))
        unique_domains = len({_domain_from_url(item.get("canonical_url") or item.get("url")) for item in deduped_sources})
        coverage_summary = {
            "unique_sources": len(deduped_sources),
            "unique_domains": unique_domains,
            "duplicate_urls": duplicate_url_count,
            "duplicate_titles": duplicate_title_count,
            "duplicate_snippets": duplicate_snippet_count,
            "duplicate_content": duplicate_content_count,
            "repeated_domain_hits": repeated_domain_hits,
            "promotional_sources": promotional_sources,
            "source_diversity_score": round(unique_domains / max(len(deduped_sources), 1), 2) if deduped_sources else 0.0,
            "new_sources_per_call": new_sources_per_call,
            "new_sources_last_call": new_sources_per_call[-1] if new_sources_per_call else 0,
            "duplicate_ratio": round((duplicate_url_count + duplicate_title_count + duplicate_snippet_count + duplicate_content_count) / max(len(raw_results_flat), 1), 2),
            "good_coverage": len(deduped_sources) >= 6 and unique_domains >= 4,
            "primary_sources": sum(1 for item in deduped_sources if item.get("source_type") in {"official", "association", "academic"}),
            "dated_sources": sum(1 for item in deduped_sources if item.get("published_at") or item.get("last_updated")),
            "stop_reason": stop_reason,
        }
        warnings = _build_warnings(coverage_summary, contradictions)
        gaps = _build_gaps(coverage_summary)
        results_summary = {"raw_results": len(raw_results_flat), "deduped_sources": len(deduped_sources), "extracted_pages": extracted_pages, "failed_extractions": failed_extractions}
        return {
            "full_results_by_subquery": results_by_subquery,
            "results_by_subquery": _preview_results_by_subquery(results_by_subquery),
            "raw_results_flat": raw_results_flat,
            "deduped_sources": deduped_sources,
            "top_sources": top_sources,
            "usage_rows": usage_rows,
            "all_searches_cached": all_searches_cached and bool(usage_rows),
            "stop_reason": stop_reason,
            "coverage_summary": coverage_summary,
            "findings": _build_findings(top_sources),
            "gaps_or_uncertainties": gaps,
            "warnings": warnings,
            "clusters": clusters,
            "contradictions": contradictions,
            "suggested_next_steps": _build_next_steps(state["intent"]),
            "results_summary": results_summary,
        }

    def finalize(state: ResearchGraphState) -> ResearchGraphState:
        started_at = datetime.fromisoformat(state["started_at"])
        usage = _aggregate_usage(state.get("usage_rows") or [], run_id=state["run_id"], max_searches=state["max_searches_resolved"], execution_cost_cap_usd=state["execution_cost_cap_usd"], budget=budget)
        metrics = {
            "duration_seconds": round((datetime.now(timezone.utc) - started_at).total_seconds(), 3),
            "provider_search_cost_usd": usage["provider_search_cost_usd"],
            "provider_extraction_cost_usd": 0.0,
            "total_cost_usd": usage["total_cost_usd"],
            "cost_cap_usd": state["execution_cost_cap_usd"],
            "cost_source": usage["cost_source"] or "estimated",
        }
        budget_snapshot = {"month_total_usd": usage["month_total_usd"], "today_total_usd": usage["today_total_usd"], "last_run_cost_usd": usage["last_run_cost_usd"]}
        summary = f"Collected {state.get('coverage_summary', {}).get('unique_sources', 0)} deduplicated sources across {len(state.get('full_results_by_subquery') or {})} search passes; stop reason: {state.get('stop_reason', 'unknown')}."
        top_sources = [SearchResult.model_validate(item) for item in state.get("top_sources") or []]
        preview_results = {query: [SearchResult.model_validate(item) for item in items] for query, items in (state.get("results_by_subquery") or {}).items()}
        full_results = {query: [SearchResult.model_validate(item) for item in items] for query, items in (state.get("full_results_by_subquery") or {}).items()}
        deduped_sources = [SearchResult.model_validate(item) for item in state.get("deduped_sources") or []]
        full_payload_model = ResearchWorkflowResult(
            run_id=state["run_id"],
            query=state["question"],
            question=state["question"],
            intent=state["intent"],
            mode_requested=state["mode_requested"],
            mode_used=state["mode_used"],
            input=state.get("input_flags") or {},
            search_strategy=state["search_strategy"],
            min_searches=state["min_searches"],
            max_searches=state["max_searches_resolved"],
            search_calls=len(state.get("usage_rows") or []),
            search_plan={"subqueries": state.get("subqueries") or [], "search_calls": len(state.get("usage_rows") or []), "providers": usage["providers"]},
            results=state.get("results_summary") or {},
            subqueries=state.get("subqueries") or [],
            subtopics=state.get("subqueries") or [],
            results_by_subquery=full_results,
            deduped_sources=deduped_sources,
            top_sources=top_sources,
            sources=top_sources,
            clusters=[ResearchCluster.model_validate(item) for item in state.get("clusters") or []],
            contradictions=[ResearchContradiction.model_validate(item) for item in state.get("contradictions") or []],
            coverage_summary=state.get("coverage_summary") or {},
            findings=state.get("findings") or [],
            gaps_or_uncertainties=state.get("gaps_or_uncertainties") or [],
            gaps=state.get("gaps_or_uncertainties") or [],
            warnings=state.get("warnings") or [],
            suggested_next_steps=state.get("suggested_next_steps") or [],
            usage=usage,
            metrics=metrics,
            budget=budget_snapshot,
            storage={"full_payload_stored": True, "full_payload_ref": state["run_id"]},
            raw_evidence_preview=build_raw_evidence_preview(state.get("raw_results_flat") or []),
            cached=bool(state.get("all_searches_cached", False)),
            summary=summary,
            depth=state["mode_requested"],
        )
        full_payload = full_payload_model.model_dump()
        store.store(state["run_id"], full_payload, plan_hash=state["plan_hash"])
        envelope = {**full_payload, "results_by_subquery": {query: [item.model_dump() for item in items] for query, items in preview_results.items()}, "deduped_sources": [item.model_dump() for item in top_sources], "sources": [item.model_dump() for item in top_sources]}
        _log_event("research_run_completed", run_id=state["run_id"], search_calls=len(state.get("usage_rows") or []), deduped_sources=len(deduped_sources), extracted_pages=state.get("results_summary", {}).get("extracted_pages", 0), failed_extractions=state.get("results_summary", {}).get("failed_extractions", 0), total_cost=metrics["total_cost_usd"], stop_reason=state.get("stop_reason"))
        return {"full_payload": full_payload, "result": full_payload if state.get("return_full_payload") else envelope}

    graph = StateGraph(ResearchGraphState)
    graph.add_node("classify_and_plan", classify_and_plan)
    graph.add_node("gather_evidence", gather_evidence)
    graph.add_node("finalize", finalize)
    graph.add_edge(START, "classify_and_plan")
    graph.add_edge("classify_and_plan", "gather_evidence")
    graph.add_edge("gather_evidence", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile()
