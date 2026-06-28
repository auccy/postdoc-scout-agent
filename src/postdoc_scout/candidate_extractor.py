"""Extract preliminary supervisor candidate clusters from publication evidence."""

import csv
import re
from collections import defaultdict
from pathlib import Path

from postdoc_scout.models import (
    AuthorMention,
    AuthorMentionPosition,
    CandidateCluster,
    CandidateExtractionReport,
    EvidenceCollection,
    EvidenceItem,
    Publication,
    RetrievedPublicationEvidence,
)

RECENT_YEAR_THRESHOLD = 2021
CLINICAL_RELEVANCE_MARKERS = [
    "ad/adrd",
    "alzheimer",
    "aging",
    "biomedical ai",
    "cancer",
    "clinical ai",
    "clinical decision support",
    "digital health",
    "digital medicine",
    "ehr",
    "implementation",
    "oncology",
    "patient stratification",
    "prediction",
    "real-world data",
    "risk",
    "rwd",
    "trial enrichment",
]
METHOD_HEAVY_MARKERS = [
    "benchmark-only",
    "foundation model architecture",
    "optimization theory",
    "simulation-only",
    "statistical theory",
]
CONSORTIUM_MARKERS = ["consortium", "collaboration", "study group", "working group"]


def normalize_author_name(name: str) -> str:
    """Conservatively normalize names without expanding initials."""
    normalized = name.casefold().replace(".", " ")
    normalized = re.sub(r"[^a-z0-9\s-]+", " ", normalized)
    normalized = normalized.replace("-", " ")
    return " ".join(normalized.split())


def load_evidence_collection(evidence_file: Path) -> EvidenceCollection:
    """Load an evidence collection JSON file."""
    return EvidenceCollection.model_validate_json(evidence_file.read_text(encoding="utf-8"))


def extract_candidates_from_file(
    evidence_file: Path,
    institution: str,
    mode: str,
    min_publications: int = 1,
) -> CandidateExtractionReport:
    """Load evidence JSON and extract preliminary candidate clusters."""
    collection = load_evidence_collection(evidence_file)
    return extract_candidates(
        collection=collection,
        institution=institution,
        mode=mode,
        source_evidence_file=evidence_file,
        min_publications=min_publications,
    )


def extract_candidates(
    collection: EvidenceCollection,
    institution: str,
    mode: str,
    source_evidence_file: Path | str,
    min_publications: int = 1,
) -> CandidateExtractionReport:
    """Extract author mentions and cluster them into preliminary candidates."""
    mentions: list[AuthorMention] = []
    publication_lookup: dict[str, Publication] = {}
    evidence_lookup: dict[str, EvidenceItem] = {}

    for record in collection.publications:
        publication_key = _publication_key(record.publication)
        publication_lookup[publication_key] = record.publication
        for evidence_item in record.publication.evidence_items:
            evidence_lookup[evidence_item.evidence_id] = evidence_item
        mentions.extend(extract_author_mentions(record))

    clusters = cluster_author_mentions(
        mentions=mentions,
        records=collection.publications,
        min_publications=max(1, min_publications),
    )
    sorted_clusters = sorted(
        clusters,
        key=lambda cluster: (
            -_cluster_strength(cluster),
            cluster.display_name,
            cluster.candidate_id,
        ),
    )

    return CandidateExtractionReport(
        institution=institution,
        mode=mode,
        source_evidence_file=str(source_evidence_file),
        total_publications_processed=len(collection.publications),
        total_author_mentions=len(mentions),
        total_candidate_clusters=len(sorted_clusters),
        candidate_clusters=sorted_clusters,
        limitations=[
            "Author disambiguation is preliminary and conservative.",
            "Affiliation metadata may be incomplete in publication sources.",
            "Candidate identity is not verified.",
            "Final supervisor scoring has not yet been applied.",
        ],
        warnings=_report_warnings(sorted_clusters),
    )


def extract_author_mentions(record: RetrievedPublicationEvidence) -> list[AuthorMention]:
    """Extract ordered author mentions from one retrieved publication record."""
    publication = record.publication
    mentions = []
    for index, author_name in enumerate(publication.authors):
        normalized_name = normalize_author_name(author_name)
        if not normalized_name:
            continue
        affiliations = _author_affiliations(publication, author_name)
        warnings = _mention_warnings(author_name, affiliations, publication)
        position = _author_position(publication, author_name, index)
        mentions.append(
            AuthorMention(
                author_name=author_name,
                normalized_author_name=normalized_name,
                publication_title=publication.title,
                publication_year=publication.year,
                journal=publication.journal,
                author_position=position,
                affiliations=affiliations,
                matched_institution_units=_matched_units(affiliations, record.matched_unit_name),
                source_connector=record.source_connector,
                evidence_id=_evidence_id(record),
                originating_query_id=record.originating_query_id,
                relevance_domains=_dedupe(
                    [*publication.relevance_domains, *record.relevance_domains]
                ),
                confidence=_mention_confidence(position, affiliations, warnings),
                warnings=warnings,
            )
        )
    return mentions


