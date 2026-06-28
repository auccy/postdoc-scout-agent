"""Command-line interface for postdoc-scout-agent."""

from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from postdoc_scout.candidate_enricher import (
    enrich_candidates_from_file,
    parse_enrichment_sources,
    write_enriched_candidate_reports,
)
from postdoc_scout.candidate_extractor import (
    extract_candidates_from_file,
    write_candidate_extraction_reports,
)
from postdoc_scout.candidate_ranker import (
    rank_candidates_from_files,
    write_candidate_ranking_reports,
)
from postdoc_scout.evidence_collector import (
    collect_evidence_from_query_file,
    parse_sources,
    write_evidence_collection_reports,
)
from postdoc_scout.institution_mapper import (
    InstitutionTier,
    MappingMode,
    OutputFormat,
    list_parent_institutions,
    map_institution_ecosystem,
    write_ecosystem_reports,
)
from postdoc_scout.models import PipelineConfig
from postdoc_scout.opening_signals import detect_openings_from_file
from postdoc_scout.pipeline import run_pipeline
from postdoc_scout.publication_calibration import calibrate_publications_from_ranked_file
from postdoc_scout.query_builder import build_query_bundle, write_query_bundle_reports
from postdoc_scout.review_tracker import (
    export_shortlist,
    init_review_tracker,
    update_candidate_review,
)
from postdoc_scout.scoring import score_candidates_from_file
from postdoc_scout.scout import ScoutMode, ScoutRequest, run_placeholder_scout
from postdoc_scout.seed_map_validation import validate_seed_map, write_validation_reports

app = typer.Typer(
    name="postdoc-scout",
    help="Scout potential postdoc supervisors in translational digital medicine and clinical AI.",
    no_args_is_help=True,
)
console = Console()


class CandidateExtractionFormat(str, Enum):
    """Supported candidate extraction output formats."""

    JSON = "json"
    MD = "md"
    CSV = "csv"
    ALL = "all"


class CandidateRankingFormat(str, Enum):
    """Supported candidate ranking output formats."""

    JSON = "json"
    MD = "md"
    CSV = "csv"
    ALL = "all"


class EnrichmentFormat(str, Enum):
    """Supported enrichment output formats."""

    JSON = "json"
    MD = "md"
    CSV = "csv"
    ALL = "all"


class PipelineFormat(str, Enum):
    """Supported pipeline output formats."""

    JSON = "json"
    MD = "md"
    ALL = "all"


class OpeningSignalFormat(str, Enum):
    """Supported opening-signal output formats."""

    JSON = "json"
    MD = "md"
    CSV = "csv"
    ALL = "all"


class PublicationCalibrationFormat(str, Enum):
    """Supported publication calibration output formats."""

    JSON = "json"
    MD = "md"
    CSV = "csv"
    ALL = "all"


class ReviewStatusOption(str, Enum):
    """Manual review status options."""

    INTERESTED = "interested"
    MAYBE = "maybe"
    LOW_PRIORITY = "low_priority"
    DO_NOT_CONTACT = "do_not_contact"
    NEEDS_MORE_REVIEW = "needs_more_review"


class OutreachStatusOption(str, Enum):
    """Manual outreach tracking status options."""

    NOT_CONTACTED = "not_contacted"
    DRAFTED = "drafted"
    CONTACTED = "contacted"
    REPLIED = "replied"
    FOLLOW_UP_NEEDED = "follow_up_needed"
    REJECTED = "rejected"
    ARCHIVED = "archived"


@app.callback()
def main() -> None:
    """Postdoc supervisor scouting command group."""


@app.command()
def scout(
    institution: Annotated[str, typer.Option(help="Institution to scout.")],
    mode: Annotated[
        ScoutMode,
        typer.Option(help="Search mode controlling breadth and specificity."),
    ] = ScoutMode.BROAD,
    limit: Annotated[int, typer.Option(min=1, max=100, help="Maximum candidates to return.")] = 20,
) -> None:
    """Run a placeholder supervisor scouting pass."""
    request = ScoutRequest(institution=institution, mode=mode, limit=limit)
    result = run_placeholder_scout(request)

    table = Table(title="Postdoc Scout Placeholder")
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("Institution", result.institution)
    table.add_row("Mode", result.mode.value)
    table.add_row("Limit", str(result.limit))
    table.add_row("Status", result.status)
    table.add_row("Focus", ", ".join(result.focus_areas))

    console.print(table)
    console.print(
        "[yellow]This MVP skeleton does not query live sources yet. "
        "Add source adapters before using results for decisions.[/yellow]"
    )


