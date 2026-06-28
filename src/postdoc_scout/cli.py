"""Command-line interface for postdoc-scout-agent."""

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from postdoc_scout.institution_mapper import (
    InstitutionTier,
    MappingMode,
    OutputFormat,
    list_parent_institutions,
    map_institution_ecosystem,
    write_ecosystem_reports,
)
from postdoc_scout.query_builder import build_query_bundle, write_query_bundle_reports
from postdoc_scout.scoring import score_candidates_from_file
from postdoc_scout.scout import ScoutMode, ScoutRequest, run_placeholder_scout
from postdoc_scout.seed_map_validation import validate_seed_map, write_validation_reports

app = typer.Typer(
    name="postdoc-scout",
    help="Scout potential postdoc supervisors in translational digital medicine and clinical AI.",
    no_args_is_help=True,
)
console = Console()


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


if __name__ == "__main__":
    app()
