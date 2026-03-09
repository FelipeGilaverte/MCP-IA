from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from automation_intel_mcp.config import Settings
from automation_intel_mcp.services.cache import FileCache
from automation_intel_mcp.services.web_fetcher import WebFetcher


class _FakeResponse:
    def __init__(self, html: str) -> None:
        self.text = html
        self.status_code = 200
        self.url = "https://example.com/final"


class _FakeFetcher(WebFetcher):
    def __init__(self, settings: Settings, cache: FileCache, html: str) -> None:
        super().__init__(settings, cache)
        self.html = html

    def _request(self, url: str):  # type: ignore[override]
        return _FakeResponse(self.html)


class WebFetcherTests(unittest.TestCase):
    def test_fetch_page_returns_enriched_metadata(self) -> None:
        html = """
        <html lang="pt-BR">
          <head>
            <title>Example title</title>
            <link rel="canonical" href="https://example.com/canonical" />
            <meta name="description" content="Resumo" />
            <meta property="article:published_time" content="2026-03-01T10:00:00Z" />
            <meta property="article:modified_time" content="2026-03-02T10:00:00Z" />
          </head>
          <body>
            <main>
              <p>Este é um conteúdo longo o suficiente para teste de extração.</p>
              <p>Outro parágrafo com texto relevante para o hash de conteúdo.</p>
            </main>
          </body>
        </html>
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            settings = Settings(CACHE_DIR=tmp_dir)
            cache = FileCache(Path(tmp_dir))
            fetcher = _FakeFetcher(settings, cache, html)
            page = fetcher.fetch_page("https://example.com/page")
        self.assertEqual(page.canonical_url, "https://example.com/canonical")
        self.assertEqual(page.language, "pt")
        self.assertEqual(page.published_at, "2026-03-01T10:00:00Z")
        self.assertEqual(page.last_updated, "2026-03-02T10:00:00Z")
        self.assertGreater(page.content_length_chars, 20)
        self.assertTrue(page.content_hash)


if __name__ == "__main__":
    unittest.main()
