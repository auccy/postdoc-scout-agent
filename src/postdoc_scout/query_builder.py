"""Build auditable supervisor-discovery query bundles from institution ecosystems."""

import re
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from postdoc_scout.config import load_named_config
from postdoc_scout.institution_mapper import (
    MappingMode,
    map_institution_ecosystem,
    slugify_institution_name,
)
from postdoc_scout.models import InstitutionUnit, QueryBundle, SearchQuery

BROAD_TERMS = [
    "digital medicine",
    "clinical AI",
    "machine learning",
    "real-world data",
    "electronic health record",
    "clinical decision support",
    "risk prediction",
    "patient stratification",
    "trial enrichment",
    "public health",
    "biomedical informatics",
]

NARROW_TERMS = [
    "AD/ADRD",
    "Alzheimer's disease",
    "dementia",
    "aging",
    "neurodegeneration",
    "cognitive decline",
    "neurology",
    "memory center",
    "biomarker",
    "amyloid",
    "tau",
]

TRANSLATIONAL_TERMS = [
    "prediction",
    "clinical decision support",
    "implementation",
    "patient stratification",
    "disease progression",
]

SOURCE_ORDER = ["pubmed", "openalex", "semantic_scholar", "nih_reporter", "web"]
PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def _load_domain_keyword_terms(mode: MappingMode) -> list[str]:
    data = load_named_config("domain_keywords.yml")
    preferred = data.get("preferred_domains", {})
    terms: list[str] = []
    if isinstance(preferred, dict):
        for key in [
            "digital_medicine",
            "clinical_ai",
            "disease_areas",
            "clinical_data",
            "translational_tasks",
        ]:
            values = preferred.get(key, [])
            if isinstance(values, list):
                terms.extend(str(value) for value in values)
    terms.extend(NARROW_TERMS if mode == MappingMode.NARROW else BROAD_TERMS)
    return _dedupe_strings(terms)


