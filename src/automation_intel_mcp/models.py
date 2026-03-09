from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class SearchResult(BaseModel):
    title: str
    url: str
    canonical_url: str | None = None
    snippet: str | None = None
    source_type: str | None = None
    date: str | None = None
    published_at: str | None = None
    last_updated: str | None = None
    relevance_score: float | None = None
    credibility_score: float | None = None
    freshness_score: float | None = None
    final_score: float | None = None
    evidence_strength: str | None = None
    extraction_quality: str | None = None
    key_points: list[str] = Field(default_factory=list)
    content_hash: str | None = None
    source: str | None = None


class ResearchCluster(BaseModel):
    topic: str
    source_count: int = 0
    top_urls: list[str] = Field(default_factory=list)


class ResearchContradiction(BaseModel):
    topic: str
    claim_a: str
    source_a: str
    claim_b: str
    source_b: str
    notes: str = ""


class CostRecord(BaseModel):
    provider: str
    operation: str
    billed_cost_usd: float
    actual_cost_usd: float | None = None
    estimated_cost_usd: float | None = None
    cost_source: str
    month_total_usd: float
    soft_limit_reached: bool
    hard_limit_reached: bool
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResearchResponse(BaseModel):
    mode: str
    model: str
    answer: str
    citations: list[str] = Field(default_factory=list)
    search_results: list[SearchResult] = Field(default_factory=list)
    usage: dict[str, Any] = Field(default_factory=dict)
    cached: bool = False


class ResearchWorkflowResult(BaseModel):
    run_id: str | None = None
    query: str
    intent: str
    mode_requested: str
    mode_used: str
    input: dict[str, Any] = Field(default_factory=dict)
    search_strategy: str
    min_searches: int
    max_searches: int
    search_calls: int
    search_plan: dict[str, Any] = Field(default_factory=dict)
    results: dict[str, Any] = Field(default_factory=dict)
    subqueries: list[str] = Field(default_factory=list)
    results_by_subquery: dict[str, list[SearchResult]] = Field(default_factory=dict)
    deduped_sources: list[SearchResult] = Field(default_factory=list)
    top_sources: list[SearchResult] = Field(default_factory=list)
    clusters: list[ResearchCluster] = Field(default_factory=list)
    contradictions: list[ResearchContradiction] = Field(default_factory=list)
    coverage_summary: dict[str, Any] = Field(default_factory=dict)
    findings: list[str] = Field(default_factory=list)
    gaps_or_uncertainties: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    suggested_next_steps: list[str] = Field(default_factory=list)
    usage: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)
    budget: dict[str, Any] = Field(default_factory=dict)
    storage: dict[str, Any] = Field(default_factory=dict)
    raw_evidence_preview: list[dict[str, str]] = Field(default_factory=list)
    cached: bool = False
    question: str | None = None
    summary: str = ""
    sources: list[SearchResult] = Field(default_factory=list)
    subtopics: list[str] = Field(default_factory=list)
    depth: str | None = None


class UrlExtractionResult(BaseModel):
    url: str
    canonical_url: str | None = None
    status_code: int
    final_url: str
    title: str | None = None
    meta_description: str | None = None
    extraction_quality: str = "low"
    content_length_chars: int = 0
    language: str | None = None
    published_at: str | None = None
    last_updated: str | None = None
    main_text: str = ""
    content_hash: str | None = None
    extracted_text: str = ""
    excerpt: str = ""
    fetched_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class WebPageSnapshot(BaseModel):
    url: str
    canonical_url: str | None = None
    status_code: int
    final_url: str
    html: str
    title: str | None = None
    meta_description: str | None = None
    extraction_quality: str = "low"
    content_length_chars: int = 0
    language: str | None = None
    published_at: str | None = None
    last_updated: str | None = None
    main_text: str = ""
    content_hash: str | None = None
    extracted_text: str = ""
    excerpt: str = ""
    fetched_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    cached: bool = False

    def to_extraction_result(self) -> UrlExtractionResult:
        return UrlExtractionResult(
            url=self.url,
            canonical_url=self.canonical_url,
            status_code=self.status_code,
            final_url=self.final_url,
            title=self.title,
            meta_description=self.meta_description,
            extraction_quality=self.extraction_quality,
            content_length_chars=self.content_length_chars,
            language=self.language,
            published_at=self.published_at,
            last_updated=self.last_updated,
            main_text=self.main_text,
            content_hash=self.content_hash,
            extracted_text=self.extracted_text,
            excerpt=self.excerpt,
            fetched_at=self.fetched_at,
        )


