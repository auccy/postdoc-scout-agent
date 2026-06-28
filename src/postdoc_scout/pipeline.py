"""End-to-end deterministic pipeline orchestration."""

from datetime import UTC, datetime
from pathlib import Path

from postdoc_scout.candidate_enricher import (
    enrich_candidates_from_file,
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
    write_evidence_collection_reports,
)
from postdoc_scout.institution_mapper import (
    MappingMode,
    map_institution_ecosystem,
    slugify_institution_name,
)
from postdoc_scout.models import (
    CandidateExtractionReport,
    CandidateRankingReport,
    EnrichedCandidateReport,
    EvidenceCollection,
    InstitutionEcosystem,
    PipelineConfig,
    PipelineRunReport,
    PipelineStageResult,
    QueryBundle,
)
from postdoc_scout.query_builder import build_query_bundle

PIPELINE_LIMITATIONS = [
    "Pipeline outputs are preliminary and require human review before outreach.",
    "Author identity, affiliation, and lab-opening status are not verified.",
    "External connector results can be incomplete or unavailable.",
    "No arbitrary lab website scraping or LLM summarization is performed.",
]

STAGE_OUTPUTS = {
    "institution_mapping": ["ecosystem.json", "ecosystem.md"],
    "query_building": ["discovery_queries.json", "discovery_queries.md"],
    "evidence_collection": ["evidence_collection.json", "evidence_collection.md"],
    "candidate_extraction": [
        "candidate_extraction.json",
        "candidate_extraction.md",
        "candidate_extraction.csv",
    ],
    "candidate_ranking": [
        "ranked_supervisors.json",
        "ranked_supervisors.md",
        "ranked_supervisors.csv",
    ],
    "candidate_enrichment": [
        "enriched_supervisors.json",
        "enriched_supervisors.md",
        "enriched_supervisors.csv",
    ],
}


def run_pipeline(config: PipelineConfig) -> PipelineRunReport:
    """Run the deterministic end-to-end scouting pipeline."""
    output_dir = _resolve_output_dir(config)
    output_dir.mkdir(parents=True, exist_ok=True)
    stages: list[PipelineStageResult] = []
    warnings: list[str] = []

    ecosystem = _run_institution_mapping(config, output_dir, stages)
    bundle = _run_query_building(config, output_dir, stages)

    if config.dry_run:
        warnings.append("Dry run stopped after query building; no external APIs were called.")
        _add_skipped_stage(
            stages,
            "evidence_collection",
            "Dry run: evidence collection not executed.",
        )
        _add_skipped_stage(
            stages,
            "candidate_extraction",
            "Dry run: candidate extraction not executed.",
        )
        _add_skipped_stage(stages, "candidate_ranking", "Dry run: candidate ranking not executed.")
        _add_skipped_stage(
            stages,
            "candidate_enrichment",
            "Dry run: candidate enrichment not executed.",
        )
    else:
        collection = _run_evidence_collection(config, output_dir, stages)
        extraction = _run_candidate_extraction(config, output_dir, stages, collection)
        ranking = _run_candidate_ranking(config, output_dir, stages, extraction)
        _run_candidate_enrichment(config, output_dir, stages, ranking)

    report = _build_report(
        config=config,
        output_dir=output_dir,
        stages=stages,
        ecosystem=ecosystem,
        bundle=bundle,
        warnings=warnings,
    )
    _write_pipeline_reports(report, output_dir)
    return report


def _run_institution_mapping(
    config: PipelineConfig,
    output_dir: Path,
    stages: list[PipelineStageResult],
) -> InstitutionEcosystem | None:
    json_path = output_dir / "ecosystem.json"
    md_path = output_dir / "ecosystem.md"
    if config.resume and json_path.exists():
        ecosystem = InstitutionEcosystem.model_validate_json(json_path.read_text(encoding="utf-8"))
        stages.append(
            _stage_result(
                "institution_mapping",
                "reused",
                [json_path, md_path],
                reused=True,
                metrics={"ecosystem_units": len(ecosystem.units)},
            )
        )
        return ecosystem
    try:
        ecosystem = map_institution_ecosystem(
            institution=config.institution,
            mode=MappingMode(config.mode),
            country=config.country,
        )
        json_path.write_text(ecosystem.model_dump_json(indent=2), encoding="utf-8")
        _write_ecosystem_markdown(ecosystem, md_path)
        stages.append(
            _stage_result(
                "institution_mapping",
                "completed",
                [json_path, md_path],
                metrics={"ecosystem_units": len(ecosystem.units)},
            )
        )
        return ecosystem
    except Exception as exc:
        stages.append(_failed_stage("institution_mapping", exc))
        return None


