"""Utility helpers for the Streamlit dashboard.

The functions in this module are intentionally deterministic and UI-independent so the
dashboard can be tested without importing Streamlit.
"""

from pathlib import Path
from typing import Any

from postdoc_scout.institution_mapper import MappingMode, map_institution_ecosystem
from postdoc_scout.models import (
    InstitutionEcosystem,
    PipelineConfig,
    QueryBundle,
    RankedCandidateList,
)
from postdoc_scout.pipeline import run_pipeline
from postdoc_scout.query_builder import build_query_bundle
from postdoc_scout.scoring import load_candidates_from_yaml, rank_candidates

DASHBOARD_REPORT_FILES = {
    "Ecosystem map": "ecosystem.md",
    "Discovery queries": "discovery_queries.md",
    "Evidence collection": "evidence_collection.md",
    "Candidate extraction": "candidate_extraction.md",
    "Ranked supervisors": "ranked_supervisors.md",
    "Enriched supervisors": "enriched_supervisors.md",
    "Pipeline summary": "pipeline_summary.md",
}

DOWNLOAD_FILENAMES = [
    "ecosystem.json",
    "ecosystem.md",
    "discovery_queries.json",
    "discovery_queries.md",
    "evidence_collection.json",
    "evidence_collection.md",
    "candidate_extraction.json",
    "candidate_extraction.md",
    "candidate_extraction.csv",
    "ranked_supervisors.json",
    "ranked_supervisors.md",
    "ranked_supervisors.csv",
    "enriched_supervisors.json",
    "enriched_supervisors.md",
    "enriched_supervisors.csv",
    "pipeline_run.json",
    "pipeline_summary.md",
]


def resolve_dashboard_output_dir(output_dir: str | Path) -> Path:
    """Resolve a dashboard output directory without requiring it to already exist."""
    return Path(output_dir).expanduser()


def safe_load_markdown(path: str | Path) -> str:
    """Load Markdown if it exists, otherwise return an explanatory placeholder."""
    markdown_path = Path(path)
    if not markdown_path.exists():
        return f"_No report found at `{markdown_path}` yet._"
    return markdown_path.read_text(encoding="utf-8")


def available_downloads(output_dir: str | Path) -> list[Path]:
    """Return existing dashboard output files that are useful for downloads."""
    directory = resolve_dashboard_output_dir(output_dir)
    return [
        directory / filename
        for filename in DOWNLOAD_FILENAMES
        if (directory / filename).exists()
    ]


def report_markdown_options(output_dir: str | Path) -> dict[str, Path]:
    """Return existing Markdown reports keyed by display label."""
    directory = resolve_dashboard_output_dir(output_dir)
    return {
        label: directory / filename
        for label, filename in DASHBOARD_REPORT_FILES.items()
        if (directory / filename).exists()
    }


def map_institution_for_dashboard(
    institution: str,
    mode: str = "broad",
    country: str = "us",
) -> InstitutionEcosystem:
    """Map an institution using the same deterministic mapper as the CLI."""
    return map_institution_ecosystem(
        institution=institution,
        mode=MappingMode(mode),
        country=country,
    )


def build_queries_for_dashboard(
    institution: str,
    mode: str = "broad",
    country: str = "us",
    limit: int = 100,
) -> QueryBundle:
    """Build deterministic discovery queries without calling external APIs."""
    return build_query_bundle(
        institution=institution,
        mode=MappingMode(mode),
        country=country,
        limit=limit,
    )


def run_dashboard_pipeline(
    institution: str,
    mode: str,
    country: str,
    output_dir: str | Path,
    dry_run: bool = True,
    resume: bool = True,
    limit_queries: int = 100,
    limit_per_source: int = 20,
) -> Any:
    """Run the pipeline from dashboard controls.

    Dry run should remain the default. Full runs can call external publication/profile APIs.
    """
    config = PipelineConfig(
        institution=institution,
        mode=mode,
        country=country,
        output_dir=str(resolve_dashboard_output_dir(output_dir)),
        dry_run=dry_run,
        resume=resume,
        limit_queries=limit_queries,
        limit_per_source=limit_per_source,
    )
    return run_pipeline(config)


def ecosystem_unit_rows(ecosystem: InstitutionEcosystem) -> list[dict[str, Any]]:
    """Convert ecosystem units into table-ready dictionaries."""
    return [
        {
            "unit name": unit.name,
            "unit type": unit.unit_type,
            "relationship to parent": unit.relationship_to_parent,
            "relevance domains": ", ".join(unit.relevance_domains),
            "confidence": unit.confidence,
            "priority": unit.priority,
            "verification status": unit.verification_status,
        }
        for unit in ecosystem.units
    ]


def query_rows(bundle: QueryBundle) -> list[dict[str, Any]]:
    """Convert discovery queries into table-ready dictionaries."""
    return [
        {
            "query id": query.query_id,
            "source": query.source,
            "unit": query.unit_name,
            "priority": query.priority,
            "query": query.query_text,
            "rationale": query.rationale,
        }
        for query in bundle.queries
    ]


def queries_by_source(bundle: QueryBundle) -> dict[str, list[dict[str, Any]]]:
    """Group query rows by source for tabbed dashboard display."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in query_rows(bundle):
        grouped.setdefault(str(row["source"]), []).append(row)
    return grouped


def score_mock_candidates_for_dashboard(
    input_path: str | Path = "examples/mock_candidates.yml",
) -> RankedCandidateList:
    """Load and score deterministic mock candidates without external APIs."""
    return rank_candidates(load_candidates_from_yaml(Path(input_path)))


def candidate_score_rows(ranked: RankedCandidateList) -> list[dict[str, Any]]:
    """Convert mock candidate scores into a dashboard table."""
    return [
        {
            "rank": report.rank,
            "candidate name": report.candidate.name,
            "overall score": report.score_breakdown.overall_score,
            "priority label": report.score_breakdown.priority_label,
            "method-heavy penalty": report.score_breakdown.method_heavy_penalty_applied,
            "domains": ", ".join(report.candidate.domains),
        }
        for report in ranked.candidates
    ]


def score_breakdown_rows(ranked: RankedCandidateList, candidate_name: str) -> list[dict[str, Any]]:
    """Return score-dimension rows for one selected mock candidate."""
    for report in ranked.candidates:
        if report.candidate.name == candidate_name:
            return [
                {
                    "dimension": dimension.name,
                    "score": dimension.numeric_score,
                    "weight": dimension.weight,
                    "weighted contribution": dimension.weighted_contribution,
                    "evidence IDs": ", ".join(dimension.supporting_evidence_ids),
                    "warnings": "; ".join(dimension.warnings),
                }
                for dimension in report.score_breakdown.dimensions
            ]
    return []
