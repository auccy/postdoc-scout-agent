"""Rank extracted candidate clusters with the deterministic scoring framework."""

import csv
from datetime import UTC, datetime
from pathlib import Path

from postdoc_scout.models import (
    CandidateCluster,
    CandidateExtractionReport,
    CandidatePublicationCalibration,
    CandidateRankingReport,
    EvidenceCollection,
    EvidenceItem,
    Publication,
    RankedSupervisorCandidate,
    ScoreBreakdown,
    SupervisorCandidate,
)
from postdoc_scout.publication_calibration import calibrate_candidate_publication_profile
from postdoc_scout.scoring import (
    assign_priority_label,
    calculate_weighted_score,
    score_candidate,
)

RANKING_LIMITATIONS = [
    "Identity is preliminary and not verified.",
    "Author disambiguation is conservative.",
    "Publication evidence is not a full CV.",
    "Affiliation metadata may be incomplete.",
    "Rankings require human review before outreach.",
]

METHODOLOGY_NOTE = (
    "Candidate clusters are converted into SupervisorCandidate records, scored with the "
    "deterministic candidate scoring framework, and ranked by overall score. Evidence IDs, "
    "publication metadata, inferred domains, and ambiguity warnings are preserved."
)


def load_candidate_extraction_report(candidate_file: Path) -> CandidateExtractionReport:
    """Load candidate extraction JSON."""
    return CandidateExtractionReport.model_validate_json(
        candidate_file.read_text(encoding="utf-8")
    )


def load_evidence_collection(evidence_file: Path | None) -> EvidenceCollection | None:
    """Load optional original evidence collection JSON."""
    if evidence_file is None:
        return None
    return EvidenceCollection.model_validate_json(evidence_file.read_text(encoding="utf-8"))


def rank_candidates_from_files(
    candidate_file: Path,
    evidence_file: Path | None,
    institution: str,
    mode: str,
    min_score: float | None = None,
    top_n: int | None = None,
) -> CandidateRankingReport:
    """Load candidate extraction/evidence files and write a preliminary ranking report."""
    extraction_report = load_candidate_extraction_report(candidate_file)
    evidence_collection = load_evidence_collection(evidence_file)
    return rank_candidate_clusters(
        extraction_report=extraction_report,
        evidence_collection=evidence_collection,
        institution=institution,
        mode=mode,
        candidate_file=candidate_file,
        evidence_file=evidence_file,
        min_score=min_score,
        top_n=top_n,
    )


def rank_candidate_clusters(
    extraction_report: CandidateExtractionReport,
    evidence_collection: EvidenceCollection | None,
    institution: str,
    mode: str,
    candidate_file: Path | str,
    evidence_file: Path | str | None = None,
    min_score: float | None = None,
    top_n: int | None = None,
) -> CandidateRankingReport:
    """Convert candidate clusters to scored, ranked supervisor candidates."""
    evidence_by_id = _evidence_by_id(evidence_collection) if evidence_collection else {}
    ranked_candidates: list[RankedSupervisorCandidate] = []
    warnings = list(extraction_report.warnings)

    for cluster in extraction_report.candidate_clusters:
        supervisor = cluster_to_supervisor_candidate(cluster, evidence_by_id)
        scored = score_candidate(supervisor)
        calibration = calibrate_candidate_publication_profile(
            candidate_id=cluster.candidate_id,
            display_name=cluster.display_name,
            publications=supervisor.publications,
        )
        _apply_publication_calibration(scored.score_breakdown, calibration)
        ranked = _ranked_candidate_from_cluster(
            cluster=cluster,
            score_breakdown=scored.score_breakdown,
            evidence_items=supervisor.evidence_items,
            inferred_domains=supervisor.domains,
        )
        if min_score is not None and ranked.overall_score < min_score:
            continue
        ranked_candidates.append(ranked)

    ranked_candidates.sort(
        key=lambda candidate: (
            -candidate.overall_score,
            candidate.display_name.casefold(),
            candidate.candidate_id,
        )
    )
    if top_n is not None:
        ranked_candidates = ranked_candidates[: max(0, top_n)]
    for index, candidate in enumerate(ranked_candidates, start=1):
        candidate.rank = index

    if any(candidate.warnings for candidate in ranked_candidates):
        warnings.append("Some ranked candidates include ambiguity or scoring warnings.")
    if evidence_collection is None:
        warnings.append("Original evidence collection was not provided; cluster evidence was used.")

    return CandidateRankingReport(
        institution=institution,
        mode=mode,
        candidate_file=str(candidate_file),
        evidence_file=str(evidence_file) if evidence_file else None,
        generated_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
        clusters_processed=len(extraction_report.candidate_clusters),
        ranked_candidate_count=len(ranked_candidates),
        ranked_candidates=ranked_candidates,
        methodology_note=METHODOLOGY_NOTE,
        limitations=RANKING_LIMITATIONS,
        warnings=_dedupe(warnings),
    )


