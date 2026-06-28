"""Validation and coverage reporting for curated institution seed maps."""

from collections import Counter, defaultdict
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from postdoc_scout.config import load_named_config
from postdoc_scout.institution_mapper import US_SEED_FILES, normalize_institution_name

VALID_PARENT_TYPES = {
    "university",
    "academic_medical_center",
    "cancer_center",
    "independent_research_institute",
    "health_system",
    "public_health_school",
    "other",
}

VALID_RELATIONSHIPS = {
    "owned_by",
    "affiliated_with",
    "joint_institute",
    "partner_ecosystem",
    "nearby_ecosystem",
    "clinical_partner",
    "research_partner",
    "needs_verification",
}

VALID_PRIORITY_TIERS = {"A", "B", "C"}

KNOWN_RELEVANCE_DOMAINS = {
    "AD/ADRD",
    "EHR/RWD",
    "aging",
    "biomedical data science",
    "biomedical engineering",
    "biomedical informatics",
    "clinical AI",
    "clinical decision support",
    "clinical trials",
    "digital medicine",
    "disease biology",
    "disease risk prediction",
    "epidemiology",
    "genomics",
    "immunology",
    "neurodegeneration",
    "neurology",
    "neuroscience",
    "oncology",
    "patient stratification",
    "pediatrics",
    "population health",
    "public health",
    "translational medicine",
    "trial enrichment",
}

REQUIRED_PARENT_FIELDS = {
    "canonical_name",
    "aliases",
    "parent_type",
    "city",
    "state",
    "priority_tier",
    "relevance_domains",
    "notes",
    "verification_status",
    "units",
}

OPTIONAL_PARENT_FIELDS = {"confidence", "limitations"}

REQUIRED_UNIT_FIELDS = {
    "name",
    "unit_type",
    "relationship_to_parent",
    "relevance_domains",
    "priority",
    "notes",
    "source_urls",
    "verification_status",
}

OPTIONAL_UNIT_FIELDS = {"confidence", "evidence_items"}

UNCERTAIN_VERIFICATION_STATUS = "curated_seed_needs_verification"


class ValidationIssue(BaseModel):
    """A structured validation issue with enough context for audit."""

    file: str
    institution: str | None = None
    unit: str | None = None
    field: str | None = None
    message: str


class SeedMapCoverage(BaseModel):
    """Coverage metrics for the curated seed map."""

    total_parent_institutions: int = 0
    total_units: int = 0
    parent_institutions_by_priority_tier: dict[str, int] = Field(default_factory=dict)
    parent_institutions_by_parent_type: dict[str, int] = Field(default_factory=dict)
    units_by_unit_type: dict[str, int] = Field(default_factory=dict)
    units_by_relevance_domain: dict[str, int] = Field(default_factory=dict)
    institutions_with_no_units: int = 0
    institutions_with_fewer_than_2_units: int = 0
    top_connected_parent_institutions: list[dict[str, int | str]] = Field(default_factory=list)


class SeedMapValidationResult(BaseModel):
    """Validation result and coverage summary for seed map files."""

    country: str
    seed_files: list[str]
    valid: bool
    errors: list[ValidationIssue] = Field(default_factory=list)
    warnings: list[ValidationIssue] = Field(default_factory=list)
    relationship_warnings: list[ValidationIssue] = Field(default_factory=list)
    duplicate_canonical_names: list[str] = Field(default_factory=list)
    near_duplicate_names: list[str] = Field(default_factory=list)
    unsupported_relevance_domains: list[str] = Field(default_factory=list)
    coverage: SeedMapCoverage = Field(default_factory=SeedMapCoverage)


def _seed_files_for_country(country: str) -> list[str]:
    if country.casefold() == "us":
        return list(US_SEED_FILES)
    return ["institution_affiliates.yml"]


def _load_seed_payloads(country: str) -> dict[str, dict[str, Any]]:
    payloads: dict[str, dict[str, Any]] = {}
    for seed_file in _seed_files_for_country(country):
        payload = load_named_config(seed_file)
        payloads[seed_file] = payload if isinstance(payload, dict) else {}
    return payloads


def _issue(
    file: str,
    message: str,
    institution: str | None = None,
    unit: str | None = None,
    field: str | None = None,
) -> ValidationIssue:
    return ValidationIssue(
        file=file,
        institution=institution,
        unit=unit,
        field=field,
        message=message,
    )


