from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from automation_intel_mcp.mcp_transport import configure_streamable_http_server
from automation_intel_mcp.research_server import mcp as research_mcp


class McpTransportTests(unittest.TestCase):
    def test_configure_streamable_http_server_sets_network_settings(self) -> None:
        configure_streamable_http_server(
            research_mcp,
            host="0.0.0.0",
            port=9000,
            path="/custom-mcp",
            public_base_url="https://research.example.com",
            stateless_http=True,
            json_response=False,
        )
        self.assertEqual(research_mcp.settings.host, "0.0.0.0")
        self.assertEqual(research_mcp.settings.port, 9000)
        self.assertEqual(research_mcp.settings.streamable_http_path, "/custom-mcp")
        self.assertTrue(research_mcp.settings.stateless_http)
        self.assertIn("research.example.com", research_mcp.settings.transport_security.allowed_hosts)
        self.assertIn("https://research.example.com", research_mcp.settings.transport_security.allowed_origins)


if __name__ == "__main__":
    unittest.main()