@app.command("map-institution")
def map_institution_command(
    institution: Annotated[str, typer.Option(help="Institution to map.")],
    mode: Annotated[
        MappingMode,
        typer.Option(help="Mapping mode for broad or narrow translational focus."),
    ] = MappingMode.BROAD,
    output_dir: Annotated[
        Path,
        typer.Option(help="Directory where ecosystem reports will be written."),
    ] = Path("outputs"),
    country: Annotated[
        str,
        typer.Option(help="Country seed layer to use. Only 'us' is curated for now."),
    ] = "us",
    output_format: Annotated[
        OutputFormat,
        typer.Option("--format", help="Report format to write."),
    ] = OutputFormat.BOTH,
) -> None:
    """Map an institution into an auditable biomedical research ecosystem."""
    ecosystem = map_institution_ecosystem(institution=institution, mode=mode, country=country)
    output_paths = write_ecosystem_reports(ecosystem, output_dir, output_format)

    table = Table(title="Institution Ecosystem Map")
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("Institution", ecosystem.institution.name)
    table.add_row("Mode", ecosystem.mode)
    table.add_row("Units", str(len(ecosystem.units)))
    table.add_row("Outputs", "\n".join(str(path) for path in output_paths))

    console.print(table)
    if ecosystem.units:
        console.print("[bold]Top units[/bold]")
        for unit in ecosystem.units[:5]:
            console.print(
                f"- {unit.name} ({unit.unit_type}, score={unit.relevance_score:.3f})"
            )
    else:
        console.print(
            "[yellow]No curated institution match found; empty reports were written.[/yellow]"
        )


@app.command("list-institutions")
def list_institutions_command(
    country: Annotated[
        str,
        typer.Option(help="Country seed layer to list. Only 'us' is curated for now."),
    ] = "us",
    tier: Annotated[
        InstitutionTier,
        typer.Option(help="Priority tier filter."),
    ] = InstitutionTier.ALL,
) -> None:
    """List curated parent institutions available to the mapper."""
    entries = list_parent_institutions(country=country, tier=tier)

    table = Table(title="Curated Institution Seed Map")
    table.add_column("Tier", style="bold")
    table.add_column("Institution")
    table.add_column("Type")
    table.add_column("Location")
    table.add_column("Units", justify="right")

    for entry in entries:
        table.add_row(
            str(entry.get("priority_tier", "C")),
            str(entry.get("canonical_name") or entry.get("name")),
            str(entry.get("parent_type", "other")),
            f"{entry.get('city', '')}, {entry.get('state', '')}".strip(", "),
            str(len(entry.get("units", []))),
        )

    console.print(table)
    console.print(f"{len(entries)} parent institutions listed.")


@app.command("validate-seed-map")
def validate_seed_map_command(
    country: Annotated[
        str,
        typer.Option(help="Country seed layer to validate. Only 'us' is curated for now."),
    ] = "us",
    output_dir: Annotated[
        Path,
        typer.Option(help="Directory where validation reports will be written."),
    ] = Path("outputs"),
) -> None:
    """Validate curated seed-map schema and write coverage reports."""
    result = validate_seed_map(country=country)
    output_paths = write_validation_reports(result, output_dir)

    table = Table(title="Seed Map Validation")
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("Country", result.country)
    table.add_row("Valid", str(result.valid))
    table.add_row("Parent institutions", str(result.coverage.total_parent_institutions))
    table.add_row("Units", str(result.coverage.total_units))
    table.add_row("Errors", str(len(result.errors)))
    table.add_row(
        "Warnings",
        str(len(result.warnings) + len(result.relationship_warnings)),
    )
    table.add_row("Outputs", "\n".join(str(path) for path in output_paths))

    console.print(table)
    if result.errors:
        console.print("[red]Schema validation errors were found.[/red]")
        raise typer.Exit(code=1)