def cluster_to_supervisor_candidate(
    cluster: CandidateCluster,
    evidence_by_id: dict[str, EvidenceItem] | None = None,
) -> SupervisorCandidate:
    """Convert one candidate cluster into a scoreable SupervisorCandidate."""
    evidence_by_id = evidence_by_id or {}
    evidence_items = _cluster_evidence_items(cluster, evidence_by_id)
    publications = [
        _publication_for_candidate(publication, cluster)
        for publication in cluster.publications
    ]
    inferred_domains = infer_domains(cluster, evidence_items)
    warnings = _dedupe(cluster.ambiguity_warnings)
    notes = " ".join(
        [
            cluster.notes,
            " ".join(warnings),
            "Preliminary candidate converted from author-cluster evidence.",
        ]
    ).strip()
    return SupervisorCandidate(
        name=cluster.display_name,
        current_affiliations=cluster.possible_affiliations,
        institution_units=cluster.matched_institution_units,
        departments_or_centers=cluster.matched_institution_units,
        domains=inferred_domains,
        publications=publications,
        evidence_items=evidence_items,
        notes=notes,
    )


def infer_domains(cluster: CandidateCluster, evidence_items: list[EvidenceItem]) -> list[str]:
    """Infer candidate domains from cluster publications, units, and evidence."""
    domains = list(cluster.relevance_domains)
    for publication in cluster.publications:
        domains.extend(publication.relevance_domains)
        text = " ".join(
            [
                publication.title,
                publication.abstract,
                publication.journal,
                " ".join(publication.affiliations),
            ]
        ).casefold()
        domains.extend(_domains_from_text(text))
    for evidence in evidence_items:
        domains.extend(evidence.relevance_domains)
        domains.extend(_domains_from_text(f"{evidence.title} {evidence.note}".casefold()))
    for unit in cluster.matched_institution_units:
        domains.extend(_domains_from_text(unit.casefold()))
    return _dedupe(domains)


def suggested_contact_angle(domains: list[str]) -> str:
    """Generate a deterministic contact angle from inferred domains."""
    domain_set = {domain.casefold() for domain in domains}
    has_adrd = bool(domain_set & {"ad/adrd", "aging", "dementia", "neurodegeneration"})
    has_digital = bool(
        domain_set
        & {"clinical ai", "digital medicine", "ehr/rwd", "real-world data", "biomedical ai"}
    )
    has_oncology = bool(domain_set & {"oncology", "cancer", "trial enrichment"})
    has_ehr = bool(
        domain_set
        & {"ehr/rwd", "real-world data", "clinical ai", "clinical decision support"}
    )
    if has_adrd and has_digital:
        return (
            "Potential angle: emphasize your work on interpretable dementia risk "
            "prediction, longitudinal cognitive progression modeling, and clinical "
            "decision-support tools using AIBL/ADNI/ROSMAP-style cohort data."
        )
    if has_oncology and has_digital:
        return (
            "Potential angle: emphasize transferable experience in risk prediction, "
            "longitudinal modeling, survival analysis, and interpretable clinical AI "
            "for real-world patient stratification."
        )
    if has_ehr:
        return (
            "Potential angle: emphasize your interest in translating interpretable "
            "prediction models into clinically usable digital medicine tools."
        )
    return (
        "Potential angle: emphasize shared translational biomedical AI interests, "
        "auditable evidence generation, and clinically meaningful prediction work."
    )