def _warn_unknown_fields(
    file: str,
    record: Mapping[str, Any],
    allowed_fields: set[str],
    warnings: list[ValidationIssue],
    institution: str | None,
    unit: str | None = None,
) -> None:
    for field in sorted(set(record) - allowed_fields):
        warnings.append(
            _issue(
                file=file,
                institution=institution,
                unit=unit,
                field=field,
                message="Unknown field is preserved but not currently validated.",
            )
        )


def _validate_required_fields(
    file: str,
    record: Mapping[str, Any],
    required_fields: set[str],
    errors: list[ValidationIssue],
    institution: str | None,
    unit: str | None = None,
) -> None:
    for field in sorted(required_fields):
        if field not in record:
            errors.append(
                _issue(
                    file=file,
                    institution=institution,
                    unit=unit,
                    field=field,
                    message="Required field is missing.",
                )
            )


def _validate_domains(
    domains: Any,
    file: str,
    unsupported_domains: set[str],
    errors: list[ValidationIssue],
    institution: str | None,
    unit: str | None = None,
) -> None:
    if not isinstance(domains, list):
        errors.append(
            _issue(
                file=file,
                institution=institution,
                unit=unit,
                field="relevance_domains",
                message="relevance_domains must be a list.",
            )
        )
        return
    for domain in domains:
        if not isinstance(domain, str) or domain not in KNOWN_RELEVANCE_DOMAINS:
            unsupported_domains.add(str(domain))


def _find_near_duplicate_names(names: list[str]) -> list[str]:
    normalized_to_names: dict[str, list[str]] = defaultdict(list)
    for name in names:
        normalized_to_names[normalize_institution_name(name)].append(name)

    near_duplicates: list[str] = []
    for normalized, grouped_names in normalized_to_names.items():
        if len(grouped_names) > 1:
            near_duplicates.append(f"{normalized}: {', '.join(sorted(grouped_names))}")
    return sorted(near_duplicates)


