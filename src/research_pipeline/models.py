"""
搜索工作流数据模型。
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class SourceTier(str, Enum):
    TIER_1 = "tier1"
    TIER_2 = "tier2"
    TIER_3 = "tier3"
    TIER_4 = "tier4"


class SourceType(str, Enum):
    ANNUAL_REPORT = "annual_report"
    QUARTERLY_REPORT = "quarterly_report"
    EARNINGS_RELEASE = "earnings_release"
    INVESTOR_PRESENTATION = "investor_presentation"
    EXCHANGE_FILING = "exchange_filing"
    OFFICIAL_NEWS = "official_news"
    PRODUCT_PAGE = "product_page"
    GOVERNMENT_REPORT = "government_report"
    REGULATORY_FILING = "regulatory_filing"
    INDUSTRY_REPORT = "industry_report"
    ACADEMIC_PAPER = "academic_paper"
    NEWS_ARTICLE = "news_article"
    BLOG_POST = "blog_post"
    OTHER = "other"


class MimeType(str, Enum):
    HTML = "text/html"
    PDF = "application/pdf"
    PLAIN_TEXT = "text/plain"
    MARKDOWN = "text/markdown"
    JSON = "application/json"
    UNKNOWN = "unknown"


class FetchStatus(str, Enum):
    PENDING = "pending"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"


class ParseStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    PENDING = "pending"


class ParseQuality(str, Enum):
    UNKNOWN = "unknown"
    USABLE = "usable"
    DEGRADED = "degraded"
    FAILED = "failed"


class TablePreservation(str, Enum):
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"
    PARTIAL = "partial"
    PRESERVED = "preserved"


class EvidenceType(str, Enum):
    QUANTITATIVE = "quantitative"
    QUALITATIVE = "qualitative"
    NUMERIC_TABLE = "numeric_table"
    FORECAST = "forecast"
    POLICY_TARGET = "policy_target"
    MANAGEMENT_STATEMENT = "management_statement"
    THIRD_PARTY_CLAIM = "third_party_claim"


class RecordLevel(str, Enum):
    """证据层级标记：区分原子事实与研究证据。"""
    ATOMIC_FACT = "atomic_fact"               # 单个数据点，如"收入为X"
    RESEARCH_EVIDENCE = "research_evidence"    # 聚合后可用于论证的完整证据
    MANAGEMENT_STATEMENT = "management_statement"  # 管理层评论
    FORECAST = "forecast"                      # 预测或指引


class TopicEnum(str, Enum):
    """受控 topic 枚举，模型只能选这些值。"""
    REVENUE_STRUCTURE = "revenue_structure"
    DELIVERY_AND_ASP = "delivery_and_asp"
    GROSS_MARGIN = "gross_margin"
    SERVICES_AND_OTHER = "services_and_other"
    TECHNOLOGY_MONETIZATION = "technology_monetization"
    FUTURE_GROWTH_DRIVERS = "future_growth_drivers"
    RISKS_AND_COUNTER_EVIDENCE = "risks_and_counterevidence"
    CORPORATE_GOVERNANCE = "corporate_governance"
    BALANCE_SHEET = "balance_sheet"
    CASH_FLOW = "cash_flow"
    OPERATING_METRICS = "operating_metrics"
    OTHER = "other"


class FetchRecord(BaseModel):
    http_status: Optional[int] = None
    final_url: Optional[str] = None
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    fetch_duration_ms: Optional[int] = None
    error_message: Optional[str] = None
    user_agent: Optional[str] = None
    used_browser: bool = False


class DocumentRecord(BaseModel):
    document_id: str
    project_id: str
    entity_name: str
    title: str
    publisher: Optional[str] = None
    author: Optional[str] = None
    published_at: Optional[str] = None
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source_url: str
    final_url: Optional[str] = None
    source_type: SourceType
    source_tier: SourceTier
    mime_type: MimeType
    language: Optional[str] = None
    raw_path: Optional[str] = None
    parsed_path: Optional[str] = None
    content_hash: str
    text: str
    text_length: int = 0
    fetch_record: Optional[FetchRecord] = None
    fetch_status: FetchStatus = FetchStatus.PENDING
    parse_status: ParseStatus = ParseStatus.PENDING
    parse_quality: ParseQuality = ParseQuality.UNKNOWN
    table_preservation: TablePreservation = TablePreservation.UNKNOWN
    ocr_used: bool = False
    manual_review_required: bool = False
    quality_signals: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    document_schema_version: str = "0.3.0"

    def model_post_init(self, __context: Any) -> None:
        self.text_length = len(self.text)


class NumericValue(BaseModel):
    value: str
    unit: Optional[str] = None
    currency: Optional[str] = None
    time_range: Optional[str] = None
    metric_name: Optional[str] = None
    scope: Optional[str] = None
    notes: Optional[str] = None


class ProjectConfig(BaseModel):
    project_id: str
    entity: EntityConfig
    research_question: str
    time_range: TimeRangeConfig
    source_policy: SourcePolicyConfig
    seed_urls: list[str] = Field(default_factory=list)
    analysis_modules: list[str] = Field(default_factory=list)


class EntityConfig(BaseModel):
    name: str
    aliases: list[str] = Field(default_factory=list)


class TimeRangeConfig(BaseModel):
    start: Optional[str] = None
    end: Optional[str] = None


class SourcePolicyConfig(BaseModel):
    allowed_domains: list[str] = Field(default_factory=list)
    blocked_domains: list[str] = Field(default_factory=list)
    source_types: list[str] = Field(default_factory=list)
    priority: list[str] = Field(default_factory=list)


class IngestStats(BaseModel):
    project_id: str
    total_urls: int = 0
    fetched: int = 0
    failed: int = 0
    skipped: int = 0
    parsed_html: int = 0
    parsed_pdf: int = 0
    parse_failed: int = 0
    duplicates_removed: int = 0
    total_documents: int = 0
    evidence_cards: int = 0
    llm_calls: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    total_duration_ms: int = 0
    tier_breakdown: dict[str, int] = Field(default_factory=dict)


class SchemaVersion(BaseModel):
    document_schema_version: str = "0.2.0"
    evidence_schema_version: str = "0.1.0"
    chunk_schema_version: str = "0.1.0"
    manifest_schema_version: str = "0.1.0"


PARSER_INFO: dict[str, str] = {
    "html_primary": "trafilatura",
    "html_fallback": "BeautifulSoup+lxml",
    "pdf_primary": "pdfplumber",
    "pdf_table": "pdfplumber.extract_tables",
    "normalization": "bigram_jaccard",
}


class DocumentChunk(BaseModel):
    chunk_id: str
    document_id: str
    chunk_index: int
    text: str
    text_hash: str
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    section_title: Optional[str] = None
    char_start: Optional[int] = None
    char_end: Optional[int] = None
    previous_chunk_id: Optional[str] = None
    next_chunk_id: Optional[str] = None
    parser_name: str = "pdfplumber"
    parser_version: str = "1.0"
    status: str = "active"
    sentences: dict[str, str] = Field(default_factory=dict)


class ExcerptVerification(BaseModel):
    exact_match: bool
    normalized_match: bool = False
    fuzzy_match: bool = False
    fuzzy_score: Optional[float] = None
    verified_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    verification_method: str = "auto"


class RunConfig(BaseModel):
    config_path: Optional[str] = None
    config_hash: Optional[str] = None
    seed_urls: list[str] = Field(default_factory=list)


class RunManifest(BaseModel):
    run_id: str
    project_id: str
    run_type: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: Optional[datetime] = None
    status: str = "running"
    document_schema_version: str = "0.2.0"
    chunk_schema_version: str = "0.1.0"
    evidence_schema_version: str = "0.1.0"
    manifest_schema_version: str = "0.1.0"
    parser_versions: dict[str, str] = Field(default_factory=dict)
    prompt_versions: dict[str, str] = Field(default_factory=dict)
    config_hash: Optional[str] = None
    source_urls: list[str] = Field(default_factory=list)
    document_ids: list[str] = Field(default_factory=list)
    chunk_count: int = 0
    evidence_count: int = 0
    fetch_success: int = 0
    fetch_failed: int = 0
    duplicates_removed: int = 0
    llm_calls: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    cache_hits: int = 0
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class EvidenceCard(BaseModel):
    evidence_id: str
    document_id: str
    chunk_id: Optional[str] = None
    project_id: str
    topics: list[TopicEnum] = Field(default_factory=list)
    topic: str = "general"
    record_level: Optional[RecordLevel] = None
    evidence_type: EvidenceType
    claim: str
    original_excerpt: str
    page_number: Optional[int] = None
    section: Optional[str] = None
    source_url: str
    publisher: Optional[str] = None
    published_at: Optional[str] = None
    source_tier: SourceTier
    selected_sentence_ids: list[str] = Field(default_factory=list)
    extraction_method: str = "auto"
    confidence: Optional[float] = None
    numeric_values: list[NumericValue] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    status: str = "unverified"
    verified_at: Optional[datetime] = None
    verified_by: Optional[str] = None
    excerpt_verification: Optional[ExcerptVerification] = None
    evidence_schema_version: str = "0.3.0"


class EvidenceRecordStatus(str, Enum):
    ADMITTED = "admitted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class EvidenceSourceReference(BaseModel):
    """Source-level provenance retained with every admitted evidence record."""

    card_id: str
    document_id: str
    source_url: str
    title: str
    publisher: Optional[str] = None
    published_at: Optional[str] = None
    content_hash: str
    page_number: Optional[int] = None
    section: Optional[str] = None
    original_excerpt: str


class EvidenceRecord(BaseModel):
    """经过聚合和人工准入、允许进入研究上下文的正式证据。"""

    evidence_record_id: str
    project_id: str
    research_question: str
    card_ids: list[str]
    document_ids: list[str]
    title: str
    summary: str
    evidence_type: EvidenceType
    original_excerpts: list[str]
    source_references: list[EvidenceSourceReference]
    numeric_values: list[NumericValue] = Field(default_factory=list)
    time_range: Optional[str] = None
    geography: Optional[str] = None
    industry_scope: Optional[str] = None
    applicability: Optional[str] = None
    prohibited_extrapolations: list[str] = Field(default_factory=list)
    reviewer: str
    reviewed_at: datetime
    review_notes: Optional[str] = None
    status: EvidenceRecordStatus = EvidenceRecordStatus.ADMITTED
    evidence_record_schema_version: str = "0.2.0"


class ResearchBrief(BaseModel):
    """轻量研究状态；不复制报告中的逐条 Claim。"""

    project_id: str
    research_question: str
    scope: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    as_of_date: Optional[str] = None
    core_hypotheses: list[str] = Field(default_factory=list)
    counterevidence: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    output_requirements: list[str] = Field(default_factory=list)
    major_revision_notes: list[str] = Field(default_factory=list)
    approved_evidence_ids: list[str] = Field(default_factory=list)
    brief_schema_version: str = "0.1.0"
