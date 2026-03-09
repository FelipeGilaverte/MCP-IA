from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

SOURCE_TYPES = {
    "official",
    "association",
    "vendor",
    "news",
    "academic",
    "consulting",
    "directory",
    "blog",
}

TOPIC_KEYWORDS: dict[str, list[str]] = {
    "market_size": ["market size", "tam", "mercado", "size", "volume"],
    "growth": ["growth", "cagr", "crescimento", "expansão", "expansion"],
    "adoption": ["adoption", "adoption rate", "adoption", "adoção", "usage"],
    "pain_points": ["pain point", "challenge", "problema", "dor", "bottleneck", "friction"],
    "vendors": ["vendor", "provider", "supplier", "player", "empresa", "plataforma"],
    "pricing": ["pricing", "price", "preço", "plan", "plano", "subscription"],
    "trends": ["trend", "trends", "tendência", "forecast", "outlook"],
    "risks": ["risk", "risco", "uncertainty", "barrier", "constraint"],
    "case_studies": ["case study", "customer story", "estudo de caso", "success story"],
    "regulation": ["regulation", "compliance", "lei", "legal", "policy", "norma"],
    "operations": ["operations", "operational", "workflow", "processo", "process"],
    "delivery": ["delivery", "implementation", "deployment", "serviço", "service"],
    "technology": ["technology", "ai", "software", "stack", "platform", "api"],
}

PROMOTIONAL_HINTS = [
    "demo",
    "teste grátis",
    "free trial",
    "saiba mais",
    "agende uma demo",
    "book a demo",
    "fale com vendas",
    "talk to sales",
]

STOPWORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "da",
    "de",
    "do",
    "e",
    "for",
    "in",
    "na",
    "no",
    "o",
    "of",
    "or",
    "para",
    "the",
    "to",
    "uma",
    "um",
}

_WHITESPACE_RE = re.compile(r"\s+")
_WORD_RE = re.compile(r"[a-z0-9]{3,}", re.IGNORECASE)
_NUMBER_RE = re.compile(r"\b\d+(?:[.,]\d+)?%?\b")


def normalize_text(value: str | None) -> str:
    return _WHITESPACE_RE.sub(" ", (value or "").strip()).lower()


def canonicalize_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url.strip())
    if not parsed.scheme or not parsed.netloc:
        return url
    query = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if not k.lower().startswith("utm_")]
    normalized = parsed._replace(
        scheme=parsed.scheme.lower(),
        netloc=parsed.netloc.lower(),
        fragment="",
        query=urlencode(query, doseq=True),
    )
    return urlunparse(normalized)


def content_hash(text: str | None) -> str | None:
    normalized = normalize_text(text)
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def classify_source_type(url: str | None, title: str | None = None, snippet: str | None = None) -> str:
    normalized_url = normalize_text(url)
    normalized_title = normalize_text(title)
    normalized_snippet = normalize_text(snippet)
    combined = " ".join([normalized_url, normalized_title, normalized_snippet]).strip()

    if any(token in normalized_url for token in [".gov", ".gob", ".edu", ".ac.", ".org.br"]) or any(
        token in combined for token in ["ministry", "government", "universidade", "university", "instituto", "federal"]
    ):
        return "official" if ".gov" in normalized_url or "government" in combined or "ministry" in combined else "academic"
    if any(token in combined for token in ["association", "associação", "federation", "sociedade", "consortium"]):
        return "association"
    if any(token in combined for token in ["gartner", "mckinsey", "bcg", "bain", "accenture", "deloitte", "pwc", "kpmg"]):
        return "consulting"
    if any(token in normalized_url for token in ["news", "noticias", "globo", "reuters", "forbes", "techcrunch"]) or any(
        token in combined for token in ["newsroom", "breaking", "reportagem", "report"]
    ):
        return "news"
    if any(token in combined for token in ["directory", "listing", "marketplace", "capterra", "g2", "clutch"]):
        return "directory"
    if any(token in combined for token in ["blog", "medium.com", "/blog", "substack"]):
        return "blog"
    return "vendor"


def extraction_quality(text: str | None) -> str:
    length = len((text or "").strip())
    if length >= 4000:
        return "high"
    if length >= 1200:
        return "medium"
    return "low"


def tokenize_query_terms(*values: str | None) -> list[str]:
    tokens: list[str] = []
    for value in values:
        for token in _WORD_RE.findall((value or "").lower()):
            if token not in STOPWORDS and token not in tokens:
                tokens.append(token)
    return tokens