def _run_query_building(
    config: PipelineConfig,
    output_dir: Path,
    stages: list[PipelineStageResult],
) -> QueryBundle | None:
    json_path = output_dir / "discovery_queries.json"
    md_path = output_dir / "discovery_queries.md"
    if config.resume and json_path.exists():
        bundle = QueryBundle.model_validate_json(json_path.read_text(encoding="utf-8"))
        stages.append(
            _stage_result(
                "query_building",
                "reused",
                [json_path, md_path],
                reused=True,
                metrics={"discovery_queries": len(bundle.queries)},
            )
        )
        return bundle
    try:
        bundle = build_query_bundle(
            institution=config.institution,
            mode=MappingMode(config.mode),
            country=config.country,
            limit=config.limit_queries,
        )
        json_path.write_text(bundle.model_dump_json(indent=2), encoding="utf-8")
        _write_query_markdown(bundle, md_path)
        stages.append(
            _stage_result(
                "query_building",
                "completed",
                [json_path, md_path],
                metrics={"discovery_queries": len(bundle.queries)},
            )
        )
        return bundle
    except Exception as exc:
        stages.append(_failed_stage("query_building", exc))
        return None


def _run_evidence_collection(
    config: PipelineConfig,
    output_dir: Path,
    stages: list[PipelineStageResult],
) -> EvidenceCollection | None:
    query_file = output_dir / "discovery_queries.json"
    json_path = output_dir / "evidence_collection.json"
    if config.resume and json_path.exists():
        collection = EvidenceCollection.model_validate_json(json_path.read_text(encoding="utf-8"))
        stages.append(
            _stage_result(
                "evidence_collection",
                "reused",
                _existing_outputs(output_dir, "evidence_collection"),
                reused=True,
                metrics={"publications_retrieved": collection.deduplicated_publications},
            )
        )
        return collection
    if config.skip_evidence_collection:
        if json_path.exists():
            collection = EvidenceCollection.model_validate_json(
                json_path.read_text(encoding="utf-8")
            )
            stages.append(
                _stage_result(
                    "evidence_collection",
                    "reused",
                    _existing_outputs(output_dir, "evidence_collection"),
                    reused=True,
                    warnings=["Evidence collection skipped; existing evidence file reused."],
                    metrics={"publications_retrieved": collection.deduplicated_publications},
                )
            )
            return collection
        stages.append(
            _stage_result(
                "evidence_collection",
                "failed",
                [],
                errors=[
                    "Evidence collection was skipped but evidence_collection.json was not found."
                ],
            )
        )
        return None
    if not query_file.exists():
        stages.append(
            _stage_result(
                "evidence_collection",
                "failed",
                [],
                errors=["discovery_queries.json is required before evidence collection."],
            )
        )
        return None
    try:
        collection = collect_evidence_from_query_file(
            query_file=query_file,
            sources=config.sources,
            limit_per_source=config.limit_per_source,
            year_from=config.year_from,
            year_to=config.year_to,
        )
        output_paths = write_evidence_collection_reports(collection, output_dir, "both")
        stages.append(
            _stage_result(
                "evidence_collection",
                "completed",
                output_paths,
                warnings=collection.warnings,
                metrics={"publications_retrieved": collection.deduplicated_publications},
            )
        )
        return collection
    except Exception as exc:
        stages.append(_failed_stage("evidence_collection", exc))
        return None


