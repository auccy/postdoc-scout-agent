"""Collect publication evidence from generated discovery query bundles."""

import re
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from postdoc_scout.connectors import ConnectorError, OpenAlexConnector, PubMedConnector
from postdoc_scout.models import (
    ConnectorRunSummary,
    EvidenceCollection,
    EvidenceConnector,
    QueryBundle,
    RetrievedPublicationEvidence,
    SearchQuery,
)


class PublicationConnector(Protocol):
    """Connector interface used by the evidence collector."""

    connector_name: str
    requests_made: int

    def search_publications(
        self,
        query: SearchQuery,
        limit: int = 10,
        year_from: int | None = None,
        year_to: int | None = None,
    ) -> list[RetrievedPublicationEvidence]:
        """Return normalized publication evidence for one query."""

    def close(self) -> None:
        """Release connector resources."""


def load_query_bundle(query_file: Path) -> QueryBundle:
    """Load a query bundle JSON file."""
    return QueryBundle.model_validate_json(query_file.read_text(encoding="utf-8"))


def parse_sources(sources: str | list[str]) -> list[EvidenceConnector]:
    """Parse and validate comma-separated connector source names."""
    raw_sources = sources.split(",") if isinstance(sources, str) else sources
    parsed = [source.strip().casefold() for source in raw_sources if source.strip()]
    allowed = {"openalex", "pubmed"}
    unsupported = sorted(set(parsed) - allowed)
    if unsupported:
        raise ValueError(f"Unsupported evidence source(s): {', '.join(unsupported)}")
    deduped = []
    for source in parsed:
        if source not in deduped:
            deduped.append(source)
    return deduped  # type: ignore[return-value]


def collect_evidence_from_query_file(
    query_file: Path,
    sources: str | list[str] = "openalex,pubmed",
    limit_per_source: int = 20,
    year_from: int | None = 2021,
    year_to: int | None = None,
    connectors: dict[str, PublicationConnector] | None = None,
) -> EvidenceCollection:
    """Load a query bundle file and collect evidence with selected connectors."""
    bundle = load_query_bundle(query_file)
    return collect_evidence(
        bundle=bundle,
        sources=sources,
        limit_per_source=limit_per_source,
        year_from=year_from,
        year_to=year_to,
        query_file=query_file,
        connectors=connectors,
    )


def collect_evidence(
    bundle: QueryBundle,
    sources: str | list[str] = "openalex,pubmed",
    limit_per_source: int = 20,
    year_from: int | None = 2021,
    year_to: int | None = None,
    query_file: Path | None = None,
    connectors: dict[str, PublicationConnector] | None = None,
) -> EvidenceCollection:
    """Collect and deduplicate publication evidence from a query bundle."""
    selected_sources = parse_sources(sources)
    connector_map = connectors or _default_connectors(selected_sources)
    all_records: list[RetrievedPublicationEvidence] = []
    summaries: list[ConnectorRunSummary] = []
    warnings: list[str] = []

    try:
        for source in selected_sources:
            connector = connector_map[source]
            source_records, summary = _run_source(
                source=source,
                connector=connector,
                queries=[query for query in bundle.queries if query.source == source],
                limit_per_source=max(0, limit_per_source),
                year_from=year_from,
                year_to=year_to,
            )
            all_records.extend(source_records)
            summaries.append(summary)
            warnings.extend(summary.warnings)
    finally:
        if connectors is None:
            for connector in connector_map.values():
                connector.close()

    deduped_records = deduplicate_publication_evidence(all_records)
    return EvidenceCollection(
        institution=bundle.institution,
        normalized_institution=bundle.normalized_institution,
        generated_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
        query_file=str(query_file) if query_file else None,
        sources=selected_sources,
        total_queries_run=sum(summary.queries_attempted for summary in summaries),
        total_publications_retrieved=len(all_records),
        deduplicated_publications=len(deduped_records),
        duplicate_publications_removed=max(0, len(all_records) - len(deduped_records)),
        publications=deduped_records,
        connector_summaries=summaries,
        warnings=warnings,
        limitations=[
            "This is publication evidence collection, not final supervisor ranking.",
            "Author identity, authorship role, and supervisor eligibility are not resolved yet.",
            "Affiliation metadata may be incomplete or stale in external publication sources.",
            "Retrieved publications are evidence candidates requiring later scoring and "
            "verification.",
        ],
    )


def _default_connectors(sources: list[EvidenceConnector]) -> dict[str, PublicationConnector]:
    connectors: dict[str, PublicationConnector] = {}
    if "openalex" in sources:
        connectors["openalex"] = OpenAlexConnector()
    if "pubmed" in sources:
        connectors["pubmed"] = PubMedConnector()
    return connectors


def _run_source(
    source: EvidenceConnector,
    connector: PublicationConnector,
    queries: list[SearchQuery],
    limit_per_source: int,
    year_from: int | None,
    year_to: int | None,
) -> tuple[list[RetrievedPublicationEvidence], ConnectorRunSummary]:
    records: list[RetrievedPublicationEvidence] = []
    summary = ConnectorRunSummary(source_connector=source)
    if limit_per_source == 0:
        summary.warnings.append(f"{source}: limit_per_source is 0; no requests were made.")
        return records, summary
    if not queries:
        summary.warnings.append(f"{source}: no matching source-specific queries were found.")
        return records, summary

    for query in queries:
        if len(records) >= limit_per_source:
            break
        remaining = limit_per_source - len(records)
        per_query_limit = min(5, remaining)
        summary.queries_attempted += 1
        requests_before = connector.requests_made
        try:
            query_records = connector.search_publications(
                query=query,
                limit=per_query_limit,
                year_from=year_from,
                year_to=year_to,
            )
            records.extend(query_records[:remaining])
            summary.publications_retrieved += len(query_records[:remaining])
        except ConnectorError as exc:
            summary.errors.append(str(exc))
            summary.warnings.append(f"{source}: {exc}")
        except Exception as exc:  # pragma: no cover - defensive guard for external clients.
            message = f"{source}: unexpected connector failure: {exc}"
            summary.errors.append(message)
            summary.warnings.append(message)
        finally:
            summary.requests_made += max(0, connector.requests_made - requests_before)

    return records, summary