def validate_seed_payloads(
    payloads_by_file: Mapping[str, Mapping[str, Any]],
    country: str = "us",
) -> SeedMapValidationResult:
    """Validate seed map payloads without reading from disk."""
    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []
    relationship_warnings: list[ValidationIssue] = []
    unsupported_domains: set[str] = set()
    canonical_names: list[str] = []
    duplicate_canonical_names: set[str] = set()
    seen_canonical_names: set[str] = set()

    tier_counts: Counter[str] = Counter()
    parent_type_counts: Counter[str] = Counter()
    unit_type_counts: Counter[str] = Counter()
    unit_domain_counts: Counter[str] = Counter()
    connected_counts: Counter[str] = Counter()
    institutions_with_no_units = 0
    institutions_with_fewer_than_2_units = 0

    for seed_file, payload in payloads_by_file.items():
        institutions = payload.get("institutions", [])
        if not isinstance(institutions, list):
            errors.append(
                _issue(
                    file=seed_file,
                    field="institutions",
                    message="Top-level institutions field must be a list.",
                )
            )
            continue

        for parent in institutions:
            if not isinstance(parent, Mapping):
                errors.append(
                    _issue(
                        file=seed_file,
                        message="Parent institution entry must be a mapping.",
                    )
                )
                continue

            canonical_name = str(parent.get("canonical_name", "")).strip()
            institution_label = canonical_name or "<missing canonical_name>"
            canonical_names.append(institution_label)

            _validate_required_fields(
                seed_file,
                parent,
                REQUIRED_PARENT_FIELDS,
                errors,
                institution_label,
            )
            _warn_unknown_fields(
                seed_file,
                parent,
                REQUIRED_PARENT_FIELDS | OPTIONAL_PARENT_FIELDS,
                warnings,
                institution_label,
            )

            if not canonical_name:
                errors.append(
                    _issue(
                        file=seed_file,
                        institution=institution_label,
                        field="canonical_name",
                        message="canonical_name must be present and non-empty.",
                    )
                )
            else:
                if canonical_name in seen_canonical_names:
                    duplicate_canonical_names.add(canonical_name)
                seen_canonical_names.add(canonical_name)

            if not isinstance(parent.get("aliases"), list):
                errors.append(
                    _issue(
                        file=seed_file,
                        institution=institution_label,
                        field="aliases",
                        message="aliases must be a list.",
                    )
                )

            parent_type = parent.get("parent_type")
            if parent_type not in VALID_PARENT_TYPES:
                errors.append(
                    _issue(
                        file=seed_file,
                        institution=institution_label,
                        field="parent_type",
                        message=f"Unsupported parent_type: {parent_type}",
                    )
                )

            priority_tier = parent.get("priority_tier")
            if priority_tier not in VALID_PRIORITY_TIERS:
                errors.append(
                    _issue(
                        file=seed_file,
                        institution=institution_label,
                        field="priority_tier",
                        message=f"priority_tier must be one of {sorted(VALID_PRIORITY_TIERS)}.",
                    )
                )

            if "verification_status" not in parent:
                errors.append(
                    _issue(
                        file=seed_file,
                        institution=institution_label,
                        field="verification_status",
                        message="verification_status is required.",
                    )
                )

            _validate_domains(
                parent.get("relevance_domains"),
                seed_file,
                unsupported_domains,
                errors,
                institution_label,
            )

            units = parent.get("units", [])
            if not isinstance(units, list):
                errors.append(
                    _issue(
                        file=seed_file,
                        institution=institution_label,
                        field="units",
                        message="units must be a list.",
                    )
                )
                units = []

            unit_names: set[str] = set()
            duplicate_unit_names: set[str] = set()

            tier_counts.update([str(priority_tier)])
            parent_type_counts.update([str(parent_type)])
            connected_counts[institution_label] = len(units)
            if len(units) == 0:
                institutions_with_no_units += 1
            if len(units) < 2:
                institutions_with_fewer_than_2_units += 1

            for unit in units:
                if not isinstance(unit, Mapping):
                    errors.append(
                        _issue(
                            file=seed_file,
                            institution=institution_label,
                            message="Unit entry must be a mapping.",
                        )
                    )
                    continue

                unit_name = str(unit.get("name", "")).strip() or "<missing unit name>"
                _validate_required_fields(
                    seed_file,
                    unit,
                    REQUIRED_UNIT_FIELDS,
                    errors,
                    institution_label,
                    unit_name,
                )
                _warn_unknown_fields(
                    seed_file,
                    unit,
                    REQUIRED_UNIT_FIELDS | OPTIONAL_UNIT_FIELDS,
                    warnings,
                    institution_label,
                    unit_name,
                )

                if unit_name in unit_names:
                    duplicate_unit_names.add(unit_name)
                unit_names.add(unit_name)

                relationship = unit.get("relationship_to_parent")
                if relationship not in VALID_RELATIONSHIPS:
                    errors.append(
                        _issue(
                            file=seed_file,
                            institution=institution_label,
                            unit=unit_name,
                            field="relationship_to_parent",
                            message=f"Unsupported relationship_to_parent: {relationship}",
                        )
                    )

                if (
                    relationship in {"owned_by", "affiliated_with"}
                    and unit.get("verification_status") == UNCERTAIN_VERIFICATION_STATUS
                ):
                    relationship_warnings.append(
                        _issue(
                            file=seed_file,
                            institution=institution_label,
                            unit=unit_name,
                            field="relationship_to_parent",
                            message=(
                                "Formal relationship label is still marked "
                                "curated_seed_needs_verification."
                            ),
                        )
                    )

                if not isinstance(unit.get("source_urls"), list):
                    errors.append(
                        _issue(
                            file=seed_file,
                            institution=institution_label,
                            unit=unit_name,
                            field="source_urls",
                            message="source_urls must be a list, even when empty.",
                        )
                    )

                _validate_domains(
                    unit.get("relevance_domains"),
                    seed_file,
                    unsupported_domains,
                    errors,
                    institution_label,
                    unit_name,
                )

                unit_type_counts.update([str(unit.get("unit_type"))])
                if isinstance(unit.get("relevance_domains"), list):
                    unit_domain_counts.update(str(domain) for domain in unit["relevance_domains"])

            for duplicate_unit_name in sorted(duplicate_unit_names):
                errors.append(
                    _issue(
                        file=seed_file,
                        institution=institution_label,
                        unit=duplicate_unit_name,
                        field="name",
                        message="Duplicate unit name within parent institution.",
                    )
                )

    coverage = SeedMapCoverage(
        total_parent_institutions=len(canonical_names),
        total_units=sum(connected_counts.values()),
        parent_institutions_by_priority_tier=dict(sorted(tier_counts.items())),
        parent_institutions_by_parent_type=dict(sorted(parent_type_counts.items())),
        units_by_unit_type=dict(sorted(unit_type_counts.items())),
        units_by_relevance_domain=dict(sorted(unit_domain_counts.items())),
        institutions_with_no_units=institutions_with_no_units,
        institutions_with_fewer_than_2_units=institutions_with_fewer_than_2_units,
        top_connected_parent_institutions=[
            {"institution": name, "unit_count": count}
            for name, count in connected_counts.most_common(20)
        ],
    )

    for duplicate_canonical_name in sorted(duplicate_canonical_names):
        errors.append(
            _issue(
                file="multiple",
                institution=duplicate_canonical_name,
                field="canonical_name",
                message="Duplicate canonical_name across seed files.",
            )
        )

    return SeedMapValidationResult(
        country=country,
        seed_files=list(payloads_by_file),
        valid=not errors,
        errors=errors,
        warnings=warnings,
        relationship_warnings=relationship_warnings,
        duplicate_canonical_names=sorted(duplicate_canonical_names),
        near_duplicate_names=_find_near_duplicate_names(canonical_names),
        unsupported_relevance_domains=sorted(unsupported_domains),
        coverage=coverage,
    )