def cluster_author_mentions(
    mentions: list[AuthorMention],
    records: list[RetrievedPublicationEvidence],
    min_publications: int = 1,
) -> list[CandidateCluster]:
    """Cluster author mentions by conservative normalized name."""
    records_by_title_year = {
        _title_year_key(record.publication.title, record.publication.year): record
        for record in records
    }
    grouped: dict[str, list[AuthorMention]] = defaultdict(list)
    for mention in mentions:
        grouped[mention.normalized_author_name].append(mention)

    clusters: list[CandidateCluster] = []
    for index, (normalized_name, group) in enumerate(sorted(grouped.items()), start=1):
        unique_publication_keys = {
            _title_year_key(mention.publication_title, mention.publication_year)
            for mention in group
        }
        if len(unique_publication_keys) < min_publications:
            continue
        publications = [
            records_by_title_year[key].publication
            for key in unique_publication_keys
            if key in records_by_title_year
        ]
        evidence_items = [
            item
            for publication in publications
            for item in publication.evidence_items
            if item.evidence_id in {mention.evidence_id for mention in group}
        ]
        senior_count = sum(
            1 for mention in group if mention.author_position in {"last", "senior"}
        )
        corresponding_count = sum(
            1 for mention in group if mention.author_position == "corresponding"
        )
        first_count = sum(
            1 for mention in group if mention.author_position in {"first", "co_first"}
        )
        possible_affiliations = _dedupe(
            [affiliation for mention in group for affiliation in mention.affiliations]
        )
        matched_units = _dedupe(
            [unit for mention in group for unit in mention.matched_institution_units]
        )
        ambiguity_warnings = _cluster_warnings(group, possible_affiliations)
        confidence = _candidate_confidence(
            group=group,
            senior_count=senior_count,
            corresponding_count=corresponding_count,
            first_count=first_count,
            matched_units=matched_units,
            ambiguity_warnings=ambiguity_warnings,
        )
        clusters.append(
            CandidateCluster(
                candidate_id=f"cand_{index:04d}",
                display_name=_display_name(group),
                normalized_name=normalized_name,
                possible_affiliations=possible_affiliations,
                matched_institution_units=matched_units,
                publications=publications,
                author_mentions=group,
                evidence_items=evidence_items,
                senior_author_count=senior_count,
                corresponding_author_count=corresponding_count,
                first_author_count=first_count,
                recent_publication_count=sum(
                    1
                    for publication in publications
                    if publication.year is not None and publication.year >= RECENT_YEAR_THRESHOLD
                ),
                high_impact_publication_count=sum(
                    1 for publication in publications if publication.is_high_impact_journal
                ),
                field_leading_publication_count=sum(
                    1 for publication in publications if publication.is_field_leading_journal
                ),
                relevance_domains=_dedupe(
                    [domain for mention in group for domain in mention.relevance_domains]
                ),
                candidate_confidence=confidence,
                ambiguity_warnings=ambiguity_warnings,
                notes=(
                    "Preliminary author cluster only; verify identity, affiliation, "
                    "and supervisor status before use."
                ),
            )
        )
    return clusters


def write_candidate_extraction_json(report: CandidateExtractionReport, output_dir: Path) -> Path:
    """Write candidate extraction JSON."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "candidate_extraction.json"
    output_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return output_path


def write_candidate_extraction_markdown(
    report: CandidateExtractionReport,
    output_dir: Path,
) -> Path:
    """Write candidate extraction Markdown report."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "candidate_extraction.md"
    lines = [
        f"# {report.institution} Candidate Extraction",
        "",
        f"- Mode: {report.mode}",
        f"- Source evidence file: {report.source_evidence_file}",
        f"- Total publications processed: {report.total_publications_processed}",
        f"- Total author mentions: {report.total_author_mentions}",
        f"- Total candidate clusters: {report.total_candidate_clusters}",
        "",
        "## Top Candidate Clusters",
        "",
    ]
    for cluster in report.candidate_clusters[:25]:
        evidence_ids = _dedupe(
            [mention.evidence_id for mention in cluster.author_mentions if mention.evidence_id]
        )
        lines.extend(
            [
                f"### {cluster.display_name}",
                "",
                f"- Candidate ID: `{cluster.candidate_id}`",
                f"- Confidence: {cluster.candidate_confidence:.2f}",
                f"- Possible affiliations: "
                f"{', '.join(cluster.possible_affiliations) or 'None available'}",
                f"- Matched institution units: "
                f"{', '.join(cluster.matched_institution_units) or 'None'}",
                f"- Senior/last author count: {cluster.senior_author_count}",
                f"- Corresponding author count: {cluster.corresponding_author_count}",
                f"- First author count: {cluster.first_author_count}",
                f"- Recent publication count: {cluster.recent_publication_count}",
                f"- Relevance domains: {', '.join(cluster.relevance_domains) or 'None'}",
                f"- Evidence IDs: {', '.join(evidence_ids) or 'None'}",
                f"- Ambiguity warnings: "
                f"{'; '.join(cluster.ambiguity_warnings) or 'None'}",
                "",
            ]
        )
    if not report.candidate_clusters:
        lines.append("- None")
        lines.append("")
    lines.extend(["## Report Warnings", ""])
    lines.extend(f"- {warning}" for warning in report.warnings or ["None"])
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {limitation}" for limitation in report.limitations)
    lines.append("")
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