def write_candidate_ranking_json(report: CandidateRankingReport, output_dir: Path) -> Path:
    """Write ranked supervisor report JSON."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "ranked_supervisors.json"
    output_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return output_path


def write_candidate_ranking_markdown(report: CandidateRankingReport, output_dir: Path) -> Path:
    """Write ranked supervisor report Markdown."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "ranked_supervisors.md"
    lines = [
        f"# {report.institution} Ranked Supervisor Candidates",
        "",
        f"- Mode: {report.mode}",
        f"- Candidate clusters processed: {report.clusters_processed}",
        f"- Ranked candidates: {report.ranked_candidate_count}",
        f"- Candidate file: {report.candidate_file}",
        f"- Evidence file: {report.evidence_file or 'not provided'}",
        "",
        "## Methodology",
        "",
        report.methodology_note,
        "",
        "## Ranked Table",
        "",
        "| Rank | Name | Priority | Score | Affiliations | Units | Domains | "
        "Senior/Corr/First | Warnings |",
        "| ---: | --- | --- | ---: | --- | --- | --- | --- | ---: |",
    ]
    for candidate in report.ranked_candidates:
        lines.append(
            "| "
            f"{candidate.rank} | {candidate.display_name} | {candidate.priority_label} | "
            f"{candidate.overall_score:.3f} | "
            f"{'; '.join(candidate.possible_affiliations) or 'None'} | "
            f"{'; '.join(candidate.matched_institution_units) or 'None'} | "
            f"{'; '.join(candidate.inferred_domains[:8]) or 'None'} | "
            f"{candidate.senior_author_count}/"
            f"{candidate.corresponding_author_count}/"
            f"{candidate.first_author_count} | "
            f"{len(candidate.warnings)} |"
        )
    if not report.ranked_candidates:
        lines.append("|  | None |  |  |  |  |  |  |  |")

    lines.extend(["", "## Candidate Details", ""])
    for candidate in report.ranked_candidates:
        lines.extend(_candidate_detail_lines(candidate))
    lines.extend(["## Warnings", ""])
    lines.extend(f"- {warning}" for warning in report.warnings or ["None"])
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {limitation}" for limitation in report.limitations)
    lines.append("")
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


