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
    "last",
    "senior",
    "corresponding",
    "unknown",
]

AuthorMentionPosition = Literal[
    "first",
    "co_first",
    "middle",
    "senior",
    "corresponding",
    "last",
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

EvidenceConnector = Literal["openalex", "pubmed"]

EnrichmentSource = Literal["nih_reporter", "semantic_scholar", "manual"]

PipelineStageName = Literal[
    "institution_mapping",
    "query_building",
    "evidence_collection",
    "candidate_extraction",
    "candidate_ranking",
    "candidate_enrichment",
]

OpeningSignalType = Literal[
    "explicit_postdoc_opening",
    "lab_hiring_statement",
    "contact_for_positions",
    "recent_grant_possible_hiring",
    "no_signal_found",
    "outdated_signal",
    "mismatch_signal",
    "manual_note",
]

OpeningSignalStrength = Literal["high", "medium", "low", "none"]

JournalTier = Literal[
    "top_general_medical",
    "top_science_nature_cell",
    "flagship_subjournals",
    "field_leading",
    "methods_but_downweighted_if_pure",
    "other",
]

ReviewStatus = Literal[
    "interested",
    "maybe",
    "low_priority",
    "do_not_contact",
    "needs_more_review",
]

OutreachStatus = Literal[
    "not_contacted",
    "drafted",
    "contacted",
    "replied",
    "follow_up_needed",
    "rejected",
    "archived",
]

FitDimensionName = Literal[
    "domain_fit",
    "data_fit",
    "translational_fit",
    "disease_fit",
    "method_fit",
    "opportunity_fit",
    "mismatch_risk",
]

FitPriority = Literal[
    "strong_fit",
    "good_fit",
    "possible_fit",
    "low_fit",
    "avoid_or_review",
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
    affiliations: list[str] = Field(default_factory=list)
    author_affiliations: dict[str, list[str]] = Field(default_factory=dict)
    corresponding_authors: list[str] = Field(default_factory=list)
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


class ConnectorRunSummary(BaseModel):
    """Summary of one external connector run."""

    source_connector: EvidenceConnector
    queries_attempted: int = 0
    requests_made: int = 0
    publications_retrieved: int = 0
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class RetrievedPublicationEvidence(BaseModel):
    """Publication evidence retrieved from one connector and traced to one query."""

    publication: Publication
    source_connector: EvidenceConnector
    originating_query_id: str
    originating_query_text: str
    matched_unit_name: str
    relevance_domains: list[str] = Field(default_factory=list)
    retrieval_warnings: list[str] = Field(default_factory=list)


class EvidenceCollection(BaseModel):
    """Deduplicated publication evidence collection for a query bundle."""

    institution: str
    normalized_institution: str
    generated_at: str
    query_file: str | None = None
    sources: list[EvidenceConnector] = Field(default_factory=list)
    total_queries_run: int = 0
    total_publications_retrieved: int = 0
    deduplicated_publications: int = 0
    duplicate_publications_removed: int = 0
    publications: list[RetrievedPublicationEvidence] = Field(default_factory=list)
    connector_summaries: list[ConnectorRunSummary] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class AuthorMention(BaseModel):
    """One author mention extracted from a retrieved publication."""

    author_name: str
    normalized_author_name: str
    publication_title: str
    publication_year: int | None = None
    journal: str = ""
    author_position: AuthorMentionPosition = "unknown"
    affiliations: list[str] = Field(default_factory=list)
    matched_institution_units: list[str] = Field(default_factory=list)
    source_connector: EvidenceConnector
    evidence_id: str
    originating_query_id: str
    relevance_domains: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list)


class CandidateCluster(BaseModel):
    """Conservative cluster of repeated author mentions into a possible candidate."""

    candidate_id: str
    display_name: str
    normalized_name: str
    possible_affiliations: list[str] = Field(default_factory=list)
    matched_institution_units: list[str] = Field(default_factory=list)
    publications: list[Publication] = Field(default_factory=list)
    author_mentions: list[AuthorMention] = Field(default_factory=list)
    evidence_items: list[EvidenceItem] = Field(default_factory=list)
    senior_author_count: int = 0
    corresponding_author_count: int = 0
    first_author_count: int = 0
    recent_publication_count: int = 0
    high_impact_publication_count: int = 0
    field_leading_publication_count: int = 0
    relevance_domains: list[str] = Field(default_factory=list)
    candidate_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    ambiguity_warnings: list[str] = Field(default_factory=list)
    notes: str = ""


class CandidateExtractionReport(BaseModel):
    """Candidate extraction report with traceable author clusters."""

    institution: str
    mode: str
    source_evidence_file: str
    total_publications_processed: int = 0
    total_author_mentions: int = 0
    total_candidate_clusters: int = 0
    candidate_clusters: list[CandidateCluster] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class RankedSupervisorCandidate(BaseModel):
    """A preliminary ranked supervisor candidate produced from author clusters."""

    rank: int | None = None
    candidate_id: str
    display_name: str
    possible_affiliations: list[str] = Field(default_factory=list)
    matched_institution_units: list[str] = Field(default_factory=list)
    inferred_domains: list[str] = Field(default_factory=list)
    publication_count: int = 0
    recent_publication_count: int = 0
    senior_author_count: int = 0
    corresponding_author_count: int = 0
    first_author_count: int = 0
    evidence_items: list[EvidenceItem] = Field(default_factory=list)
    score_breakdown: ScoreBreakdown
    overall_score: float = Field(ge=0.0, le=5.0)
    priority_label: str
    method_heavy_penalty_applied: bool = False
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    suggested_contact_angle: str = ""


class CandidateRankingReport(BaseModel):
    """Preliminary ranked supervisor report from candidate clusters."""

    institution: str
    mode: str
    candidate_file: str
    evidence_file: str | None = None
    generated_at: str
    clusters_processed: int = 0
    ranked_candidate_count: int = 0
    ranked_candidates: list[RankedSupervisorCandidate] = Field(default_factory=list)
    methodology_note: str = ""
    limitations: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class JournalClassification(BaseModel):
    """Configured journal-tier and field-basket classification."""

    journal: str
    normalized_journal: str
    journal_tier: JournalTier = "other"
    field_basket: str = "other"
    configured_weight: float = 0.45
    explanation: str = ""


class AuthorshipCalibration(BaseModel):
    """Author-position calibration for one publication."""

    author_position: AuthorPosition = "unknown"
    author_position_weight: float = 0.55
    explanation: str = ""
    warnings: list[str] = Field(default_factory=list)


class PublicationImpactScore(BaseModel):
    """Calibrated impact score for one publication."""

    publication_id: str
    title: str
    year: int | None = None
    journal: str = ""
    journal_tier: JournalTier = "other"
    field_basket: str = "other"
    author_position: AuthorPosition = "unknown"
    author_position_weight: float = 0.55
    recency_weight: float = 0.60
    domain_relevance_weight: float = 0.50
    article_type_weight: float = 0.65
    consortium_warning: str = ""
    method_heavy_warning: str = ""
    calibrated_score: float = 0.0
    explanation: str = ""


class CandidatePublicationCalibration(BaseModel):
    """Candidate-level publication calibration summary."""

    candidate_id: str
    display_name: str
    publication_count: int = 0
    mean_calibrated_score: float = 0.0
    max_calibrated_score: float = 0.0
    senior_or_corresponding_count: int = 0
    middle_author_count: int = 0
    field_leading_count: int = 0
    method_heavy_count: int = 0
    consortium_warning_count: int = 0
    old_impact_only_warning: bool = False
    warnings: list[str] = Field(default_factory=list)
    publication_scores: list[PublicationImpactScore] = Field(default_factory=list)


class PublicationCalibrationReport(BaseModel):
    """Auditable candidate publication calibration report."""

    generated_at: str
    ranked_file: str
    candidate_file: str | None = None
    candidate_count: int = 0
    candidates: list[CandidatePublicationCalibration] = Field(default_factory=list)
    journal_tier_summary: dict[str, int] = Field(default_factory=dict)
    author_position_summary: dict[str, int] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class FundingEvidence(BaseModel):
    """Grant or funding evidence from NIH RePORTER or similar sources."""

    title: str = ""
    funder: str = ""
    project_number: str | None = None
    fiscal_years: list[int] = Field(default_factory=list)
    role: str = ""
    organization: str = ""
    url: str | None = None
    relevance_domains: list[str] = Field(default_factory=list)
    evidence_id: str = ""
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    notes: str = ""


class AuthorProfileEvidence(BaseModel):
    """External author/profile evidence for a preliminary supervisor candidate."""

    source: str
    profile_url: str | None = None
    author_id: str | None = None
    name: str = ""
    affiliations: list[str] = Field(default_factory=list)
    paper_count: int | None = None
    citation_count: int | None = None
    h_index: int | None = None
    fields_of_study: list[str] = Field(default_factory=list)
    matched_by: str = ""
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list)