@app.command("score-mock-candidates")
def score_mock_candidates_command(
    input_path: Annotated[
        Path,
        typer.Option("--input", help="Path to mock candidate YAML."),
    ] = Path("examples/mock_candidates.yml"),
    output_dir: Annotated[
        Path,
        typer.Option(help="Directory where candidate score reports will be written."),
    ] = Path("outputs"),
) -> None:
    """Score mock candidates and write auditable ranking reports."""
    ranked, output_paths = score_candidates_from_file(input_path=input_path, output_dir=output_dir)

    table = Table(title="Mock Candidate Scores")
    table.add_column("Rank", justify="right")
    table.add_column("Candidate")
    table.add_column("Score", justify="right")
    table.add_column("Priority")
    table.add_column("Method Penalty")

    for report in ranked.candidates:
        breakdown = report.score_breakdown
        table.add_row(
            str(report.rank),
            report.candidate.name,
            f"{breakdown.overall_score:.3f}",
            breakdown.priority_label,
            "yes" if breakdown.method_heavy_penalty_applied else "no",
        )

    console.print(table)
    console.print("Outputs:")
    for output_path in output_paths:
        console.print(f"- {output_path}")


@app.command("build-queries")
def build_queries_command(
    institution: Annotated[str, typer.Option(help="Institution to build queries for.")],
    mode: Annotated[
        MappingMode,
        typer.Option(help="Query mode for broad or narrow discovery."),
    ] = MappingMode.BROAD,
    country: Annotated[
        str,
        typer.Option(help="Country seed layer to use. Only 'us' is curated for now."),
    ] = "us",
    output_dir: Annotated[
        Path,
        typer.Option(help="Directory where query reports will be written."),
    ] = Path("outputs"),
    limit: Annotated[int, typer.Option(min=0, help="Maximum queries to include.")] = 100,
    output_format: Annotated[
        OutputFormat,
        typer.Option("--format", help="Report format to write."),
    ] = OutputFormat.BOTH,
) -> None:
    """Build auditable supervisor-discovery query templates."""
    bundle = build_query_bundle(
        institution=institution,
        mode=mode,
        country=country,
        limit=limit,
    )
    output_paths = write_query_bundle_reports(bundle, output_dir, output_format.value)

    table = Table(title="Supervisor Discovery Query Bundle")
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("Institution", bundle.institution)
    table.add_row("Mode", bundle.mode)
    table.add_row("Queries", str(len(bundle.queries)))
    table.add_row("Outputs", "\n".join(str(path) for path in output_paths))
    console.print(table)

    top_queries = [query for query in bundle.queries if query.priority == "high"][:5]
    if top_queries:
        console.print("[bold]Top queries[/bold]")
        for query in top_queries:
            console.print(f"- {query.source} | {query.unit_name}: {query.query_text}")
    else:
        console.print("[yellow]No high-priority queries were generated.[/yellow]")


@app.command("collect-evidence")
def collect_evidence_command(
    query_file: Annotated[
        Path,
        typer.Option(help="Path to a discovery query bundle JSON file."),
    ],
    sources: Annotated[
        str,
        typer.Option(help="Comma-separated evidence sources: openalex,pubmed."),
    ] = "openalex,pubmed",
    limit_per_source: Annotated[
        int,
        typer.Option(min=0, help="Maximum publications to collect from each source."),
    ] = 20,
    year_from: Annotated[
        int | None,
        typer.Option(help="Optional lower publication year bound."),
    ] = 2021,
    year_to: Annotated[
        int | None,
        typer.Option(help="Optional upper publication year bound."),
    ] = None,
    output_dir: Annotated[
        Path,
        typer.Option(help="Directory where evidence collection reports will be written."),
    ] = Path("outputs"),
    output_format: Annotated[
        OutputFormat,
        typer.Option("--format", help="Report format to write."),
    ] = OutputFormat.BOTH,
) -> None:
    """Collect publication evidence from OpenAlex and/or PubMed query templates."""
    try:
        parse_sources(sources)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc

    collection = collect_evidence_from_query_file(
        query_file=query_file,
        sources=sources,
        limit_per_source=limit_per_source,
        year_from=year_from,
        year_to=year_to,
    )
    output_paths = write_evidence_collection_reports(
        collection=collection,
        output_dir=output_dir,
        output_format=output_format.value,
    )

    table = Table(title="Publication Evidence Collection")
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("Institution", collection.institution)
    table.add_row("Sources", ", ".join(collection.sources))
    table.add_row("Queries run", str(collection.total_queries_run))
    table.add_row("Retrieved", str(collection.total_publications_retrieved))
    table.add_row("Deduplicated", str(collection.deduplicated_publications))
    table.add_row("Outputs", "\n".join(str(path) for path in output_paths))
    console.print(table)

    if collection.warnings:
        console.print("[yellow]Warnings[/yellow]")
        for warning in collection.warnings[:5]:
            console.print(f"- {warning}")
    else:
        console.print("[green]No connector warnings were recorded.[/green]")


