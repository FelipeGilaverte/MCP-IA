from __future__ import annotations

import re
from html import unescape

import httpx
import trafilatura

from automation_intel_mcp.config import Settings
from automation_intel_mcp.models import UrlExtractionResult, WebPageSnapshot
from automation_intel_mcp.services.cache import FileCache

_SCRIPT_STYLE_PATTERN = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAG_PATTERN = re.compile(r"<[^>]+>")
_META_DESCRIPTION_PATTERN = re.compile(
    r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
    re.IGNORECASE | re.DOTALL,
)
_TITLE_PATTERN = re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL)
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
        snapshot = WebPageSnapshot(
            url=url,
            status_code=response.status_code,
            final_url=str(response.url),
            html=html,
            title=title_match.group(1).strip() if title_match else None,
            meta_description=meta_description_match.group(1).strip() if meta_description_match else None,
            extracted_text=extracted,
            excerpt=extracted[:800],
            cached=False,
        )
        self.cache.set(cache_key, snapshot.model_dump())
        return snapshot

    def fetch_and_extract(self, url: str) -> UrlExtractionResult:
        return self.fetch_page(url).to_extraction_result()
