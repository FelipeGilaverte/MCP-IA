from __future__ import annotations

AGENCY_BUSINESS_TEMPLATES = [
    "commercial implications of: {q}",
    "buyer concerns and objections for: {q}",
    "pricing and packaging signals for: {q}",
    "market demand indicators for: {q}",
    "competitive alternatives for: {q}",
    "switching costs and migration concerns for: {q}",
]


def build_agency_business_queries(question: str, max_queries: int) -> list[str]:
    cleaned = question.strip().rstrip("?")
    queries: list[str] = []
    for template in AGENCY_BUSINESS_TEMPLATES:
        candidate = template.format(q=cleaned)
        if candidate not in queries:
            queries.append(candidate)
        if len(queries) >= max_queries:
            break
    return queries