@app.command("extract-candidates")
def extract_candidates_command(
    evidence_file: Annotated[
        Path,
        typer.Option(help="Path to an evidence collection JSON file."),
    ],
    institution: Annotated[str, typer.Option(help="Institution context for extraction.")],
    mode: Annotated[
        MappingMode,
        typer.Option(help="Extraction mode matching the source query bundle."),
    ] = MappingMode.BROAD,
    output_dir: Annotated[
        Path,
        typer.Option(help="Directory where candidate extraction reports will be written."),
    ] = Path("outputs"),
    min_publications: Annotated[
        int,
        typer.Option(min=1, help="Minimum publications required for a candidate cluster."),
    ] = 1,
    output_format: Annotated[
        CandidateExtractionFormat,
        typer.Option("--format", help="Report format to write."),
    ] = CandidateExtractionFormat.ALL,
) -> None:
    """Extract preliminary author candidate clusters from publication evidence."""
    report = extract_candidates_from_file(
        evidence_file=evidence_file,
        institution=institution,
        mode=mode.value,
        min_publications=min_publications,
    )
    output_paths = write_candidate_extraction_reports(
        report=report,
        output_dir=output_dir,
        output_format=output_format.value,
    )

    table = Table(title="Candidate Extraction")
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("Institution", report.institution)
    table.add_row("Mode", report.mode)
    table.add_row("Publications processed", str(report.total_publications_processed))
    table.add_row("Author mentions", str(report.total_author_mentions))
    table.add_row("Candidate clusters", str(report.total_candidate_clusters))
    table.add_row("Outputs", "\n".join(str(path) for path in output_paths))
    console.print(table)

    if report.candidate_clusters:
        console.print("[bold]Top candidate clusters[/bold]")
        for cluster in report.candidate_clusters[:5]:
            console.print(
                f"- {cluster.display_name} ({cluster.candidate_id}, "
                f"confidence={cluster.candidate_confidence:.2f})"
            )
    else:
        console.print("[yellow]No candidate clusters met the extraction threshold.[/yellow]")


@app.command("rank-candidates")
def rank_candidates_command(
    candidate_file: Annotated[
        Path,
        typer.Option(help="Path to a candidate extraction JSON file."),
    ],
    institution: Annotated[str, typer.Option(help="Institution context for ranking.")],
    mode: Annotated[
        MappingMode,
        typer.Option(help="Ranking mode matching the source extraction report."),
    ] = MappingMode.BROAD,
    evidence_file: Annotated[
        Path | None,
        typer.Option(help="Optional path to the original evidence collection JSON file."),
    ] = None,
    output_dir: Annotated[
        Path,
        typer.Option(help="Directory where ranked supervisor reports will be written."),
    ] = Path("outputs"),
    min_score: Annotated[
        float | None,
        typer.Option(help="Optional minimum overall score to include."),
    ] = None,
    top_n: Annotated[
        int | None,
        typer.Option(help="Optional maximum number of ranked candidates to include."),
    ] = None,
    output_format: Annotated[
        CandidateRankingFormat,
        typer.Option("--format", help="Report format to write."),
    ] = CandidateRankingFormat.ALL,
) -> None:
    """Rank extracted candidate clusters with the deterministic scoring framework."""
    report = rank_candidates_from_files(
        candidate_file=candidate_file,
        evidence_file=evidence_file,
        institution=institution,
        mode=mode.value,
        min_score=min_score,
        top_n=top_n,
    )
    output_paths = write_candidate_ranking_reports(
        report=report,
        output_dir=output_dir,
        output_format=output_format.value,
    )

    table = Table(title="Ranked Supervisor Candidates")
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("Institution", report.institution)
    table.add_row("Mode", report.mode)
    table.add_row("Clusters processed", str(report.clusters_processed))
    table.add_row("Ranked candidates", str(report.ranked_candidate_count))
    table.add_row("Outputs", "\n".join(str(path) for path in output_paths))
    console.print(table)

    if report.ranked_candidates:
        console.print("[bold]Top ranked candidates[/bold]")
        for candidate in report.ranked_candidates[:5]:
            console.print(
                f"- {candidate.rank}. {candidate.display_name} "
                f"({candidate.priority_label}, score={candidate.overall_score:.3f})"
            )
    else:
        console.print("[yellow]No candidates met the ranking threshold.[/yellow]")


