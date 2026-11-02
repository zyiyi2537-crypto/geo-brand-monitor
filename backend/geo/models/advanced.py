"""Pydantic request + response models for the 6 advanced GEO check modes.

Each mode gets its own request + response type. Responses are intentionally
flat so the frontend can render them with minimal transformation.
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------

class CompareRequest(BaseModel):
    """--compare: 2+ URLs, returns side-by-side category breakdown."""
    urls: List[str] = Field(..., min_length=2, max_length=5)


class CrawlTestRequest(BaseModel):
    """--crawl-test: one URL, simulates AI bot access + Common Crawl lookup."""
    url: str


class AuthorityAuditRequest(BaseModel):
    """--authority-audit: one URL, off-page authority signals."""
    url: str


class CitationCheckRequest(BaseModel):
    """--citation-check: one URL, queries Perplexity for brand citations."""
    url: str


class AeoVisibilityRequest(BaseModel):
    """--aeo-visibility: one URL, AEO content optimization audit (free)."""
    url: str


class AiVisibilityRequest(BaseModel):
    """--ai-visibility: one URL, optional custom queries for the audit."""
    url: str
    custom_queries: Optional[List[str]] = None


class EntityAuditRequest(BaseModel):
    """--entity: entity name + type (brand|product|person)."""
    entity_name: str = Field(..., min_length=1)
    entity_type: str = Field(default="brand")


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------

class CompareUrlResult(BaseModel):
    url: str
    domain: str
    score: int
    grade: str
    categories: Dict[str, Any]


class CompareAdvantage(BaseModel):
    category: str
    ranked: List[Dict[str, Any]]


class CompareWinner(BaseModel):
    domain: str
    score: int
    grade: str
    lead: int


class CompareResponse(BaseModel):
    urls: List[str]
    results: List[CompareUrlResult]
    categories: List[str]
    advantages: List[CompareAdvantage]
    winner: Optional[CompareWinner] = None


class CrawlTestRobotEntry(BaseModel):
    bot: str
    ua: str
    status: str  # allowed | blocked


class CrawlTestWafEntry(BaseModel):
    bot: str
    status_code: Optional[int] = None
    size: int = 0
    result: str  # allowed | blocked | suspicious | error | unknown
    error: Optional[str] = None


class CrawlTestRobotsBlock(BaseModel):
    found: bool
    bots: List[CrawlTestRobotEntry]
    blocked: List[str]


class CrawlTestWafBlock(BaseModel):
    baseline_status: Optional[int] = None
    baseline_size: int = 0
    bots: List[CrawlTestWafEntry]
    blocked: List[str]


class CrawlTestCommonCrawl(BaseModel):
    found: bool = False
    count: int = 0
    samples: List[str] = Field(default_factory=list)
    status: Optional[int] = None
    error: Optional[str] = None


class CrawlTestResponse(BaseModel):
    url: str
    domain: str
    robots: CrawlTestRobotsBlock
    waf: CrawlTestWafBlock
    common_crawl: CrawlTestCommonCrawl
    total_issues: int


class AuthorityReviewsBlock(BaseModel):
    platforms: List[str]
    has_schema: bool


class AuthorityAwardsBlock(BaseModel):
    keywords: List[str]
    has_schema: bool
    badges: List[str]
    signal_count: int


class AuthorityGoogleBlock(BaseModel):
    indexed_pages: Optional[int] = None
    kg_schema_fields: int
    wikipedia_or_wikidata: bool
    score: int


class AuthorityMentionsBlock(BaseModel):
    platforms: List[str]


class AuthorityAuditResponse(BaseModel):
    url: str
    domain: str
    brand: str
    score: int
    max_score: int
    percent: float
    grade: str
    reviews: AuthorityReviewsBlock
    awards: AuthorityAwardsBlock
    google: AuthorityGoogleBlock
    mentions: AuthorityMentionsBlock


class CitationQueryResult(BaseModel):
    query: str
    cited: bool
    citations: List[str] = Field(default_factory=list)
    mentioned: bool = False
    total_sources: int = 0
    error: bool = False


class CitationCheckResponse(BaseModel):
    url: str
    domain: str
    brand: str
    engine: str
    total_queries: int
    valid_queries: int
    cited_queries: int
    citation_rate: float
    total_citations: int
    grade: str
    queries: List[CitationQueryResult]


class AiVisibilityScores(BaseModel):
    visibility: int
    entity: int
    competitor: int
    stability: int
    content_gap: int


class AiVisibilityCompetitor(BaseModel):
    domain: str
    mentions: int


class AiVisibilityResponse(BaseModel):
    url: str
    domain: str
    brand: str
    engines: List[str]
    scores: AiVisibilityScores
    total_score: int
    max_score: int
    grade: str
    grade_label: str
    per_engine_rates: Dict[str, float]
    top_competitors: List[AiVisibilityCompetitor]
    framings: Dict[str, int]
    content_gaps: List[str]
    query_count: int
    stability_runs: int
    source_trace: Optional["CISourceTrace"] = None
    source_preference: Optional["CISourcePreference"] = None


class EntityKnowledgeGraph(BaseModel):
    wikipedia: bool
    wikidata: bool
    wikidata_id: Optional[str] = None
    google_kg: bool
    baidu_baike: bool = False
    platforms_found: List[str]


class EntityPlatforms(BaseModel):
    found: List[str]
    not_found: List[str]


class EntityEngineDetail(BaseModel):
    sentiment: str
    framing: str
    recognized: bool


class EntityAuditResponse(BaseModel):
    entity: str
    entity_type: str
    scores: Dict[str, int]
    total_score: int
    max_score: int
    percent: int
    grade: str
    engines_used: List[str] = Field(default_factory=list)
    knowledge_graph: EntityKnowledgeGraph
    platforms: EntityPlatforms
    sentiment: str
    best_framing: str
    per_engine: Dict[str, EntityEngineDetail] = Field(default_factory=dict)
    content_gaps: List[str]
    recognition_rate: float
    stability_runs: int
    total_runs_per_query: int = 3
    source_trace: Optional["CISourceTrace"] = None
    source_preference: Optional["CISourcePreference"] = None


class AeoCategoryScore(BaseModel):
    earned: float
    max: float


class AeoPageResult(BaseModel):
    path: str
    score: int
    weakest_signal: str
    weakest_detail: str


class AeoPriorityImprovement(BaseModel):
    category: str
    percent: int


class AeoVisibilityResponse(BaseModel):
    url: str
    domain: str
    score: int
    grade: str
    max_score: int
    categories: Dict[str, AeoCategoryScore]
    page_results: List[AeoPageResult]
    priority_improvements: List[AeoPriorityImprovement]


# ---------------------------------------------------------------------------
# Tier gating — mirrors frontend ADVANCED_MODES in Result.tsx. Keep in sync.
# ---------------------------------------------------------------------------

TIER_RANK: Dict[str, int] = {
    "free": 0,
    "pro": 1,
    "starter": 2,
    "growth": 3,
    "scale": 4,
}

# Each advanced mode's minimum paid tier. These match Result.tsx ADVANCED_MODES
# so frontend and backend agree on what's locked.
MODE_MIN_TIER: Dict[str, str] = {
    "aeo": "free",
    "compare": "pro",
    "crawlTest": "pro",
    "authority": "pro",
    "citation": "pro",
    "visibility": "pro",
    "entity": "free",  # TODO: restore to "pro" after testing
    "competitiveIntel": "free",  # TODO: restore to "pro" after testing
}


# ---------------------------------------------------------------------------
# Competitive Intelligence (3-in-1: source trace + preference + competitors)
# ---------------------------------------------------------------------------

class CompetitiveIntelRequest(BaseModel):
    """Competitive Intelligence: URL + optional competitor domains."""
    url: str
    competitor_domains: Optional[List[str]] = None


class CISourceArticle(BaseModel):
    url: str
    title: str
    citations: int


class CISourceEntry(BaseModel):
    platform: str
    article_count: int
    total_citations: int
    engines: List[str]
    queries: List[str] = Field(default_factory=list)
    source_type: str = ""
    articles: List[CISourceArticle] = Field(default_factory=list)


class CISelfCitation(BaseModel):
    url: str
    engine: str
    query: str
    title: str = ""


class CISourceTrace(BaseModel):
    sources: List[CISourceEntry]
    self_citations: List[CISelfCitation]
    missing_queries: List[str]
    total_sources: int
    total_citations: int


class CIEnginePreference(BaseModel):
    engine: str
    total_citations: int
    type_distribution: Dict[str, float]
    top_domains: List[Dict[str, Any]]


class CISourcePreference(BaseModel):
    per_engine: List[CIEnginePreference]
    overall_distribution: Dict[str, float]
    engine_totals: Dict[str, int]
    recommendations: List[Dict[str, str]]
    stats: Dict[str, Any]


class CICompetitorEntry(BaseModel):
    domain: str
    name: str
    citation_count: int
    mention_count: int
    rate: float
    framing: str
    framings: Dict[str, int] = Field(default_factory=dict)
    engines: List[str] = Field(default_factory=list)


class CICompetitorInsight(BaseModel):
    competitors: List[CICompetitorEntry]
    total_competitors: int
    top_competitor: Optional[str] = None
    top_competitor_rate: float = 0
    top_competitor_mentions: int = 0
    your_rate: float = 0
    your_framing: str = "not_mentioned"
    monitored_keywords: int = 1


class BrandRankDetail(BaseModel):
    position: Optional[int] = None
    rank_label: str
    mentioned: bool
    is_first: bool


class BrandRankingSummary(BaseModel):
    brand: str
    per_engine: Dict[str, BrandRankDetail] = Field(default_factory=dict)
    avg_position: Optional[float] = None
    best_position: Optional[int] = None
    rank_distribution: Dict[str, int] = Field(default_factory=dict)
    engines_checked: int = 0
    engines_mentioned: int = 0


class CompetitiveIntelResponse(BaseModel):
    url: str
    domain: str
    brand: str
    engines: List[str]
    query_count: int
    total_results: int
    valid_results: int
    elapsed_seconds: float
    source_trace: CISourceTrace
    source_preference: CISourcePreference
    competitor_insight: CICompetitorInsight
    brand_ranking: Optional[BrandRankingSummary] = None


# Resolve forward references for models that use Optional["CI..."] before definition
AiVisibilityResponse.model_rebuild()
EntityAuditResponse.model_rebuild()
