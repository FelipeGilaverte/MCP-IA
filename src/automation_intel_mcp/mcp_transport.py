from __future__ import annotations

from urllib.parse import urlparse

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

LOCAL_ALLOWED_HOSTS = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
LOCAL_ALLOWED_ORIGINS = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]


def _normalize_path(path: str) -> str:
    if not path:
        return "/mcp"
    return path if path.startswith("/") else f"/{path}"


def _build_transport_security(host: str, port: int, public_base_url: str | None) -> TransportSecuritySettings:
    allowed_hosts = list(LOCAL_ALLOWED_HOSTS)
    allowed_origins = list(LOCAL_ALLOWED_ORIGINS)

    if public_base_url:
        parsed = urlparse(public_base_url)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError("public_base_url must include scheme and host, e.g. https://example.com")
        allowed_hosts.append(parsed.netloc)
        allowed_origins.append(f"{parsed.scheme}://{parsed.netloc}")
    elif host not in {"127.0.0.1", "localhost", "::1", "[::1]", "0.0.0.0"}:
        allowed_hosts.extend([host, f"{host}:{port}"])
        allowed_origins.extend([f"http://{host}:{port}", f"https://{host}:{port}"])

    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=list(dict.fromkeys(allowed_hosts)),
        allowed_origins=list(dict.fromkeys(allowed_origins)),
    )


def configure_streamable_http_server(
    mcp: FastMCP,
    *,
    host: str,
    port: int,
    path: str = "/mcp",
    public_base_url: str | None = None,
    stateless_http: bool = True,
    json_response: bool = False,
) -> None:
    mcp.settings.host = host
    mcp.settings.port = port
    mcp.settings.streamable_http_path = _normalize_path(path)
    mcp.settings.stateless_http = stateless_http
    mcp.settings.json_response = json_response
    mcp.settings.transport_security = _build_transport_security(host, port, public_base_url)
