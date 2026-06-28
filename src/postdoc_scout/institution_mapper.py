"""Institution ecosystem mapping from curated seed data."""

import re
from enum import Enum
from pathlib import Path
from typing import Any

from postdoc_scout.config import CONFIG_DIR, load_named_config
from postdoc_scout.models import EvidenceItem, Institution, InstitutionEcosystem, InstitutionUnit


class MappingMode(str, Enum):
    """Supported institution mapping modes."""

    BROAD = "broad"
    NARROW = "narrow"


class OutputFormat(str, Enum):
    """Supported report output formats."""

    JSON = "json"
    MD = "md"
    BOTH = "both"


class InstitutionTier(str, Enum):
    """Supported institution priority tier filters."""

    A = "A"
    B = "B"
    C = "C"
    ALL = "all"


MODE_DOMAIN_WEIGHTS = {
    MappingMode.BROAD: {
        "digital medicine": 0.18,
        "clinical AI": 0.18,
        "oncology": 0.14,
        "EHR/RWD": 0.14,
        "public health": 0.11,
        "population health": 0.11,
        "epidemiology": 0.10,
        "translational medicine": 0.11,
        "biomedical informatics": 0.09,
        "clinical decision support": 0.05,
        "trial enrichment": 0.05,
        "patient stratification": 0.05,
        "disease risk prediction": 0.05,
        "pediatrics": 0.04,
    },
    MappingMode.NARROW: {
        "AD/ADRD": 0.24,
        "aging": 0.20,
        "neurodegeneration": 0.18,
        "neurology": 0.16,
        "neuroscience": 0.12,
        "clinical AI": 0.06,
        "EHR/RWD": 0.04,
    },
}

UNIT_TYPE_PRIORS = {
    "medical_school": 0.10,
    "academic_medical_center": 0.10,
    "health_system": 0.10,
    "public_health_school": 0.08,
    "population_health_unit": 0.08,
    "affiliated_hospital": 0.10,
    "cancer_center": 0.12,
    "aging_center": 0.12,
    "neuroscience_center": 0.11,
    "biomedical_informatics_unit": 0.10,
    "digital_medicine_center": 0.12,
    "partner_research_institute": 0.08,
    "clinical_trial_center": 0.08,
    "department": 0.06,
    "university": 0.04,
    "other": 0.02,
}

DEFAULT_LIMITATIONS = [
    "This ecosystem map is generated from curated seed data only.",
    "Affiliation and relevance claims should be verified before outreach or ranking decisions.",
    "No web scraping, external APIs, or private data sources are used in this MVP module.",
]

US_SEED_FILES = [
    "us_institution_targets.yml",
    "us_institution_affiliates.yml",
    "us_independent_research_institutes.yml",
]


def normalize_institution_name(name: str) -> str:
    """Normalize institution names and aliases for conservative matching."""
    normalized = name.casefold().replace("&", " and ")
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return " ".join(normalized.split())


def slugify_institution_name(name: str) -> str:
    """Create a stable filesystem slug for ecosystem outputs."""
    normalized = normalize_institution_name(name)
    return normalized.replace(" ", "_") or "unknown_institution"


def _read_seed_file(name: str) -> list[dict[str, Any]]:
    if not (CONFIG_DIR / name).exists():
        return []
    data = load_named_config(name)
    institutions = data.get("institutions", [])
    if not isinstance(institutions, list):
        return []
    return [entry for entry in institutions if isinstance(entry, dict)]


def _entry_name(entry: dict[str, Any]) -> str:
    return str(entry.get("canonical_name") or entry.get("name") or "Unknown institution")


def _load_institution_entries(country: str = "us") -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if country.casefold() == "us":
        for seed_file in US_SEED_FILES:
            entries.extend(_read_seed_file(seed_file))
    else:
        entries.extend(_read_seed_file("institution_affiliates.yml"))

    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for entry in entries:
        normalized_name = normalize_institution_name(_entry_name(entry))
        if normalized_name not in seen:
            seen.add(normalized_name)
            deduped.append(entry)
    return deduped