@app.command("calibrate-publications")
def calibrate_publications_command(
    ranked_file: Annotated[
        Path,
        typer.Option(help="Path to ranked_supervisors.json."),
    ],
    output_dir: Annotated[
        Path,
        typer.Option(help="Directory where publication calibration reports will be written."),
    ] = Path("outputs"),
    output_format: Annotated[
        PublicationCalibrationFormat,
        typer.Option("--format", help="Report format to write."),
    ] = PublicationCalibrationFormat.ALL,
) -> None:
    """Calibrate publication impact using journals, authorship, recency, and relevance."""
    report, output_paths = calibrate_publications_from_ranked_file(
        ranked_file=ranked_file,
        output_dir=output_dir,
        output_format=output_format.value,
    )

    table = Table(title="Publication Calibration")
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("Ranked file", str(ranked_file))
    table.add_row("Candidate file", report.candidate_file or "None")
    table.add_row("Candidates calibrated", str(report.candidate_count))
    table.add_row("Outputs", "\n".join(str(path) for path in output_paths))
    console.print(table)

    if report.candidates:
        console.print("[bold]Top calibrated profiles[/bold]")
        for candidate in report.candidates[:5]:
            console.print(
                f"- {candidate.display_name}: mean={candidate.mean_calibrated_score:.3f}, "
                f"max={candidate.max_calibrated_score:.3f}, warnings={len(candidate.warnings)}"
            )


@app.command("enrich-candidates")
def enrich_candidates_command(
    ranked_file: Annotated[
        Path,
        typer.Option(help="Path to a ranked supervisors JSON file."),
    ],
    sources: Annotated[
        str,
        typer.Option(
            help="Comma-separated enrichment sources: nih_reporter,semantic_scholar,manual."
        ),
    ] = "nih_reporter,semantic_scholar,manual",
    year_from: Annotated[
        int | None,
        typer.Option(help="Optional lower fiscal year bound for funding searches."),
    ] = datetime.now(UTC).year - 5,
    year_to: Annotated[
        int | None,
        typer.Option(help="Optional upper fiscal year bound for funding searches."),
    ] = None,
    output_dir: Annotated[
        Path,
        typer.Option(help="Directory where enriched supervisor reports will be written."),
    ] = Path("outputs"),
    top_n: Annotated[
        int | None,
        typer.Option(help="Optional maximum number of ranked candidates to enrich."),
    ] = None,
    output_format: Annotated[
        EnrichmentFormat,
        typer.Option("--format", help="Report format to write."),
    ] = EnrichmentFormat.ALL,
) -> None:
    """Enrich ranked candidates with preliminary profile, funding, and opening evidence."""
    try:
        parse_enrichment_sources(sources)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc

    report = enrich_candidates_from_file(
        ranked_file=ranked_file,
        sources=sources,
        year_from=year_from,
        year_to=year_to,
        top_n=top_n,
    )
    output_paths = write_enriched_candidate_reports(
        report=report,
        output_dir=output_dir,
        output_format=output_format.value,
    )

    table = Table(title="Enriched Supervisor Candidates")
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("Sources", ", ".join(report.run_summary.sources))
    table.add_row("Candidates processed", str(report.run_summary.candidates_processed))
    table.add_row(
        "With funding",
        str(report.run_summary.candidates_with_funding_evidence),
    )
    table.add_row(
        "With profiles",
        str(report.run_summary.candidates_with_author_profile_evidence),
    )
    table.add_row("Outputs", "\n".join(str(path) for path in output_paths))
    console.print(table)

    if report.candidates:
        console.print("[bold]Top enriched candidates[/bold]")
        for candidate in report.candidates[:5]:
            ranked = candidate.ranked_candidate
            adjusted = candidate.enrichment_adjusted_score or ranked.overall_score
            console.print(
                f"- {ranked.rank}. {ranked.display_name} "
                f"(original={ranked.overall_score:.3f}, adjusted={adjusted:.3f})"
            )
    else:
        console.print("[yellow]No ranked candidates were enriched.[/yellow]")