class OpeningSignal(BaseModel):
    """Manual or future connector-derived lab opening signal."""

    signal_type: OpeningSignalType = "no_signal_found"
    source_url: str | None = None
    text_or_note: str = ""
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    evidence_id: str = ""
    warnings: list[str] = Field(default_factory=list)


class LabProfileSignal(BaseModel):
    """Lab/profile URL and search-query hints for one ranked candidate."""

    candidate_id: str
    display_name: str
    possible_affiliations: list[str] = Field(default_factory=list)
    generated_search_queries: list[str] = Field(default_factory=list)
    profile_urls: list[str] = Field(default_factory=list)
    lab_urls: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list)
    evidence_items: list[EvidenceItem] = Field(default_factory=list)


class OpeningSignalEvidence(BaseModel):
    """One deterministic opening-signal classification from manual text or URL evidence."""

    candidate_id: str
    display_name: str
    opening_signal_type: OpeningSignalType = "no_signal_found"
    opening_signal_strength: OpeningSignalStrength = "none"
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    source_url: str | None = None
    evidence_snippet: str = ""
    source_query: str = ""
    opportunity_score_adjustment: float = 0.0
    warnings: list[str] = Field(default_factory=list)
    evidence_items: list[EvidenceItem] = Field(default_factory=list)


