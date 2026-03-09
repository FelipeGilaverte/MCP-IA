from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    perplexity_api_key: str | None = Field(default=None, alias="PERPLEXITY_API_KEY")
    perplexity_default_model: str = Field(default="sonar-pro", alias="PERPLEXITY_DEFAULT_MODEL")
    perplexity_deep_model: str = Field(default="sonar-deep-research", alias="PERPLEXITY_DEEP_MODEL")
    perplexity_estimated_raw_search_cost_usd: float = Field(default=0.005, alias="PERPLEXITY_ESTIMATED_RAW_SEARCH_COST_USD")
    perplexity_estimated_quick_search_cost_usd: float = Field(default=0.01, alias="PERPLEXITY_ESTIMATED_QUICK_SEARCH_COST_USD")
    perplexity_estimated_deep_search_cost_usd: float = Field(default=0.03, alias="PERPLEXITY_ESTIMATED_DEEP_SEARCH_COST_USD")
    perplexity_raw_search_max_results: int = Field(default=10, alias="PERPLEXITY_RAW_SEARCH_MAX_RESULTS")

    enable_premium_research_tools: bool = Field(default=False, alias="ENABLE_PREMIUM_RESEARCH_TOOLS")
    perplexity_deep_search_premium_label: str = Field(default="premium_expensive", alias="PERPLEXITY_DEEP_SEARCH_PREMIUM_LABEL")

    google_maps_api_key: str | None = Field(default=None, alias="GOOGLE_MAPS_API_KEY")
    google_places_language_code: str = Field(default="pt-BR", alias="GOOGLE_PLACES_LANGUAGE_CODE")
    google_places_region_code: str = Field(default="BR", alias="GOOGLE_PLACES_REGION_CODE")

    budget_soft_limit_usd: float = Field(default=6.0, alias="BUDGET_SOFT_LIMIT_USD")
    budget_hard_limit_usd: float = Field(default=9.0, alias="BUDGET_HARD_LIMIT_USD")

    cache_enabled: bool = Field(default=True, alias="CACHE_ENABLED")
    cache_dir: Path = Field(default=Path(".cache"), alias="CACHE_DIR")
    cache_ttl_hours: int = Field(default=168, alias="CACHE_TTL_HOURS")

    mcp_stateless_http: bool = Field(default=True, alias="MCP_STATELESS_HTTP")
    mcp_json_response: bool = Field(default=False, alias="MCP_JSON_RESPONSE")
    research_mcp_http_host: str = Field(default="127.0.0.1", alias="RESEARCH_MCP_HTTP_HOST")
    research_mcp_http_port: int = Field(default=8000, alias="RESEARCH_MCP_HTTP_PORT")
    research_mcp_http_path: str = Field(default="/mcp", alias="RESEARCH_MCP_HTTP_PATH")
    research_mcp_public_base_url: str | None = Field(default=None, alias="RESEARCH_MCP_PUBLIC_BASE_URL")
    agency_mcp_http_host: str = Field(default="127.0.0.1", alias="AGENCY_MCP_HTTP_HOST")
    agency_mcp_http_port: int = Field(default=8001, alias="AGENCY_MCP_HTTP_PORT")
    agency_mcp_http_path: str = Field(default="/mcp", alias="AGENCY_MCP_HTTP_PATH")
    agency_mcp_public_base_url: str | None = Field(default=None, alias="AGENCY_MCP_PUBLIC_BASE_URL")

    request_timeout_seconds: float = Field(default=30.0, alias="REQUEST_TIMEOUT_SECONDS")
    request_max_retries: int = Field(default=2, alias="REQUEST_MAX_RETRIES")
    default_max_output_tokens: int = Field(default=1200, alias="DEFAULT_MAX_OUTPUT_TOKENS")
    default_deep_max_output_tokens: int = Field(default=2400, alias="DEFAULT_DEEP_MAX_OUTPUT_TOKENS")

    agency_enable_external_research: bool = Field(default=False, alias="AGENCY_ENABLE_EXTERNAL_RESEARCH")
    agency_external_research_default_mode: str = Field(default="auto", alias="AGENCY_EXTERNAL_RESEARCH_DEFAULT_MODE")
    agency_external_research_max_mode: str = Field(default="standard", alias="AGENCY_EXTERNAL_RESEARCH_MAX_MODE")

    research_default_mode: str = Field(default="auto", alias="RESEARCH_DEFAULT_MODE")
    research_auto_min_searches: int = Field(default=3, alias="RESEARCH_AUTO_MIN_SEARCHES")
    research_auto_soft_target_searches: int = Field(default=6, alias="RESEARCH_AUTO_SOFT_TARGET_SEARCHES")
    research_auto_max_searches: int = Field(default=8, alias="RESEARCH_AUTO_MAX_SEARCHES")
    research_quick_max_searches: int = Field(default=4, alias="RESEARCH_QUICK_MAX_SEARCHES")
    research_standard_max_searches: int = Field(default=8, alias="RESEARCH_STANDARD_MAX_SEARCHES")
    research_deep_max_searches: int = Field(default=15, alias="RESEARCH_DEEP_MAX_SEARCHES")
    research_exhaustive_max_searches: int = Field(default=40, alias="RESEARCH_EXHAUSTIVE_MAX_SEARCHES")
    research_default_execution_cost_cap_usd: float = Field(default=0.04, alias="RESEARCH_DEFAULT_EXECUTION_COST_CAP_USD")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