def validate_seed_map(country: str = "us") -> SeedMapValidationResult:
    """Validate the configured curated seed map for a country."""
    return validate_seed_payloads(_load_seed_payloads(country), country=country)


def write_validation_json(result: SeedMapValidationResult, output_dir: Path) -> Path:
    """Write structured validation output."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{result.country}_seed_map_validation.json"
    output_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    return output_path


def _format_counter_section(title: str, values: Mapping[str, int]) -> list[str]:
    lines = [f"## {title}", ""]
    if values:
        lines.extend(f"- {key}: {value}" for key, value in values.items())
    else:
        lines.append("- None")
    lines.append("")
    return lines


def write_coverage_markdown(result: SeedMapValidationResult, output_dir: Path) -> Path:
    """Write a human-readable seed map coverage report."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{result.country}_seed_map_coverage.md"
    coverage = result.coverage

    lines = [
        f"# {result.country.upper()} Seed Map Coverage",
        "",
        "## Summary",
        "",
        f"- Validation status: {'pass' if result.valid else 'fail'}",
        f"- Total parent institutions: {coverage.total_parent_institutions}",
        f"- Total units: {coverage.total_units}",
        f"- Institutions with no units: {coverage.institutions_with_no_units}",
        f"- Institutions with fewer than 2 units: {coverage.institutions_with_fewer_than_2_units}",
        f"- Schema errors: {len(result.errors)}",
        f"- General warnings: {len(result.warnings)}",
        f"- Relationship warnings: {len(result.relationship_warnings)}",
        "",
    ]
    lines.extend(
        _format_counter_section(
            "Parent Institutions by Priority Tier",
            coverage.parent_institutions_by_priority_tier,
        )
    )
    lines.extend(
        _format_counter_section(
            "Parent Institutions by Parent Type",
            coverage.parent_institutions_by_parent_type,
        )
    )
    lines.extend(_format_counter_section("Units by Unit Type", coverage.units_by_unit_type))
    lines.extend(
        _format_counter_section("Units by Relevance Domain", coverage.units_by_relevance_domain)
    )

    lines.extend(["## Duplicate or Near-Duplicate Names", ""])
    duplicates = [*result.duplicate_canonical_names, *result.near_duplicate_names]
    lines.extend(f"- {duplicate}" for duplicate in duplicates or ["None detected"])
    lines.append("")

    lines.extend(["## Relationship Warnings", ""])
    if result.relationship_warnings:
        lines.extend(
            "- "
            f"{issue.institution} / {issue.unit}: {issue.message}"
            for issue in result.relationship_warnings
        )
    else:
        lines.append("- None")
    lines.append("")

    lines.extend(["## Unsupported Relevance Domains", ""])
    lines.extend(
        f"- {domain}" for domain in result.unsupported_relevance_domains or ["None detected"]
    )
    lines.append("")

    lines.extend(["## Top 20 Most Connected Parent Institutions", ""])
    lines.extend(
        f"- {entry['institution']}: {entry['unit_count']} units"
        for entry in coverage.top_connected_parent_institutions
    )
    lines.append("")

    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


def write_validation_reports(result: SeedMapValidationResult, output_dir: Path) -> list[Path]:
    """Write JSON validation and Markdown coverage reports."""
    return [
        write_validation_json(result, output_dir),
        write_coverage_markdown(result, output_dir),
    ]