class CandidateOpportunityAssessment(BaseModel):
    """Opening-signal assessment for one ranked supervisor candidate."""

    candidate_id: str
    display_name: str
    possible_affiliations: list[str] = Field(default_factory=list)
    original_priority_label: str = ""
    original_score: float = 0.0
    generated_search_queries: list[str] = Field(default_factory=list)
    profile_urls: list[str] = Field(default_factory=list)
    lab_urls: list[str] = Field(default_factory=list)
    opening_signal_type: OpeningSignalType = "no_signal_found"
    opening_signal_strength: OpeningSignalStrength = "none"
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    source_url: str | None = None
    evidence_snippet: str = ""
    source_query: str = ""
    opportunity_score_adjustment: float = 0.0
    suggested_next_manual_check: str = ""
    warnings: list[str] = Field(default_factory=list)
    evidence_items: list[EvidenceItem] = Field(default_factory=list)


class OpeningSignalReport(BaseModel):
    """Auditable opening-signal report for ranked or enriched supervisor candidates."""

    generated_at: str
    ranked_file: str
    manual_signals_file: str | None = None
    candidate_count: int = 0
    candidates: list[CandidateOpportunityAssessment] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class CandidateProfileEnrichment(BaseModel):
    """Profile, funding, and opening enrichment for one ranked candidate."""

    candidate_id: str
    display_name: str
    possible_affiliations: list[str] = Field(default_factory=list)
    profile_urls: list[str] = Field(default_factory=list)
    semantic_scholar_profiles: list[AuthorProfileEvidence] = Field(default_factory=list)
    nih_reporter_grants: list[FundingEvidence] = Field(default_factory=list)
    manual_profile_notes: list[str] = Field(default_factory=list)
    opening_signals: list[OpeningSignal] = Field(default_factory=list)
    enrichment_warnings: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    evidence_items: list[EvidenceItem] = Field(default_factory=list)


class EnrichedSupervisorCandidate(BaseModel):
    """Ranked supervisor candidate plus deterministic enrichment annotations."""

    ranked_candidate: RankedSupervisorCandidate
    enrichment: CandidateProfileEnrichment
    enrichment_adjusted_score: float | None = None
    enrichment_notes: list[str] = Field(default_factory=list)
    next_manual_check: str = ""


class EnrichmentRunSummary(BaseModel):
    """Summary of one candidate enrichment run."""

    sources: list[EnrichmentSource] = Field(default_factory=list)
    candidates_processed: int = 0
    candidates_with_funding_evidence: int = 0
    candidates_with_author_profile_evidence: int = 0
    candidates_with_opening_signals: int = 0
    warnings: list[str] = Field(default_factory=list)