@app.command("detect-openings")
def detect_openings_command(
    ranked_file: Annotated[
        Path,
        typer.Option(help="Path to ranked_supervisors.json or enriched_supervisors.json."),
    ],
    manual_signals: Annotated[
        Path | None,
        typer.Option(help="Optional YAML/CSV with manual snippets or URLs."),
    ] = None,
    output_dir: Annotated[
        Path,
        typer.Option(help="Directory where opening-signal reports will be written."),
    ] = Path("outputs"),
    top_n: Annotated[
        int | None,
        typer.Option(help="Optional maximum number of ranked candidates to assess."),
    ] = None,
    output_format: Annotated[
        OpeningSignalFormat,
        typer.Option("--format", help="Report format to write."),
    ] = OpeningSignalFormat.ALL,
) -> None:
    """Detect deterministic lab/profile/opening signals from manual evidence."""
    report, output_paths = detect_openings_from_file(
        ranked_file=ranked_file,
        manual_signals=manual_signals,
        output_dir=output_dir,
        top_n=top_n,
        output_format=output_format.value,
    )

    table = Table(title="Opening Signal Discovery")
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("Ranked file", str(ranked_file))
    table.add_row("Manual signals", str(manual_signals) if manual_signals else "None")
    table.add_row("Candidates assessed", str(report.candidate_count))
    table.add_row("Outputs", "\n".join(str(path) for path in output_paths))
    console.print(table)

    if report.candidates:
        console.print("[bold]Top opening assessments[/bold]")
        for candidate in report.candidates[:5]:
            console.print(
                f"- {candidate.display_name}: {candidate.opening_signal_type} "
                f"({candidate.opening_signal_strength}, confidence={candidate.confidence:.2f})"
            )
    console.print(
        "[yellow]Opening signals are preliminary and require manual verification before "
        "outreach.[/yellow]"
    )


@app.command("init-review-tracker")
def init_review_tracker_command(
    ranked_file: Annotated[
        Path,
        typer.Option(help="Path to ranked_supervisors.json or enriched_supervisors.json."),
    ],
    output: Annotated[
        Path,
        typer.Option(help="CSV tracker path to create."),
    ] = Path("outputs/review_tracker.csv"),
    opening_signals_file: Annotated[
        Path | None,
        typer.Option(help="Optional opening_signals.json to merge into tracker rows."),
    ] = None,
) -> None:
    """Initialize a manual candidate review tracker CSV."""
    reviews = init_review_tracker(
        ranked_file=ranked_file,
        output=output,
        opening_signals_file=opening_signals_file,
    )
    table = Table(title="Review Tracker Initialized")
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("Candidates", str(len(reviews)))
    table.add_row("Output", str(output))
    console.print(table)


@app.command("review-candidate")
def review_candidate_command(
    tracker: Annotated[
        Path,
        typer.Option(help="Path to review_tracker.csv."),
    ],
    candidate_id: Annotated[str, typer.Option(help="Candidate ID to update.")],
    review_status: Annotated[
        ReviewStatusOption | None,
        typer.Option(help="Manual review status."),
    ] = None,
    outreach_status: Annotated[
        OutreachStatusOption | None,
        typer.Option(help="Outreach tracking status."),
    ] = None,
    note: Annotated[
        str | None,
        typer.Option(help="Manual review note to append."),
    ] = None,
    next_action: Annotated[
        str | None,
        typer.Option(help="Optional next manual action."),
    ] = None,
) -> None:
    """Update one candidate row in the manual review tracker."""
    review = update_candidate_review(
        tracker=tracker,
        candidate_id=candidate_id,
        review_status=review_status.value if review_status else None,
        outreach_status=outreach_status.value if outreach_status else None,
        note=note,
        next_action=next_action,
    )
    table = Table(title="Candidate Review Updated")
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("Candidate", review.display_name)
    table.add_row("Review status", review.review_status)
    table.add_row("Outreach status", review.outreach_status)
    table.add_row("Notes", review.user_notes or "None")
    console.print(table)