def list_parent_institutions(
    country: str = "us",
    tier: InstitutionTier = InstitutionTier.ALL,
) -> list[dict[str, Any]]:
    """List curated parent institutions for CLI inspection and tests."""
    entries = _load_institution_entries(country)
    if tier == InstitutionTier.ALL:
        return sorted(entries, key=lambda entry: (_entry_name(entry)))
    return sorted(
        [entry for entry in entries if str(entry.get("priority_tier", "C")) == tier.value],
        key=lambda entry: _entry_name(entry),
    )


def _find_institution_entry(
    query: str,
    country: str = "us",
) -> tuple[dict[str, Any] | None, list[str]]:
    normalized_query = normalize_institution_name(query)

    for entry in _load_institution_entries(country):
        names = [_entry_name(entry), *entry.get("aliases", [])]
        normalized_aliases = {
            normalize_institution_name(alias): alias for alias in names if isinstance(alias, str)
        }
        if normalized_query in normalized_aliases:
            matched = [
                alias
                for normalized, alias in normalized_aliases.items()
                if normalized == normalized_query
            ]
            return entry, matched

    return None, []


def _score_domains(domains: list[str], unit_type: str, mode: MappingMode) -> float:
    weights = MODE_DOMAIN_WEIGHTS[mode]
    domain_score = sum(weights.get(domain, 0.0) for domain in domains)
    type_prior = UNIT_TYPE_PRIORS.get(unit_type, UNIT_TYPE_PRIORS["other"])
    return min(1.0, round(domain_score + type_prior, 3))


def _build_unit(raw_unit: dict[str, Any], parent_name: str, mode: MappingMode) -> InstitutionUnit:
    domains = [str(domain) for domain in raw_unit.get("relevance_domains", [])]
    unit_type = str(raw_unit.get("unit_type", "other"))
    evidence_items = [
        EvidenceItem(
            source_name=str(item.get("source_name", "Curated seed entry")),
            url=item.get("url"),
            note=str(item.get("note", "Curated seed entry; verify before use.")),
            confidence=float(item.get("confidence", raw_unit.get("confidence", 0.5))),
        )
        for item in raw_unit.get("evidence_items", [])
        if isinstance(item, dict)
    ]
    source_urls = [str(url) for url in raw_unit.get("source_urls", [])]

    return InstitutionUnit(
        name=str(raw_unit.get("name", "Unknown unit")),
        unit_type=unit_type,
        parent_institution=parent_name,
        relationship_to_parent=str(raw_unit.get("relationship_to_parent", "curated seed unit")),
        relevance_domains=domains,
        relevance_score=_score_domains(domains, unit_type, mode),
        confidence=float(raw_unit.get("confidence", 0.5)),
        source_urls=source_urls,
        evidence_items=evidence_items,
        notes=str(raw_unit.get("notes", "Curated seed entry; verify before use.")),
        priority=str(raw_unit.get("priority", "medium")),
        verification_status=str(
            raw_unit.get("verification_status", "curated_seed_needs_verification")
        ),
    )


def map_institution_ecosystem(
    institution: str,
    mode: MappingMode = MappingMode.BROAD,
    country: str = "us",
) -> InstitutionEcosystem:
    """Map an institution query to relevant biomedical ecosystem units."""
    entry, matched_aliases = _find_institution_entry(institution, country)
    normalized_query = normalize_institution_name(institution)

    if entry is None:
        return InstitutionEcosystem(
            query=institution,
            mode=mode.value,
            institution=Institution(
                name=institution,
                normalized_name=normalized_query,
                aliases=[],
                verification_status="curated_seed_needs_verification",
                confidence=0.1,
            ),
            matched_aliases=[],
            units=[],
            limitations=[
                *DEFAULT_LIMITATIONS,
                "No curated seed entry matched this institution query.",
            ],
        )

    canonical_name = _entry_name(entry)
    aliases = [str(alias) for alias in entry.get("aliases", [])]
    units = [
        _build_unit(raw_unit, canonical_name, mode)
        for raw_unit in entry.get("units", [])
        if isinstance(raw_unit, dict)
    ]
    units.sort(key=lambda unit: (-unit.relevance_score, -unit.confidence, unit.name))

    return InstitutionEcosystem(
        query=institution,
        mode=mode.value,
        institution=Institution(
            name=canonical_name,
            normalized_name=normalize_institution_name(canonical_name),
            aliases=aliases,
            parent_type=str(entry.get("parent_type", "other")),
            city=entry.get("city"),
            state=entry.get("state"),
            priority_tier=str(entry.get("priority_tier", "C")),
            relevance_domains=[str(domain) for domain in entry.get("relevance_domains", [])],
            notes=str(entry.get("notes", "Curated seed entry; verify before use.")),
            verification_status=str(
                entry.get("verification_status", "curated_seed_needs_verification")
            ),
            confidence=float(entry.get("confidence", 0.5)),
        ),
        matched_aliases=matched_aliases,
        units=units,
        limitations=list(entry.get("limitations", DEFAULT_LIMITATIONS)) or DEFAULT_LIMITATIONS,
    )