def _dedupe_strings(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        normalized = value.casefold().strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            deduped.append(value)
    return deduped


def _normalize_query_text(query_text: str) -> str:
    lowered = query_text.casefold()
    return re.sub(r"\s+", " ", lowered).strip()


def _unit_priority(unit: InstitutionUnit) -> str:
    if unit.priority in {"high", "medium", "low"}:
        return unit.priority
    if unit.relevance_score >= 0.6:
        return "high"
    if unit.relevance_score >= 0.35:
        return "medium"
    return "low"


def _mode_terms_for_unit(unit: InstitutionUnit, mode: MappingMode) -> list[str]:
    mode_terms = NARROW_TERMS if mode == MappingMode.NARROW else BROAD_TERMS
    domains = list(unit.relevance_domains)
    if mode == MappingMode.NARROW:
        selected = [
            term
            for term in [*domains, *mode_terms]
            if any(
                marker in term.casefold()
                for marker in [
                    "ad/",
                    "alzheimer",
                    "aging",
                    "dementia",
                    "neuro",
                    "cognitive",
                    "memory",
                    "amyloid",
                    "tau",
                ]
            )
        ]
        return _dedupe_strings(selected or mode_terms[:5])[:5]
    selected = [
        term
        for term in [*domains, *mode_terms]
        if any(
            marker in term.casefold()
            for marker in [
                "digital",
                "clinical ai",
                "ehr",
                "real-world",
                "oncology",
                "decision support",
                "risk",
                "prediction",
                "stratification",
                "trial",
                "public health",
                "informatics",
            ]
        )
    ]
    return _dedupe_strings(selected or mode_terms[:6])[:6]


def _quoted_or_terms(terms: list[str]) -> str:
    return " OR ".join(f'"{term}"' for term in terms)


def _source_query_text(source: str, unit: InstitutionUnit, terms: list[str]) -> str:
    source_terms = _quoted_or_terms(terms[:4])
    translational = _quoted_or_terms(TRANSLATIONAL_TERMS[:3])
    if source == "pubmed":
        return f'("{unit.name}"[Affiliation]) AND ({source_terms}) AND ({translational})'
    if source == "openalex":
        return f'institution:"{unit.name}" concepts:({source_terms}) keywords:prediction'
    if source == "semantic_scholar":
        return f'"{unit.name}" ({source_terms}) publication supervisor clinical translation'
    if source == "nih_reporter":
        return f'organization:"{unit.name}" terms:({source_terms})'
    if source == "web":
        return f'"{unit.name}" "{terms[0]}" "faculty" "postdoctoral fellow"'
    return f'"{unit.name}" {source_terms}'


def _expected_evidence_type(source: str) -> str:
    return {
        "pubmed": "publication",
        "openalex": "author",
        "semantic_scholar": "publication",
        "nih_reporter": "grant",
        "web": "lab_page",
    }.get(source, "other")


def _query_rationale(source: str, unit: InstitutionUnit, terms: list[str]) -> str:
    return (
        f"{source} query for {unit.name} ({unit.unit_type}) using "
        f"{', '.join(terms[:4])} to identify potential supervisor evidence."
    )


def _build_query(
    index: int,
    source: str,
    institution: str,
    unit: InstitutionUnit,
    mode: MappingMode,
    terms: list[str],
) -> SearchQuery:
    return SearchQuery(
        query_id=f"q_{index:04d}_{source}",
        query_text=_source_query_text(source, unit, terms),
        source=source,
        institution=institution,
        unit_name=unit.name,
        unit_type=unit.unit_type,
        mode=mode.value,
        relevance_domains=_dedupe_strings([*unit.relevance_domains, *terms]),
        priority=_unit_priority(unit),
        rationale=_query_rationale(source, unit, terms),
        expected_evidence_type=_expected_evidence_type(source),
        notes="Template query only; no external API call has been made.",
    )


def _dedupe_queries(queries: list[SearchQuery]) -> list[SearchQuery]:
    seen: set[tuple[str, str, str]] = set()
    deduped: list[SearchQuery] = []
    for query in queries:
        key = (query.source, query.unit_name.casefold(), _normalize_query_text(query.query_text))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(query)
    return deduped


def build_query_bundle(
    institution: str,
    mode: MappingMode = MappingMode.BROAD,
    country: str = "us",
    limit: int = 100,
) -> QueryBundle:
    """Build a deterministic discovery query bundle from an institution ecosystem."""
    ecosystem = map_institution_ecosystem(institution=institution, mode=mode, country=country)
    if not ecosystem.units:
        return QueryBundle(
            institution=ecosystem.institution.name,
            normalized_institution=ecosystem.institution.normalized_name,
            mode=mode.value,
            generated_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
            queries=[],
            limitations=[
                *ecosystem.limitations,
                "No queries were generated because no curated ecosystem units were found.",
            ],
            ecosystem_summary={
                "unit_count": 0,
                "units_used": [],
                "country": country,
            },
        )

    _load_domain_keyword_terms(mode)
    sorted_units = sorted(
        ecosystem.units,
        key=lambda unit: (
            PRIORITY_ORDER.get(_unit_priority(unit), 9),
            -unit.relevance_score,
            unit.name,
        ),
    )
    queries: list[SearchQuery] = []
    query_index = 1
    for unit in sorted_units:
        terms = _mode_terms_for_unit(unit, mode)
        for source in SOURCE_ORDER:
            queries.append(
                _build_query(
                    query_index,
                    source,
                    ecosystem.institution.name,
                    unit,
                    mode,
                    terms,
                )
            )
            query_index += 1

    deduped_queries = _dedupe_queries(queries)
    deduped_queries.sort(
        key=lambda query: (
            PRIORITY_ORDER.get(query.priority, 9),
            SOURCE_ORDER.index(query.source) if query.source in SOURCE_ORDER else 99,
            query.unit_name,
            query.query_id,
        )
    )
    limited_queries = deduped_queries[: max(0, limit)]
    for index, query in enumerate(limited_queries, start=1):
        query.query_id = f"q_{index:04d}_{query.source}"

    return QueryBundle(
        institution=ecosystem.institution.name,
        normalized_institution=ecosystem.institution.normalized_name,
        mode=mode.value,
        generated_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
        queries=limited_queries,
        limitations=[
            "Query bundle is deterministic and template-based.",
            "No external APIs, web scraping, or source verification were performed.",
            "Institution-unit relationships inherit curated seed-map limitations.",
            "External connectors will consume these query templates later.",
        ],
        ecosystem_summary={
            "unit_count": len(ecosystem.units),
            "units_used": [unit.name for unit in sorted_units],
            "country": country,
        },
    )


def write_query_bundle_json(bundle: QueryBundle, output_dir: Path) -> Path:
    """Write query bundle JSON."""
    output_dir.mkdir(parents=True, exist_ok=True)
    slug = slugify_institution_name(bundle.institution)
    output_path = output_dir / f"{slug}_discovery_queries.json"
    output_path.write_text(bundle.model_dump_json(indent=2), encoding="utf-8")
    return output_path


def write_query_bundle_markdown(bundle: QueryBundle, output_dir: Path) -> Path:
    """Write query bundle Markdown report."""
    output_dir.mkdir(parents=True, exist_ok=True)
    slug = slugify_institution_name(bundle.institution)
    output_path = output_dir / f"{slug}_discovery_queries.md"
    queries_by_source: dict[str, list[SearchQuery]] = defaultdict(list)
    queries_by_unit: dict[str, list[SearchQuery]] = defaultdict(list)
    for query in bundle.queries:
        queries_by_source[query.source].append(query)
        queries_by_unit[query.unit_name].append(query)

    lines = [
        f"# {bundle.institution} Discovery Queries",
        "",
        f"- Normalized institution: {bundle.normalized_institution}",
        f"- Mode: {bundle.mode}",
        f"- Generated at: {bundle.generated_at}",
        f"- Query count: {len(bundle.queries)}",
        "",
        "## Ecosystem Units Used",
        "",
    ]
    lines.extend(f"- {unit}" for unit in bundle.ecosystem_summary.get("units_used", []))
    lines.extend(["", "## Top High-Priority Queries", ""])
    high_priority = [query for query in bundle.queries if query.priority == "high"][:10]
    lines.extend(
        f"- `{query.query_id}` [{query.source}] {query.unit_name}: {query.query_text}"
        for query in high_priority or []
    )
    if not high_priority:
        lines.append("- None")
    lines.extend(["", "## Queries by Source", ""])
    for source in SOURCE_ORDER:
        source_queries = queries_by_source.get(source, [])
        if not source_queries:
            continue
        lines.extend([f"### {source}", ""])
        lines.extend(
            f"- `{query.query_id}` ({query.priority}) {query.unit_name}: {query.query_text}"
            for query in source_queries
        )
        lines.append("")
    lines.extend(["## Queries by Unit", ""])
    for unit_name in sorted(queries_by_unit):
        lines.extend([f"### {unit_name}", ""])
        lines.extend(
            f"- `{query.query_id}` [{query.source}] {query.query_text}"
            for query in queries_by_unit[unit_name]
        )
        lines.append("")
    lines.extend(["## Limitations", ""])
    lines.extend(f"- {limitation}" for limitation in bundle.limitations)
    lines.extend(
        [
            "",
            "## Next Step",
            "",
            "Future PubMed, OpenAlex, Semantic Scholar, NIH RePORTER, and web/lab-page "
            "connectors will consume these query bundles and attach source evidence to "
            "supervisor candidates.",
            "",
        ]
    )
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


def write_query_bundle_reports(
    bundle: QueryBundle,
    output_dir: Path,
    output_format: str,
) -> list[Path]:
    """Write query bundle reports in JSON, Markdown, or both."""
    if output_format == "json":
        return [write_query_bundle_json(bundle, output_dir)]
    if output_format == "md":
        return [write_query_bundle_markdown(bundle, output_dir)]
    return [
        write_query_bundle_json(bundle, output_dir),
        write_query_bundle_markdown(bundle, output_dir),
    ]