@app.command("export-shortlist")
def export_shortlist_command(
    tracker: Annotated[
        Path,
        typer.Option(help="Path to review_tracker.csv."),
    ],
    status: Annotated[
        ReviewStatusOption | None,
        typer.Option(help="Review status to export."),
    ] = ReviewStatusOption.INTERESTED,
    output: Annotated[
        Path,
        typer.Option(help="CSV path for shortlist export."),
    ] = Path("outputs/shortlist.csv"),
) -> None:
    """Export a manual-review shortlist CSV."""
    report = export_shortlist(
        tracker=tracker,
        output=output,
        status=status.value if status else None,
    )
    table = Table(title="Shortlist Exported")
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("Status filter", report.status_filter or "all")
    table.add_row("Candidates", str(report.candidate_count))
    table.add_row("Output", str(output))
    console.print(table)


@app.command("run-pipeline")
def run_pipeline_command(
    institution: Annotated[str, typer.Option(help="Institution to scout end to end.")],
    mode: Annotated[
        MappingMode,
        typer.Option(help="Pipeline mode for broad or narrow discovery."),
    ] = MappingMode.BROAD,
    country: Annotated[
        str,
        typer.Option(help="Country seed layer to use. Only 'us' is curated for now."),
    ] = "us",
    output_dir: Annotated[
        Path,
        typer.Option(help="Base or institution-specific pipeline output directory."),
    ] = Path("outputs"),
    sources: Annotated[
        str,
        typer.Option(help="Comma-separated evidence sources: openalex,pubmed."),
    ] = "openalex,pubmed",
    enrichment_sources: Annotated[
        str,
        typer.Option(help="Comma-separated enrichment sources."),
    ] = "nih_reporter,semantic_scholar,manual",
    limit_queries: Annotated[
        int,
        typer.Option(min=0, help="Maximum discovery queries to generate."),
    ] = 100,
    limit_per_source: Annotated[
        int,
        typer.Option(min=0, help="Maximum evidence records to collect per source."),
    ] = 20,
    top_n: Annotated[
        int | None,
        typer.Option(help="Optional maximum ranked/enriched candidates to keep."),
    ] = None,
    year_from: Annotated[
        int | None,
        typer.Option(help="Optional lower publication/funding year bound."),
    ] = 2021,
    year_to: Annotated[
        int | None,
        typer.Option(help="Optional upper publication/funding year bound."),
    ] = None,
    resume: Annotated[
        bool,
        typer.Option("--resume/--no-resume", help="Reuse existing stage outputs when present."),
    ] = True,
    skip_evidence_collection: Annotated[
        bool,
        typer.Option(help="Skip evidence collection and reuse existing evidence file."),
    ] = False,
    skip_enrichment: Annotated[
        bool,
        typer.Option(help="Skip candidate enrichment."),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option(help="Generate map/query outputs only; do not call external APIs."),
    ] = False,
    output_format: Annotated[
        PipelineFormat,
        typer.Option("--format", help="Pipeline report format to emphasize."),
    ] = PipelineFormat.ALL,
) -> None:
    """Run the deterministic end-to-end postdoc scouting pipeline."""
    config = PipelineConfig(
        institution=institution,
        mode=mode.value,
        country=country,
        output_dir=str(output_dir),
        sources=sources,
        enrichment_sources=enrichment_sources,
        limit_queries=limit_queries,
        limit_per_source=limit_per_source,
        top_n=top_n,
        year_from=year_from,
        year_to=year_to,
        resume=resume,
        skip_evidence_collection=skip_evidence_collection,
        skip_enrichment=skip_enrichment,
        dry_run=dry_run,
        output_format=output_format.value,
    )
    report = run_pipeline(config)

    table = Table(title="Postdoc Scout Pipeline")
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("Institution", report.institution)
    table.add_row("Mode", report.mode)
    table.add_row("Output dir", report.output_dir)
    table.add_row("Dry run", str(report.dry_run))
    table.add_row("Stages", ", ".join(f"{stage.stage}:{stage.status}" for stage in report.stages))
    table.add_row("Pipeline JSON", str(Path(report.output_dir) / "pipeline_run.json"))
    table.add_row("Summary MD", str(Path(report.output_dir) / "pipeline_summary.md"))
    console.print(table)

    if report.warnings:
        console.print("[yellow]Warnings[/yellow]")
        for warning in report.warnings[:8]:
            console.print(f"- {warning}")


if __name__ == "__main__":
    app()
