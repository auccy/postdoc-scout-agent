"""Shared data models for auditable scouting outputs."""

from typing import Literal

from pydantic import BaseModel, Field

EvidenceSourceType = Literal[
    "publication",
    "grant",
    "lab_page",
    "institution_page",
    "job_posting",
    "clinical_trial",
    "news",
    "manual_note",
    "other",
]

AuthorPosition = Literal[
    "first",
    "co_first",
    "middle",
    "senior",
    "corresponding",
    "unknown",
]

QuerySource = Literal[
    "pubmed",
    "openalex",
    "semantic_scholar",
    "nih_reporter",
    "web",
    "generic",
]

ExpectedEvidenceType = Literal[
    "publication",
    "grant",
    "author",
    "lab_page",
    "job_posting",
    "clinical_trial",
    "other",
]


class EvidenceItem(BaseModel):
    """A short auditable evidence note from curated or extracted source data."""

    evidence_id: str = ""
    source_type: EvidenceSourceType = "other"
    title: str = ""
    url: str | None = None
    year: int | None = None
    source_name: str
    quoted_or_paraphrased_evidence: str = ""
    relevance_domains: list[str] = Field(default_factory=list)
    note: str
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    notes: str = ""


class Publication(BaseModel):
    """Publication evidence for a potential supervisor."""

    title: str
    year: int | None = None
    journal: str = ""
    authors: list[str] = Field(default_factory=list)
    candidate_author_position: AuthorPosition = "unknown"
    doi: str | None = None
    pmid: str | None = None
    url: str | None = None
    abstract: str = ""
    relevance_domains: list[str] = Field(default_factory=list)
    is_high_impact_journal: bool = False
    is_field_leading_journal: bool = False
    evidence_items: list[EvidenceItem] = Field(default_factory=list)


class Grant(BaseModel):
    """Grant or funded-project evidence for a potential supervisor."""

    title: str
    funder: str = ""
    project_number: str | None = None
    start_year: int | None = None
    end_year: int | None = None
    role: str = ""
    amount: float | None = None
    url: str | None = None
    relevance_domains: list[str] = Field(default_factory=list)
    evidence_items: list[EvidenceItem] = Field(default_factory=list)


class SupervisorCandidate(BaseModel):
    """A potential postdoctoral supervisor and auditable evidence bundle."""

    name: str
    current_affiliations: list[str] = Field(default_factory=list)
    institution_units: list[str] = Field(default_factory=list)
    departments_or_centers: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    profile_urls: list[str] = Field(default_factory=list)
    email: str | None = None
    contact_url: str | None = None
    publications: list[Publication] = Field(default_factory=list)
    grants: list[Grant] = Field(default_factory=list)
    evidence_items: list[EvidenceItem] = Field(default_factory=list)
    current_opening_signal: str | None = None
    notes: str = ""


class ScoreDimension(BaseModel):
    """One auditable dimension in a candidate score."""

    name: str
    numeric_score: float = Field(ge=0.0, le=5.0)
    stars: str
    weight: float
    weighted_contribution: float
    explanation: str
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ScoreBreakdown(BaseModel):
    """Weighted scoring output for one candidate."""

    dimensions: list[ScoreDimension]
    overall_score: float = Field(ge=0.0, le=5.0)
    priority_label: str
    method_heavy_penalty_applied: bool = False
    method_heavy_penalty: float = 0.0
    warnings: list[str] = Field(default_factory=list)


class CandidateReport(BaseModel):
    """A scored candidate report with traceable evidence."""

    candidate: SupervisorCandidate
    score_breakdown: ScoreBreakdown
    rank: int | None = None


class RankedCandidateList(BaseModel):
    """A deterministic ranked list of candidate reports."""

    candidates: list[CandidateReport]
    scoring_version: str = "candidate_scoring_v1"
    notes: str = ""


class QueryTarget(BaseModel):
    """Traceable institution unit target used for discovery query generation."""

    institution: str
    unit_name: str
    unit_type: str
    relevance_domains: list[str] = Field(default_factory=list)
    priority: str = "medium"


class SearchQuery(BaseModel):
    """A reusable structured search query template for a future connector."""

    query_id: str
    query_text: str
    source: QuerySource
    institution: str
    unit_name: str
    unit_type: str
    mode: Literal["broad", "narrow"]
    relevance_domains: list[str] = Field(default_factory=list)
    priority: Literal["high", "medium", "low"] = "medium"
    rationale: str
    expected_evidence_type: ExpectedEvidenceType
    notes: str = ""


class QueryBundle(BaseModel):
    """Auditable bundle of discovery queries for an institution ecosystem."""

    institution: str
    normalized_institution: str
    mode: Literal["broad", "narrow"]
    generated_at: str
    queries: list[SearchQuery] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    ecosystem_summary: dict[str, object] = Field(default_factory=dict)


class Institution(BaseModel):
    """A normalized institution identity and known aliases."""

    name: str
    normalized_name: str
    aliases: list[str] = Field(default_factory=list)
    parent_type: str = "other"
    city: str | None = None
    state: str | None = None
    priority_tier: str = "C"
    relevance_domains: list[str] = Field(default_factory=list)
    notes: str = ""
    verification_status: str = "curated_seed_needs_verification"
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class InstitutionUnit(BaseModel):
    """A school, hospital, center, department, or partner unit in an ecosystem."""

    name: str
    unit_type: str
    parent_institution: str
    relationship_to_parent: str
    relevance_domains: list[str] = Field(default_factory=list)
    relevance_score: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    source_urls: list[str] = Field(default_factory=list)
    evidence_items: list[EvidenceItem] = Field(default_factory=list)
    notes: str = ""
    priority: str = "medium"
    verification_status: str = "curated_seed_needs_verification"


class InstitutionEcosystem(BaseModel):
    """Auditable map of relevant units around an institution query."""

    query: str
    mode: str
    institution: Institution
    matched_aliases: list[str] = Field(default_factory=list)
    units: list[InstitutionUnit] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