def deduplicate_publication_evidence(
    records: list[RetrievedPublicationEvidence],
) -> list[RetrievedPublicationEvidence]:
    """Deduplicate records by DOI, PMID, then normalized title/year."""
    seen: set[str] = set()
    deduped: list[RetrievedPublicationEvidence] = []
    for record in records:
        key = _publication_key(record)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped


def _publication_key(record: RetrievedPublicationEvidence) -> str:
    publication = record.publication
    if publication.doi:
        return f"doi:{publication.doi.casefold().strip()}"
    if publication.pmid:
        return f"pmid:{publication.pmid.strip()}"
    normalized_title = re.sub(r"\s+", " ", publication.title.casefold()).strip()
    return f"title-year:{normalized_title}:{publication.year or ''}"


def write_evidence_collection_json(collection: EvidenceCollection, output_dir: Path) -> Path:
    """Write evidence collection JSON."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "evidence_collection.json"
    output_path.write_text(collection.model_dump_json(indent=2), encoding="utf-8")
    return output_path


def write_evidence_collection_markdown(collection: EvidenceCollection, output_dir: Path) -> Path:
    """Write an auditable Markdown evidence collection report."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "evidence_collection.md"
    by_source: dict[str, list[RetrievedPublicationEvidence]] = defaultdict(list)
    by_unit: dict[str, list[RetrievedPublicationEvidence]] = defaultdict(list)
    for record in collection.publications:
        by_source[record.source_connector].append(record)
        by_unit[record.matched_unit_name].append(record)

    lines = [
        f"# {collection.institution} Evidence Collection",
        "",
        f"- Generated at: {collection.generated_at}",
        f"- Query file: {collection.query_file or 'in-memory bundle'}",
        f"- Sources: {', '.join(collection.sources)}",
        f"- Queries run: {collection.total_queries_run}",
        f"- Publications retrieved before deduplication: {collection.total_publications_retrieved}",
        f"- Deduplicated publications: {collection.deduplicated_publications}",
        f"- Duplicate publications removed: {collection.duplicate_publications_removed}",
        "",
        "## Connector Summaries",
        "",
    ]
    for summary in collection.connector_summaries:
        lines.extend(
            [
                f"### {summary.source_connector}",
                "",
                f"- Queries attempted: {summary.queries_attempted}",
                f"- Requests made: {summary.requests_made}",
                f"- Publications retrieved: {summary.publications_retrieved}",
                f"- Errors: {len(summary.errors)}",
                "",
            ]
        )

    lines.extend(["## Top Retrieved Publications by Source", ""])
    for source in collection.sources:
        lines.extend([f"### {source}", ""])
        source_records = by_source.get(source, [])[:10]
        if not source_records:
            lines.append("- None")
        for record in source_records:
            lines.append(_publication_markdown_line(record))
        lines.append("")

    lines.extend(["## Top Retrieved Publications by Institution Unit", ""])
    for unit_name in sorted(by_unit):
        lines.extend([f"### {unit_name}", ""])
        for record in by_unit[unit_name][:10]:
            lines.append(_publication_markdown_line(record))
        lines.append("")

    lines.extend(["## Retrieval Warnings and Limitations", ""])
    if collection.warnings:
        lines.extend(f"- {warning}" for warning in collection.warnings)
    else:
        lines.append("- None")
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {limitation}" for limitation in collection.limitations)
    lines.extend(
        [
            "",
            "## Next Step",
            "",
            "Use later scoring and verification layers to assess supervisor identity, "
            "fit, availability, and evidence quality. This report is not a ranked "
            "supervisor list.",
            "",
        ]
    )
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


def write_evidence_collection_reports(
    collection: EvidenceCollection,
    output_dir: Path,
    output_format: str,
) -> list[Path]:
    """Write evidence collection reports in JSON, Markdown, or both."""
    if output_format == "json":
        return [write_evidence_collection_json(collection, output_dir)]
    if output_format == "md":
        return [write_evidence_collection_markdown(collection, output_dir)]
    return [
        write_evidence_collection_json(collection, output_dir),
        write_evidence_collection_markdown(collection, output_dir),
    ]


def _publication_markdown_line(record: RetrievedPublicationEvidence) -> str:
    publication = record.publication
    identifiers = []
    if publication.doi:
        identifiers.append(f"DOI: {publication.doi}")
    if publication.pmid:
        identifiers.append(f"PMID: {publication.pmid}")
    identifier_text = f" ({'; '.join(identifiers)})" if identifiers else ""
    year = publication.year if publication.year is not None else "n.d."
    return (
        f"- `{record.originating_query_id}` {publication.title} "
        f"({year}, {publication.journal or 'unknown source'}){identifier_text}; "
        f"unit: {record.matched_unit_name}"
    )