def write_ecosystem_json(ecosystem: InstitutionEcosystem, output_dir: Path) -> Path:
    """Write an ecosystem map as JSON and return the output path."""
    output_dir.mkdir(parents=True, exist_ok=True)
    slug = slugify_institution_name(ecosystem.institution.name)
    output_path = output_dir / f"{slug}_ecosystem.json"
    output_path.write_text(ecosystem.model_dump_json(indent=2), encoding="utf-8")
    return output_path


def write_ecosystem_markdown(ecosystem: InstitutionEcosystem, output_dir: Path) -> Path:
    """Write an ecosystem map as Markdown and return the output path."""
    output_dir.mkdir(parents=True, exist_ok=True)
    slug = slugify_institution_name(ecosystem.institution.name)
    output_path = output_dir / f"{slug}_ecosystem.md"

    lines = [
        f"# {ecosystem.institution.name} Ecosystem Map",
        "",
        "## Normalized Institution",
        "",
        f"- Query: {ecosystem.query}",
        f"- Normalized: {ecosystem.institution.normalized_name}",
        f"- Parent type: {ecosystem.institution.parent_type}",
        f"- Location: {ecosystem.institution.city or 'Unknown'}, "
        f"{ecosystem.institution.state or 'Unknown'}",
        f"- Priority tier: {ecosystem.institution.priority_tier}",
        f"- Verification status: {ecosystem.institution.verification_status}",
        f"- Mode: {ecosystem.mode}",
        "",
        "## Matched Aliases",
        "",
    ]
    lines.extend(f"- {alias}" for alias in ecosystem.matched_aliases or ["No alias matched."])
    lines.extend(["", "## Relevant Schools, Departments, and Institutes", ""])

    if ecosystem.units:
        for unit in ecosystem.units:
            lines.extend(
                [
                    f"### {unit.name}",
                    "",
                    f"- Type: {unit.unit_type}",
                    f"- Relationship: {unit.relationship_to_parent}",
                    f"- Priority: {unit.priority}",
                    f"- Verification status: {unit.verification_status}",
                    f"- Relevance score: {unit.relevance_score:.3f}",
                    f"- Confidence: {unit.confidence:.2f}",
                    f"- Relevance domains: {', '.join(unit.relevance_domains) or 'None listed'}",
                    f"- Source URLs: {', '.join(unit.source_urls) or 'None listed'}",
                    f"- Notes: {unit.notes}",
                    "",
                    "Evidence notes:",
                ]
            )
            if unit.evidence_items:
                lines.extend(
                    f"- {item.source_name}: {item.note} ({item.url or 'no URL'})"
                    for item in unit.evidence_items
                )
            else:
                lines.append("- No evidence items listed.")
            lines.append("")
    else:
        lines.append("No curated units matched this institution.")
        lines.append("")

    lines.extend(["## Limitations", ""])
    lines.extend(f"- {limitation}" for limitation in ecosystem.limitations)
    lines.append("")

    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


def write_ecosystem_reports(
    ecosystem: InstitutionEcosystem,
    output_dir: Path,
    output_format: OutputFormat,
) -> list[Path]:
    """Write ecosystem reports in the requested format."""
    if output_format == OutputFormat.JSON:
        return [write_ecosystem_json(ecosystem, output_dir)]
    if output_format == OutputFormat.MD:
        return [write_ecosystem_markdown(ecosystem, output_dir)]
    return [
        write_ecosystem_json(ecosystem, output_dir),
        write_ecosystem_markdown(ecosystem, output_dir),
    ]