def _run_candidate_extraction(
    config: PipelineConfig,
    output_dir: Path,
    stages: list[PipelineStageResult],
    collection: EvidenceCollection | None,
) -> CandidateExtractionReport | None:
    json_path = output_dir / "candidate_extraction.json"
    evidence_file = output_dir / "evidence_collection.json"
    if config.resume and json_path.exists():
        report = CandidateExtractionReport.model_validate_json(
            json_path.read_text(encoding="utf-8")
        )
        stages.append(
            _stage_result(
                "candidate_extraction",
                "reused",
                _existing_outputs(output_dir, "candidate_extraction"),
                reused=True,
                metrics={"candidate_clusters": report.total_candidate_clusters},
            )
        )
        return report
    if collection is None or not evidence_file.exists():
        stages.append(
            _stage_result(
                "candidate_extraction",
                "skipped",
                [],
                warnings=[
                    "Candidate extraction skipped because no evidence collection is available."
                ],
            )
        )
        return None
    try:
        report = extract_candidates_from_file(
            evidence_file=evidence_file,
            institution=config.institution,
            mode=config.mode,
        )
        output_paths = write_candidate_extraction_reports(report, output_dir, "all")
        stages.append(
            _stage_result(
                "candidate_extraction",
                "completed",
                output_paths,
                warnings=report.warnings,
                metrics={"candidate_clusters": report.total_candidate_clusters},
            )
        )
        return report
    except Exception as exc:
        stages.append(_failed_stage("candidate_extraction", exc))
        return None


def _run_candidate_ranking(
    config: PipelineConfig,
    output_dir: Path,
    stages: list[PipelineStageResult],
    extraction: CandidateExtractionReport | None,
) -> CandidateRankingReport | None:
    json_path = output_dir / "ranked_supervisors.json"
    candidate_file = output_dir / "candidate_extraction.json"
    evidence_file = output_dir / "evidence_collection.json"
    if config.resume and json_path.exists():
        report = CandidateRankingReport.model_validate_json(json_path.read_text(encoding="utf-8"))
        stages.append(
            _stage_result(
                "candidate_ranking",
                "reused",
                _existing_outputs(output_dir, "candidate_ranking"),
                reused=True,
                metrics={"ranked_candidates": report.ranked_candidate_count},
            )
        )
        return report
    if extraction is None or not candidate_file.exists():
        stages.append(
            _stage_result(
                "candidate_ranking",
                "skipped",
                [],
                warnings=[
                    "Candidate ranking skipped because no candidate extraction is available."
                ],
            )
        )
        return None
    try:
        report = rank_candidates_from_files(
            candidate_file=candidate_file,
            evidence_file=evidence_file if evidence_file.exists() else None,
            institution=config.institution,
            mode=config.mode,
            top_n=config.top_n,
        )
        output_paths = write_candidate_ranking_reports(report, output_dir, "all")
        stages.append(
            _stage_result(
                "candidate_ranking",
                "completed",
                output_paths,
                warnings=report.warnings,
                metrics={"ranked_candidates": report.ranked_candidate_count},
            )
        )
        return report
    except Exception as exc:
        stages.append(_failed_stage("candidate_ranking", exc))
        return None


def _run_candidate_enrichment(
    config: PipelineConfig,
    output_dir: Path,
    stages: list[PipelineStageResult],
    ranking: CandidateRankingReport | None,
) -> EnrichedCandidateReport | None:
    json_path = output_dir / "enriched_supervisors.json"
    ranked_file = output_dir / "ranked_supervisors.json"
    if config.skip_enrichment:
        stages.append(
            _stage_result(
                "candidate_enrichment",
                "skipped",
                [],
                warnings=["Candidate enrichment skipped by configuration."],
            )
        )
        return None
    if config.resume and json_path.exists():
        report = EnrichedCandidateReport.model_validate_json(json_path.read_text(encoding="utf-8"))
        stages.append(
            _stage_result(
                "candidate_enrichment",
                "reused",
                _existing_outputs(output_dir, "candidate_enrichment"),
                reused=True,
                metrics={"enriched_candidates": len(report.candidates)},
            )
        )
        return report
    if ranking is None or not ranked_file.exists():
        stages.append(
            _stage_result(
                "candidate_enrichment",
                "skipped",
                [],
                warnings=["Candidate enrichment skipped because no ranking is available."],
            )
        )
        return None
    try:
        report = enrich_candidates_from_file(
            ranked_file=ranked_file,
            sources=config.enrichment_sources,
            year_from=config.year_from,
            year_to=config.year_to,
            top_n=config.top_n,
        )
        output_paths = write_enriched_candidate_reports(report, output_dir, "all")
        stages.append(
            _stage_result(
                "candidate_enrichment",
                "completed",
                output_paths,
                warnings=report.run_summary.warnings,
                metrics={"enriched_candidates": len(report.candidates)},
            )
        )
        return report
    except Exception as exc:
        stages.append(_failed_stage("candidate_enrichment", exc))
        return None


def _build_report(
    config: PipelineConfig,
    output_dir: Path,
    stages: list[PipelineStageResult],
    ecosystem: InstitutionEcosystem | None,
    bundle: QueryBundle | None,
    warnings: list[str],
) -> PipelineRunReport:
    metrics = {
        "ecosystem_units": len(ecosystem.units) if ecosystem else 0,
        "discovery_queries": len(bundle.queries) if bundle else 0,
        "publications_retrieved": _metric_from_stages(stages, "publications_retrieved"),
        "candidate_clusters": _metric_from_stages(stages, "candidate_clusters"),
        "ranked_candidates": _metric_from_stages(stages, "ranked_candidates"),
        "enriched_candidates": _metric_from_stages(stages, "enriched_candidates"),
    }
    all_warnings = [*warnings]
    for stage in stages:
        all_warnings.extend(stage.warnings)
        all_warnings.extend(stage.errors)
    return PipelineRunReport(
        institution=config.institution,
        mode=config.mode,
        country=config.country,
        output_dir=str(output_dir),
        generated_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
        dry_run=config.dry_run,
        config=config.model_copy(update={"output_dir": str(output_dir)}),
        stages=stages,
        output_files=[
            str(path)
            for stage in stages
            for path in stage.output_files
        ]
        + [
            str(output_dir / "pipeline_run.json"),
            str(output_dir / "pipeline_summary.md"),
        ],
        metrics=metrics,
        warnings=_dedupe(all_warnings),
        limitations=PIPELINE_LIMITATIONS,
    )


def _write_pipeline_reports(report: PipelineRunReport, output_dir: Path) -> None:
    json_path = output_dir / "pipeline_run.json"
    md_path = output_dir / "pipeline_summary.md"
    json_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    md_path.write_text(_pipeline_summary_markdown(report), encoding="utf-8")


def _pipeline_summary_markdown(report: PipelineRunReport) -> str:
    lines = [
        f"# {report.institution} Pipeline Summary",
        "",
        f"- Mode: {report.mode}",
        f"- Country: {report.country}",
        f"- Generated at: {report.generated_at}",
        f"- Dry run: {report.dry_run}",
        "",
        "## Stages",
        "",
        "| Stage | Status | Reused | Outputs | Warnings |",
        "| --- | --- | --- | ---: | ---: |",
    ]
    for stage in report.stages:
        lines.append(
            f"| {stage.stage} | {stage.status} | {stage.reused_existing} | "
            f"{len(stage.output_files)} | {len(stage.warnings) + len(stage.errors)} |"
        )
    lines.extend(
        [
            "",
            "## Metrics",
            "",
            f"- Ecosystem units: {report.metrics.get('ecosystem_units', 0)}",
            f"- Discovery queries: {report.metrics.get('discovery_queries', 0)}",
            f"- Publications retrieved: {report.metrics.get('publications_retrieved', 0)}",
            f"- Candidate clusters: {report.metrics.get('candidate_clusters', 0)}",
            f"- Ranked candidates: {report.metrics.get('ranked_candidates', 0)}",
            f"- Enriched candidates: {report.metrics.get('enriched_candidates', 0)}",
            "",
            "## Output Files",
            "",
        ]
    )
    lines.extend(f"- {path}" for path in report.output_files or ["None"])
    lines.extend(["", "## Top Ranked Candidates", ""])
    ranked_path = Path(report.output_dir) / "ranked_supervisors.json"
    if ranked_path.exists():
        ranking = CandidateRankingReport.model_validate_json(
            ranked_path.read_text(encoding="utf-8")
        )
        lines.extend(
            f"- {candidate.rank}. {candidate.display_name}: "
            f"{candidate.priority_label}, {candidate.overall_score:.3f}"
            for candidate in ranking.ranked_candidates[:10]
        )
    else:
        lines.append("- Not available")
    lines.extend(["", "## Major Warnings", ""])
    lines.extend(f"- {warning}" for warning in report.warnings or ["None"])
    lines.extend(["", "## Recommended Next Manual Checks", ""])
    lines.extend(
        [
            "- Review generated discovery queries before relying on external evidence.",
            "- Verify candidate identity and institutional affiliation manually.",
            "- Check lab and department pages for current opening/contact signals.",
            "- Treat rankings as preliminary evidence triage, not final supervisor suitability.",
            "",
            "## Limitations",
            "",
        ]
    )
    lines.extend(f"- {limitation}" for limitation in report.limitations)
    lines.append("")
    return "\n".join(lines)


def _resolve_output_dir(config: PipelineConfig) -> Path:
    base = Path(config.output_dir)
    if base.name in {"outputs", ""}:
        return base / slugify_institution_name(config.institution)
    return base


def _stage_result(
    stage: str,
    status: str,
    output_files: list[Path],
    reused: bool = False,
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
    metrics: dict[str, int | float | str | bool | None] | None = None,
) -> PipelineStageResult:
    return PipelineStageResult(
        stage=stage,  # type: ignore[arg-type]
        status=status,
        output_files=[str(path) for path in output_files if path.exists()],
        reused_existing=reused,
        warnings=warnings or [],
        errors=errors or [],
        metrics=metrics or {},
    )


def _failed_stage(stage: str, exc: Exception) -> PipelineStageResult:
    return _stage_result(stage, "failed", [], errors=[f"{type(exc).__name__}: {exc}"])


def _add_skipped_stage(
    stages: list[PipelineStageResult],
    stage: str,
    warning: str,
) -> None:
    stages.append(_stage_result(stage, "skipped", [], warnings=[warning]))


def _existing_outputs(output_dir: Path, stage: str) -> list[Path]:
    return [
        output_dir / filename
        for filename in STAGE_OUTPUTS[stage]
        if (output_dir / filename).exists()
    ]


def _metric_from_stages(
    stages: list[PipelineStageResult],
    metric_name: str,
) -> int:
    for stage in stages:
        value = stage.metrics.get(metric_name)
        if isinstance(value, int):
            return value
    return 0


def _write_ecosystem_markdown(ecosystem: InstitutionEcosystem, output_path: Path) -> None:
    lines = [
        f"# {ecosystem.institution.name} Ecosystem Map",
        "",
        f"- Query: {ecosystem.query}",
        f"- Mode: {ecosystem.mode}",
        f"- Units: {len(ecosystem.units)}",
        "",
        "## Units",
        "",
    ]
    lines.extend(
        f"- {unit.name} ({unit.unit_type}; {', '.join(unit.relevance_domains)})"
        for unit in ecosystem.units
    )
    if not ecosystem.units:
        lines.append("- None")
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {limitation}" for limitation in ecosystem.limitations)
    lines.append("")
    output_path.write_text("\n".join(lines), encoding="utf-8")


def _write_query_markdown(bundle: QueryBundle, output_path: Path) -> None:
    lines = [
        f"# {bundle.institution} Discovery Queries",
        "",
        f"- Mode: {bundle.mode}",
        f"- Query count: {len(bundle.queries)}",
        "",
        "## Top Queries",
        "",
    ]
    lines.extend(
        f"- `{query.query_id}` [{query.source}] {query.unit_name}: {query.query_text}"
        for query in bundle.queries[:25]
    )
    if not bundle.queries:
        lines.append("- None")
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {limitation}" for limitation in bundle.limitations)
    lines.append("")
    output_path.write_text("\n".join(lines), encoding="utf-8")


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    deduped = []
    for value in values:
        normalized = value.casefold().strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            deduped.append(value)
    return deduped
