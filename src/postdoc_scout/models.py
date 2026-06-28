"""Shared data models for auditable scouting outputs."""

from pydantic import BaseModel, Field


class EvidenceItem(BaseModel):
    """A short auditable evidence note from curated seed data."""

    source_name: str
    url: str | None = None
    note: str
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class Institution(BaseModel):
    """A normalized institution identity and known aliases."""

    name: str
    normalized_name: str
    aliases: list[str] = Field(default_factory=list)


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


class InstitutionEcosystem(BaseModel):
    """Auditable map of relevant units around an institution query."""

    query: str
    mode: str
    institution: Institution
    matched_aliases: list[str] = Field(default_factory=list)
    units: list[InstitutionUnit] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