class NicheScore(BaseModel):
    niche: str
    score: int
    breakdown: dict[str, int]
    reasoning: list[str]


class SiteContactInfo(BaseModel):
    emails: list[str] = Field(default_factory=list)
    phones: list[str] = Field(default_factory=list)
    whatsapp_numbers: list[str] = Field(default_factory=list)
    whatsapp_links: list[str] = Field(default_factory=list)


class SiteFormField(BaseModel):
    name: str | None = None
    field_type: str = "text"
    label: str | None = None
    required: bool = False


class SiteForm(BaseModel):
    action: str | None = None
    method: str = "get"
    purpose: str = "unknown"
    submit_text: str | None = None
    fields: list[SiteFormField] = Field(default_factory=list)


class SiteCTA(BaseModel):
    text: str = ""
    href: str | None = None
    source: str = "unknown"
    confidence: float = 0.0


class ImportantPage(BaseModel):
    title: str
    url: str | None = None
    reason: str


class SiteArtifacts(BaseModel):
    contacts: SiteContactInfo = Field(default_factory=SiteContactInfo)
    forms: list[SiteForm] = Field(default_factory=list)
    primary_cta: SiteCTA | None = None
    important_pages: list[ImportantPage] = Field(default_factory=list)
    service_signals: list[str] = Field(default_factory=list)


class DigitalMaturity(BaseModel):
    level: str
    score: int
    signals: list[str] = Field(default_factory=list)
    summary: str


class PainCategories(BaseModel):
    comercial: list[str] = Field(default_factory=list)
    operacional: list[str] = Field(default_factory=list)
    atendimento: list[str] = Field(default_factory=list)
    marketing: list[str] = Field(default_factory=list)


class CompanyAnalysis(BaseModel):
    company_name: str
    company_url: str
    niche: str | None = None
    company_summary: str
    contact_points: SiteContactInfo = Field(default_factory=SiteContactInfo)
    digital_maturity: DigitalMaturity | None = None
    pain_points: list[str] = Field(default_factory=list)
    pain_categories: PainCategories = Field(default_factory=PainCategories)
    automation_opportunities: list[str] = Field(default_factory=list)
    offer: str
    outreach: dict[str, Any] = Field(default_factory=dict)
    confidence_notes: list[str] = Field(default_factory=list)
    important_pages: list[ImportantPage] = Field(default_factory=list)
    services_or_products: list[str] = Field(default_factory=list)
    primary_cta: SiteCTA | None = None
    forms: list[SiteForm] = Field(default_factory=list)
    external_research: ResearchWorkflowResult | None = None
    external_research_used: bool = False
    external_research_mode: str | None = None
    external_research_search_calls: int = 0
    external_research_cost_usd: float | None = None
    usage: dict[str, Any] = Field(default_factory=dict)
    summary: str | None = None
    likely_pains: list[str] = Field(default_factory=list)
    suggested_offer: str | None = None
    contacts: SiteContactInfo = Field(default_factory=SiteContactInfo)


class GeoPoint(BaseModel):
    latitude: float
    longitude: float


class LocalBusiness(BaseModel):
    name: str
    address: str | None = None
    website: str | None = None
    phone: str | None = None
    rating: float | None = None
    total_reviews: int | None = None
    distance_meters: int | None = None


class LocalBusinessSearchResponse(BaseModel):
    niche: str
    city: str
    radius_meters: int
    center: GeoPoint
    results: list[LocalBusiness] = Field(default_factory=list)
    cached: bool = False


class OfferChannelVariants(BaseModel):
    whatsapp: str
    email_subject: str
    email_body: str
    discovery_call: str


class CommercialOffer(BaseModel):
    niche: str
    pain: str
    solution: str
    desired_ticket: str
    urgency_level: str
    promise: str
    deliverables: list[str] = Field(default_factory=list)
    probable_objections: list[str] = Field(default_factory=list)
    roi_argument: str
    final_cta: str
    channel_versions: OfferChannelVariants


class OutreachDraft(BaseModel):
    channel: str
    subject: str | None = None
    message: str