def score_relevance(query_terms: list[str], *values: str | None) -> float:
    if not query_terms:
        return 0.3
    haystack = normalize_text(" ".join(value or "" for value in values))
    hits = sum(1 for term in query_terms if term in haystack)
    return round(min(1.0, hits / max(len(query_terms), 1) + 0.1), 3)


def score_credibility(source_type: str, extraction_quality_value: str = "low") -> float:
    base = {
        "official": 0.95,
        "association": 0.85,
        "academic": 0.9,
        "consulting": 0.72,
        "news": 0.68,
        "vendor": 0.55,
        "directory": 0.45,
        "blog": 0.35,
    }.get(source_type, 0.4)
    bonus = {"high": 0.05, "medium": 0.02, "low": 0.0}.get(extraction_quality_value, 0.0)
    return round(min(1.0, base + bonus), 3)


def parse_isoish_date(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    for candidate in [text, text.replace("Z", "+00:00")]:
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except ValueError:
            continue
    return None


def score_freshness(published_at: str | None, last_updated: str | None) -> float:
    dt = parse_isoish_date(last_updated) or parse_isoish_date(published_at)
    if not dt:
        return 0.3
    age_days = max((datetime.now(timezone.utc) - dt).days, 0)
    if age_days <= 30:
        return 1.0
    if age_days <= 180:
        return 0.8
    if age_days <= 365:
        return 0.6
    if age_days <= 730:
        return 0.4
    return 0.2


def score_final(relevance_score: float, credibility_score: float, freshness_score: float) -> float:
    return round((0.5 * relevance_score) + (0.3 * credibility_score) + (0.2 * freshness_score), 3)


def evidence_strength(final_score: float, extraction_quality_value: str) -> str:
    if final_score >= 0.75 and extraction_quality_value != "low":
        return "high"
    if final_score >= 0.45:
        return "medium"
    return "low"


def extract_key_points(*values: str | None) -> list[str]:
    combined = " ".join(value or "" for value in values).strip()
    if not combined:
        return []
    chunks = re.split(r"(?<=[.!?])\s+", combined)
    points: list[str] = []
    for chunk in chunks:
        cleaned = " ".join(chunk.split()).strip(" -")
        if len(cleaned) >= 30 and cleaned not in points:
            points.append(cleaned[:240])
        if len(points) >= 3:
            break
    return points


def title_similarity(left: str | None, right: str | None) -> float:
    return SequenceMatcher(a=normalize_text(left), b=normalize_text(right)).ratio()


def content_similarity(left: str | None, right: str | None) -> float:
    return SequenceMatcher(a=normalize_text(left), b=normalize_text(right)).ratio()


def detect_topics(*values: str | None, focus_topics: list[str] | None = None) -> list[str]:
    haystack = normalize_text(" ".join(value or "" for value in values))
    topics: list[str] = []
    allowed = set(focus_topics or TOPIC_KEYWORDS.keys())
    for topic, keywords in TOPIC_KEYWORDS.items():
        if topic not in allowed:
            continue
        if any(keyword in haystack for keyword in keywords):
            topics.append(topic)
    return topics[:4]


def detect_numeric_claims(*values: str | None) -> list[str]:
    haystack = " ".join(value or "" for value in values)
    return _NUMBER_RE.findall(haystack)


def looks_promotional(*values: str | None) -> bool:
    haystack = normalize_text(" ".join(value or "" for value in values))
    return any(token in haystack for token in PROMOTIONAL_HINTS)


def classify_language(html_lang: str | None, text: str | None) -> str | None:
    if html_lang:
        return html_lang.split("-")[0].lower()
    normalized = normalize_text(text)
    if any(token in normalized for token in [" para ", " com ", " não ", "ção", "ões"]):
        return "pt"
    if any(token in normalized for token in [" the ", " and ", " with ", " for "]):
        return "en"
    return None


def build_raw_evidence_preview(items: list[dict[str, Any]], limit: int = 8) -> list[dict[str, str]]:
    preview: list[dict[str, str]] = []
    for item in items[:limit]:
        preview.append(
            {
                "url": str(item.get("url") or ""),
                "title": str(item.get("title") or ""),
                "excerpt": str(item.get("snippet") or item.get("main_text") or "")[:280],
            }
        )
    return preview
