from __future__ import annotations

import hashlib
import re
from html import unescape

import httpx
import trafilatura

from automation_intel_mcp.config import Settings
from automation_intel_mcp.models import UrlExtractionResult, WebPageSnapshot
from automation_intel_mcp.services.cache import FileCache
from automation_intel_mcp.services.research_features import canonicalize_url, classify_language, extraction_quality

_SCRIPT_STYLE_PATTERN = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAG_PATTERN = re.compile(r"<[^>]+>")
_META_DESCRIPTION_PATTERN = re.compile(
    r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
    re.IGNORECASE | re.DOTALL,
)
_CANONICAL_PATTERN = re.compile(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\'](.*?)["\']', re.IGNORECASE | re.DOTALL)
_TITLE_PATTERN = re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_LANG_PATTERN = re.compile(r"<html[^>]+lang=[\"'](.*?)[\"']", re.IGNORECASE | re.DOTALL)
_PUBLISHED_META_PATTERNS = [
    re.compile(pattern, re.IGNORECASE | re.DOTALL)
    for pattern in [
        r'<meta[^>]+property=["\']article:published_time["\'][^>]+content=["\'](.*?)["\']',
        r'<meta[^>]+name=["\']date["\'][^>]+content=["\'](.*?)["\']',
        r'<meta[^>]+itemprop=["\']datePublished["\'][^>]+content=["\'](.*?)["\']',
    ]
]
_UPDATED_META_PATTERNS = [
    re.compile(pattern, re.IGNORECASE | re.DOTALL)
    for pattern in [
        r'<meta[^>]+property=["\']article:modified_time["\'][^>]+content=["\'](.*?)["\']',
        r'<meta[^>]+name=["\']last-modified["\'][^>]+content=["\'](.*?)["\']',
        r'<meta[^>]+itemprop=["\']dateModified["\'][^>]+content=["\'](.*?)["\']',
    ]
]
_WHITESPACE_PATTERN = re.compile(r"\s+")


class WebFetcher:
    def __init__(self, settings: Settings, cache: FileCache) -> None:
        self.settings = settings
        self.cache = cache

    @staticmethod
    def _fallback_extract(html: str) -> str:
        cleaned = _SCRIPT_STYLE_PATTERN.sub(" ", html)
        cleaned = _TAG_PATTERN.sub(" ", cleaned)
        cleaned = unescape(cleaned)
        return _WHITESPACE_PATTERN.sub(" ", cleaned).strip()

    def _request(self, url: str) -> httpx.Response:
        headers = {
            "User-Agent": "automation-intel-mcp/0.1 (+https://local.app)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        }
        last_error: Exception | None = None
        for attempt in range(self.settings.request_max_retries + 1):
            try:
                with httpx.Client(
                    timeout=self.settings.request_timeout_seconds,
                    follow_redirects=True,
                    headers=headers,
                ) as client:
                    response = client.get(url)
                    response.raise_for_status()
                    return response
            except Exception as exc:
                last_error = exc
                if attempt >= self.settings.request_max_retries:
                    break
        assert last_error is not None
        raise last_error

    def fetch_page(self, url: str) -> WebPageSnapshot:
        cache_key = {"endpoint": "fetch_page", "url": url}
        cached = self.cache.get(cache_key)
        if cached is not None:
            cached["cached"] = True
            return WebPageSnapshot.model_validate(cached)

        response = self._request(url)
        html = response.text
        extracted = trafilatura.extract(html, include_comments=False, include_links=True) or ""
        if not extracted.strip():
            extracted = self._fallback_extract(html)

        title_match = _TITLE_PATTERN.search(html)
        meta_description_match = _META_DESCRIPTION_PATTERN.search(html)
        canonical_match = _CANONICAL_PATTERN.search(html)
        html_lang_match = _LANG_PATTERN.search(html)
        published_at = next((match.group(1).strip() for pattern in _PUBLISHED_META_PATTERNS if (match := pattern.search(html))), None)
        last_updated = next((match.group(1).strip() for pattern in _UPDATED_META_PATTERNS if (match := pattern.search(html))), None)
        main_text = extracted.strip()
        snapshot = WebPageSnapshot(
            url=url,
            canonical_url=canonicalize_url(canonical_match.group(1).strip() if canonical_match else str(response.url)),
            status_code=response.status_code,
            final_url=str(response.url),
            html=html,
            title=title_match.group(1).strip() if title_match else None,
            meta_description=meta_description_match.group(1).strip() if meta_description_match else None,
            extraction_quality=extraction_quality(main_text),
            content_length_chars=len(main_text),
            language=classify_language(html_lang_match.group(1).strip() if html_lang_match else None, main_text),
            published_at=published_at,
            last_updated=last_updated,
            main_text=main_text,
            content_hash=hashlib.sha256(main_text.encode("utf-8")).hexdigest() if main_text else None,
            extracted_text=extracted,
            excerpt=extracted[:800],
            cached=False,
        )
        self.cache.set(cache_key, snapshot.model_dump())
        return snapshot

    def fetch_and_extract(self, url: str) -> UrlExtractionResult:
        return self.fetch_page(url).to_extraction_result()
