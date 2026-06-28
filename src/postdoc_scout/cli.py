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
from postdoc_scout.scout import ScoutMode, ScoutRequest, run_placeholder_scout

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


if __name__ == "__main__":
    app()
