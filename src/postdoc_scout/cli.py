"""Command-line interface for postdoc-scout-agent."""

from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

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


if __name__ == "__main__":
    app()