def write_candidate_extraction_csv(report: CandidateExtractionReport, output_dir: Path) -> Path:
    """Write candidate extraction CSV summary."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "candidate_extraction.csv"
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "candidate_id",
                "display_name",
                "possible_affiliations",
                "matched_institution_units",
                "senior_author_count",
                "corresponding_author_count",
                "first_author_count",
                "recent_publication_count",
                "high_impact_publication_count",
                "field_leading_publication_count",
                "relevance_domains",
                "candidate_confidence",
                "ambiguity_warnings",
            ],
        )
        writer.writeheader()
        for cluster in report.candidate_clusters:
            writer.writerow(
                {
                    "candidate_id": cluster.candidate_id,
                    "display_name": cluster.display_name,
                    "possible_affiliations": "; ".join(cluster.possible_affiliations),
                    "matched_institution_units": "; ".join(cluster.matched_institution_units),
                    "senior_author_count": cluster.senior_author_count,
                    "corresponding_author_count": cluster.corresponding_author_count,
                    "first_author_count": cluster.first_author_count,
                    "recent_publication_count": cluster.recent_publication_count,
                    "high_impact_publication_count": cluster.high_impact_publication_count,
                    "field_leading_publication_count": cluster.field_leading_publication_count,
                    "relevance_domains": "; ".join(cluster.relevance_domains),
                    "candidate_confidence": f"{cluster.candidate_confidence:.3f}",
                    "ambiguity_warnings": "; ".join(cluster.ambiguity_warnings),
                }
            )
    return output_path


def write_candidate_extraction_reports(
    report: CandidateExtractionReport,
    output_dir: Path,
    output_format: str,
) -> list[Path]:
    """Write candidate extraction reports as JSON, Markdown, CSV, or all."""
    if output_format == "json":
        return [write_candidate_extraction_json(report, output_dir)]
    if output_format == "md":
        return [write_candidate_extraction_markdown(report, output_dir)]
    if output_format == "csv":
        return [write_candidate_extraction_csv(report, output_dir)]
    return [
        write_candidate_extraction_json(report, output_dir),
        write_candidate_extraction_markdown(report, output_dir),
        write_candidate_extraction_csv(report, output_dir),
    ]


def _author_affiliations(publication: Publication, author_name: str) -> list[str]:
    direct = publication.author_affiliations.get(author_name, [])
    if direct:
        return _dedupe(direct)
    normalized_author = normalize_author_name(author_name)
    for stored_author, affiliations in publication.author_affiliations.items():
        if normalize_author_name(stored_author) == normalized_author:
            return _dedupe(affiliations)
    return _dedupe(publication.affiliations)


def _author_position(
    publication: Publication,
    author_name: str,
    index: int,
) -> AuthorMentionPosition:
    if any(
        normalize_author_name(author_name) == normalize_author_name(corresponding)
        for corresponding in publication.corresponding_authors
    ):
        return "corresponding"
    if len(publication.authors) == 1:
        return "unknown"
    if index == 0:
        return "first"
    if index == len(publication.authors) - 1:
        return "last"
    return "middle"


def _mention_warnings(
    author_name: str,
    affiliations: list[str],
    publication: Publication,
) -> list[str]:
    warnings = []
    lowered_name = author_name.casefold()
    if any(marker in lowered_name for marker in CONSORTIUM_MARKERS):
        warnings.append("Consortium or group authorship; do not treat as an individual candidate.")
    if _is_initials_only(author_name):
        warnings.append("Initials-only author name; identity confidence is low.")
    if not affiliations:
        warnings.append("No affiliation metadata available for this author mention.")
    publication_text = f"{publication.title} {publication.abstract}".casefold()
    has_clinical_signal = any(marker in publication_text for marker in CLINICAL_RELEVANCE_MARKERS)
    has_method_signal = any(marker in publication_text for marker in METHOD_HEAVY_MARKERS)
    if has_method_signal and not has_clinical_signal:
        warnings.append("Method-heavy publication with limited clinical/digital medicine signal.")
    return warnings


def _mention_confidence(
    position: AuthorMentionPosition,
    affiliations: list[str],
    warnings: list[str],
) -> float:
    confidence = 0.45
    if position in {"last", "senior", "corresponding"}:
        confidence += 0.25
    elif position in {"first", "co_first"}:
        confidence += 0.1
    elif position == "middle":
        confidence -= 0.15
    if affiliations:
        confidence += 0.1
    if warnings:
        confidence -= min(0.25, 0.08 * len(warnings))
    return _clamp(confidence)


def _matched_units(affiliations: list[str], matched_unit_name: str) -> list[str]:
    normalized_unit = _normalize_affiliation(matched_unit_name)
    if any(normalized_unit in _normalize_affiliation(affiliation) for affiliation in affiliations):
        return [matched_unit_name]
    return []


def _candidate_confidence(
    group: list[AuthorMention],
    senior_count: int,
    corresponding_count: int,
    first_count: int,
    matched_units: list[str],
    ambiguity_warnings: list[str],
) -> float:
    unique_publications = {
        _title_year_key(mention.publication_title, mention.publication_year)
        for mention in group
    }
    middle_only = all(mention.author_position == "middle" for mention in group)
    confidence = sum(mention.confidence for mention in group) / max(1, len(group))
    if senior_count:
        confidence += 0.15
    if corresponding_count:
        confidence += 0.15
    if first_count and not senior_count:
        confidence += 0.05
    if len(unique_publications) >= 2:
        confidence += 0.12
    if matched_units:
        confidence += 0.1
    if middle_only:
        confidence -= 0.25
    if ambiguity_warnings:
        confidence -= min(0.25, 0.06 * len(ambiguity_warnings))
    return _clamp(confidence)


def _cluster_warnings(group: list[AuthorMention], affiliations: list[str]) -> list[str]:
    warnings = _dedupe([warning for mention in group for warning in mention.warnings])
    normalized_affiliations = {
        _normalize_affiliation(affiliation)
        for affiliation in affiliations
        if _normalize_affiliation(affiliation)
    }
    if not affiliations:
        warnings.append("Cluster formed by name only because affiliation metadata is missing.")
    if len(normalized_affiliations) > 1:
        warnings.append(
            "Same normalized author name appears with multiple affiliation strings; "
            "identity is not verified."
        )
    if all(mention.author_position == "middle" for mention in group):
        warnings.append(
            "Only middle-author mentions found; preliminary supervisor confidence is low."
        )
    return _dedupe(warnings)


def _report_warnings(clusters: list[CandidateCluster]) -> list[str]:
    warnings = []
    if any(cluster.ambiguity_warnings for cluster in clusters):
        warnings.append("Some candidate clusters include ambiguity warnings.")
    if any(cluster.candidate_confidence < 0.5 for cluster in clusters):
        warnings.append("Some candidate clusters have low preliminary confidence.")
    return warnings


def _display_name(group: list[AuthorMention]) -> str:
    return max((mention.author_name for mention in group), key=lambda value: (len(value), value))


def _evidence_id(record: RetrievedPublicationEvidence) -> str:
    if record.publication.evidence_items:
        return record.publication.evidence_items[0].evidence_id
    publication = record.publication
    if publication.doi:
        return f"doi:{publication.doi}"
    if publication.pmid:
        return f"pmid:{publication.pmid}"
    return f"title:{_title_year_key(publication.title, publication.year)}"


def _publication_key(publication: Publication) -> str:
    if publication.doi:
        return f"doi:{publication.doi.casefold()}"
    if publication.pmid:
        return f"pmid:{publication.pmid}"
    return _title_year_key(publication.title, publication.year)


def _title_year_key(title: str, year: int | None) -> str:
    normalized_title = re.sub(r"\s+", " ", title.casefold()).strip()
    return f"{normalized_title}::{year or ''}"


def _cluster_strength(cluster: CandidateCluster) -> float:
    return (
        cluster.candidate_confidence
        + 0.2 * cluster.senior_author_count
        + 0.2 * cluster.corresponding_author_count
        + 0.08 * cluster.recent_publication_count
        + 0.05 * len(cluster.matched_institution_units)
    )


def _normalize_affiliation(value: str) -> str:
    normalized = value.casefold().replace("&", " and ")
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return " ".join(normalized.split())


def _is_initials_only(name: str) -> bool:
    parts = [part for part in re.split(r"[\s.]+", name.strip()) if part]
    return bool(parts) and all(len(part) == 1 for part in parts)


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    deduped = []
    for value in values:
        normalized = value.casefold().strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            deduped.append(value)
    return deduped


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, round(value, 3)))