class EnrichedCandidateReport(BaseModel):
    """Auditable enriched supervisor report."""

    generated_at: str
    ranked_file: str
    run_summary: EnrichmentRunSummary
    candidates: list[EnrichedSupervisorCandidate] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class CandidateReview(BaseModel):
    """Manual review-tracker row for one candidate."""

    candidate_id: str
    display_name: str
    possible_affiliations: str = ""
    original_priority_label: str = ""
    original_score: float = 0.0
    review_status: ReviewStatus = "needs_more_review"
    outreach_status: OutreachStatus = "not_contacted"
    user_notes: str = ""
    last_updated: str = ""
    next_action: str = ""
    contact_url: str = ""
    email: str = ""
    opening_signal_type: OpeningSignalType = "no_signal_found"
    opening_signal_strength: OpeningSignalStrength = "none"
    opportunity_score_adjustment: float = 0.0


class ShortlistReport(BaseModel):
    """Summary of exported manual-review shortlist rows."""

    generated_at: str
    tracker_file: str
    output_file: str
    status_filter: ReviewStatus | None = None
    candidate_count: int = 0
    candidates: list[CandidateReview] = Field(default_factory=list)


class UserResearchProfile(BaseModel):
    """A user-supplied research profile for deterministic candidate-fit matching."""

    name: str = ""
    current_position: str = ""
    current_affiliation: str = ""
    website: str | None = None
    github: str | None = None
    email: str | None = None
    research_summary: str = ""
    target_role: str = ""
    preferred_domains: list[str] = Field(default_factory=list)
    secondary_domains: list[str] = Field(default_factory=list)
    methods: list[str] = Field(default_factory=list)
    datasets: list[str] = Field(default_factory=list)
    disease_areas: list[str] = Field(default_factory=list)
    translational_strengths: list[str] = Field(default_factory=list)
    publications_summary: str = ""
    avoid_directions: dict[str, bool] = Field(default_factory=dict)
    preferred_geographies: list[str] = Field(default_factory=list)
    preferred_institution_types: list[str] = Field(default_factory=list)
    notes: str = ""


class FitDimension(BaseModel):
    """One auditable fit dimension for a personalized candidate assessment."""

    name: FitDimensionName
    score: float = Field(ge=0.0, le=5.0)
    weight: float
    weighted_contribution: float
    matched_terms: list[str] = Field(default_factory=list)
    explanation: str = ""
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class CandidateFitAssessment(BaseModel):
    """Personalized deterministic fit assessment for one ranked candidate."""

    candidate_id: str
    display_name: str
    original_priority_label: str = ""
    original_score: float = 0.0
    fit_score: float = Field(ge=0.0, le=5.0)
    fit_priority: FitPriority
    recommended_shortlist_status: ReviewStatus = "needs_more_review"
    dimensions: list[FitDimension] = Field(default_factory=list)
    transferable_strengths: list[str] = Field(default_factory=list)
    mismatch_warnings: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    explanation: str = ""
    human_review_checklist: list[str] = Field(default_factory=list)


class FitMatchingReport(BaseModel):
    """Personalized fit-matching report for a user profile and ranked candidates."""

    generated_at: str
    ranked_file: str
    user_profile_file: str
    user_profile: UserResearchProfile
    candidate_count: int = 0
    candidates: list[CandidateFitAssessment] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class PipelineConfig(BaseModel):
    """Configuration for an end-to-end postdoc scouting pipeline run."""

    institution: str
    mode: str = "broad"
    country: str = "us"
    output_dir: str = "outputs"
    sources: str = "openalex,pubmed"
    enrichment_sources: str = "nih_reporter,semantic_scholar,manual"
    limit_queries: int = 100
    limit_per_source: int = 20
    top_n: int | None = None
    year_from: int | None = 2021
    year_to: int | None = None
    resume: bool = True
    skip_evidence_collection: bool = False
    skip_enrichment: bool = False
    dry_run: bool = False
    output_format: str = "all"


class PipelineStageResult(BaseModel):
    """Execution status for one pipeline stage."""

    stage: PipelineStageName
    status: str
    output_files: list[str] = Field(default_factory=list)
    reused_existing: bool = False
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    metrics: dict[str, int | float | str | bool | None] = Field(default_factory=dict)


class PipelineRunReport(BaseModel):
    """Auditable end-to-end pipeline run report."""

    institution: str
    mode: str
    country: str
    output_dir: str
    generated_at: str
    dry_run: bool = False
    config: PipelineConfig
    stages: list[PipelineStageResult] = Field(default_factory=list)
    output_files: list[str] = Field(default_factory=list)
    metrics: dict[str, int | float | str | bool | None] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


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