def write_candidate_ranking_csv(report: CandidateRankingReport, output_dir: Path) -> Path:
    """Write ranked supervisor CSV."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "ranked_supervisors.csv"
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "rank",
                "candidate_id",
                "display_name",
                "possible_affiliations",
                "matched_institution_units",
                "inferred_domains",
                "overall_score",
                "priority_label",
                "digital_medicine_relevance",
                "disease_domain_strategic_fit",
                "data_resource_strength",
                "translational_publication_potential",
                "recent_academic_impact",
                "hiring_accessibility",
                "methodological_alignment",
                "method_heavy_penalty_applied",
                "publication_count",
                "recent_publication_count",
                "senior_author_count",
                "corresponding_author_count",
                "first_author_count",
                "warning_count",
                "suggested_contact_angle",
            ],
        )
        writer.writeheader()
        for candidate in report.ranked_candidates:
            dimensions = _dimension_scores(candidate.score_breakdown)
            writer.writerow(
                {
                    "rank": candidate.rank,
                    "candidate_id": candidate.candidate_id,
                    "display_name": candidate.display_name,
                    "possible_affiliations": "; ".join(candidate.possible_affiliations),
                    "matched_institution_units": "; ".join(candidate.matched_institution_units),
                    "inferred_domains": "; ".join(candidate.inferred_domains),
                    "overall_score": f"{candidate.overall_score:.3f}",
                    "priority_label": candidate.priority_label,
                    "digital_medicine_relevance": dimensions.get(
                        "digital_medicine_relevance", ""
                    ),
                    "disease_domain_strategic_fit": dimensions.get(
                        "disease_domain_strategic_fit", ""
                    ),
                    "data_resource_strength": dimensions.get("data_resource_strength", ""),
                    "translational_publication_potential": dimensions.get(
                        "translational_publication_potential", ""
                    ),
                    "recent_academic_impact": dimensions.get("recent_academic_impact", ""),
                    "hiring_accessibility": dimensions.get("hiring_accessibility", ""),
                    "methodological_alignment": dimensions.get(
                        "methodological_alignment", ""
                    ),
                    "method_heavy_penalty_applied": candidate.method_heavy_penalty_applied,
                    "publication_count": candidate.publication_count,
                    "recent_publication_count": candidate.recent_publication_count,
                    "senior_author_count": candidate.senior_author_count,
                    "corresponding_author_count": candidate.corresponding_author_count,
                    "first_author_count": candidate.first_author_count,
                    "warning_count": len(candidate.warnings),
                    "suggested_contact_angle": candidate.suggested_contact_angle,
                }
            )
    return output_path


def write_candidate_ranking_reports(
    report: CandidateRankingReport,
    output_dir: Path,
    output_format: str,
) -> list[Path]:
    """Write ranked supervisor reports as JSON, Markdown, CSV, or all."""
    if output_format == "json":
        return [write_candidate_ranking_json(report, output_dir)]
    if output_format == "md":
        return [write_candidate_ranking_markdown(report, output_dir)]
    if output_format == "csv":
        return [write_candidate_ranking_csv(report, output_dir)]
    return [
        write_candidate_ranking_json(report, output_dir),
        write_candidate_ranking_markdown(report, output_dir),
        write_candidate_ranking_csv(report, output_dir),
    ]


def _ranked_candidate_from_cluster(
    cluster: CandidateCluster,
    score_breakdown: ScoreBreakdown,
    evidence_items: list[EvidenceItem],
    inferred_domains: list[str],
) -> RankedSupervisorCandidate:
    warnings = _dedupe(
        [
            *cluster.ambiguity_warnings,
            *score_breakdown.warnings,
            *[
                warning
                for dimension in score_breakdown.dimensions
                for warning in dimension.warnings
            ],
        ]
    )
    return RankedSupervisorCandidate(
        candidate_id=cluster.candidate_id,
        display_name=cluster.display_name,
        possible_affiliations=cluster.possible_affiliations,
        matched_institution_units=cluster.matched_institution_units,
        inferred_domains=inferred_domains,
        publication_count=len(cluster.publications),
        recent_publication_count=cluster.recent_publication_count,
        senior_author_count=cluster.senior_author_count,
        corresponding_author_count=cluster.corresponding_author_count,
        first_author_count=cluster.first_author_count,
        evidence_items=evidence_items,
        score_breakdown=score_breakdown,
        overall_score=score_breakdown.overall_score,
        priority_label=score_breakdown.priority_label,
        method_heavy_penalty_applied=score_breakdown.method_heavy_penalty_applied,
        warnings=warnings,
        limitations=RANKING_LIMITATIONS,
        suggested_contact_angle=suggested_contact_angle(inferred_domains),
    )


def _apply_publication_calibration(
    score_breakdown: ScoreBreakdown,
    calibration: CandidatePublicationCalibration,
) -> None:
    """Blend calibrated publication impact into existing publication score dimensions."""
    if not calibration.publication_scores:
        return
    recent_scores = [
        score.calibrated_score
        for score in calibration.publication_scores
        if score.recency_weight >= 0.82
    ]
    publication_score = min(5.0, calibration.mean_calibrated_score + 0.35)
    recent_score = (
        min(5.0, sum(recent_scores) / len(recent_scores) + 0.25)
        if recent_scores
        else max(0.0, calibration.mean_calibrated_score - 0.75)
    )
    for dimension in score_breakdown.dimensions:
        if dimension.name == "translational_publication_potential":
            _update_dimension_from_calibration(
                dimension,
                max(dimension.numeric_score, publication_score),
                "Calibrated with journal tier, author role, domain relevance, and article type.",
            )
        if dimension.name == "recent_academic_impact":
            _update_dimension_from_calibration(
                dimension,
                max(dimension.numeric_score, recent_score),
                "Calibrated with publication recency and impact rather than count alone.",
            )
    score_breakdown.warnings = _dedupe([*score_breakdown.warnings, *calibration.warnings])
    raw_score = calculate_weighted_score(score_breakdown.dimensions)
    score_breakdown.overall_score = round(
        max(0.0, raw_score - score_breakdown.method_heavy_penalty),
        3,
    )
    score_breakdown.priority_label = assign_priority_label(score_breakdown.overall_score)


def _update_dimension_from_calibration(
    dimension,
    numeric_score: float,
    explanation_suffix: str,
) -> None:
    dimension.numeric_score = round(max(0.0, min(5.0, numeric_score)), 3)
    dimension.weighted_contribution = round(dimension.numeric_score * dimension.weight, 3)
    if explanation_suffix not in dimension.explanation:
        dimension.explanation = f"{dimension.explanation} {explanation_suffix}".strip()


def _publication_for_candidate(
    publication: Publication,
    cluster: CandidateCluster,
) -> Publication:
    position = "unknown"
    for mention in cluster.author_mentions:
        if mention.publication_title == publication.title:
            if mention.author_position in {"last", "corresponding"}:
                position = "senior" if mention.author_position == "last" else "corresponding"
                break
            position = mention.author_position
    return publication.model_copy(update={"candidate_author_position": position})


def _cluster_evidence_items(
    cluster: CandidateCluster,
    evidence_by_id: dict[str, EvidenceItem],
) -> list[EvidenceItem]:
    evidence_items = list(cluster.evidence_items)
    for mention in cluster.author_mentions:
        if mention.evidence_id in evidence_by_id:
            evidence_items.append(evidence_by_id[mention.evidence_id])
    for publication in cluster.publications:
        evidence_items.extend(publication.evidence_items)
    return _dedupe_evidence_items(evidence_items)


def _evidence_by_id(collection: EvidenceCollection) -> dict[str, EvidenceItem]:
    evidence: dict[str, EvidenceItem] = {}
    for record in collection.publications:
        for item in record.publication.evidence_items:
            if item.evidence_id:
                evidence[item.evidence_id] = item
    return evidence


def _candidate_detail_lines(candidate: RankedSupervisorCandidate) -> list[str]:
    lines = [
        f"### {candidate.rank}. {candidate.display_name}",
        "",
        f"- Candidate ID: `{candidate.candidate_id}`",
        f"- Overall score: {candidate.overall_score:.3f}",
        f"- Priority label: {candidate.priority_label}",
        f"- Method-heavy penalty applied: {candidate.method_heavy_penalty_applied}",
        f"- Suggested contact angle: {candidate.suggested_contact_angle}",
        "",
        "| Dimension | Score | Weight | Evidence IDs |",
        "| --- | ---: | ---: | --- |",
    ]
    for dimension in candidate.score_breakdown.dimensions:
        lines.append(
            "| "
            f"{dimension.name} | {dimension.numeric_score:.2f} | "
            f"{dimension.weight:.1f} | "
            f"{', '.join(dimension.supporting_evidence_ids) or 'None'} |"
        )
    lines.extend(["", "Representative publications:"])
    publication_titles = _dedupe([item.title for item in candidate.evidence_items if item.title])
    lines.extend(f"- {title}" for title in publication_titles[:5] or ["None"])
    lines.extend(["", "Warnings:"])
    lines.extend(f"- {warning}" for warning in candidate.warnings or ["None"])
    lines.append("")
    return lines


def _dimension_scores(score_breakdown: ScoreBreakdown) -> dict[str, str]:
    return {
        dimension.name: f"{dimension.numeric_score:.3f}"
        for dimension in score_breakdown.dimensions
    }


def _domains_from_text(text: str) -> list[str]:
    mappings = {
        "AD/ADRD": ["ad/adrd", "alzheimer", "dementia"],
        "aging": ["aging", "cognitive progression"],
        "biomedical AI": ["biomedical ai"],
        "clinical AI": ["clinical ai", "machine learning", "prediction model"],
        "clinical decision support": ["clinical decision support", "decision support"],
        "digital medicine": ["digital medicine", "digital health"],
        "disease risk prediction": ["risk prediction", "prediction"],
        "EHR/RWD": ["ehr", "electronic health record", "real-world data", "rwd"],
        "oncology": ["oncology", "cancer"],
        "patient stratification": ["patient stratification", "stratification"],
        "progression modeling": ["progression modeling", "longitudinal"],
        "trial enrichment": ["trial enrichment"],
    }
    return [
        domain
        for domain, markers in mappings.items()
        if any(marker in text for marker in markers)
    ]


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    deduped = []
    for value in values:
        normalized = value.casefold().strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            deduped.append(value)
    return deduped


def _dedupe_evidence_items(items: list[EvidenceItem]) -> list[EvidenceItem]:
    seen = set()
    deduped = []
    for item in items:
        key = item.evidence_id or f"{item.title}:{item.source_name}:{item.year}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped
