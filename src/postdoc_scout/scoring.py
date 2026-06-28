"""Deterministic candidate scoring for postdoctoral supervisor scouting."""

from collections import Counter
from pathlib import Path

import yaml

from postdoc_scout.models import (
    CandidateReport,
    EvidenceItem,
    RankedCandidateList,
    ScoreBreakdown,
    ScoreDimension,
    SupervisorCandidate,
)

SCORING_VERSION = "candidate_scoring_v1"

DEFAULT_SCORE_WEIGHTS = {
    "digital_medicine_relevance": 25.0,
    "disease_domain_strategic_fit": 20.0,
    "data_resource_strength": 20.0,
    "translational_publication_potential": 15.0,
    "recent_academic_impact": 10.0,
    "hiring_accessibility": 7.0,
    "methodological_alignment": 3.0,
}

CLINICAL_TRANSLATION_DOMAINS = {
    "AD/ADRD",
    "aging",
    "biomedical informatics",
    "clinical AI",
    "clinical decision support",
    "digital medicine",
    "disease progression",
    "disease risk prediction",
    "EHR/RWD",
    "oncology",
    "patient stratification",
    "progression modeling",
    "public health",
    "real-world data",
    "trial enrichment",
    "translational medicine",
}

DIGITAL_MEDICINE_DOMAINS = {
    "clinical AI",
    "clinical decision support",
    "digital medicine",
    "EHR/RWD",
    "real-world data",
    "remote monitoring",
    "wearables",
}

DISEASE_STRATEGIC_DOMAINS = {
    "AD/ADRD",
    "aging",
    "cancer",
    "dementia",
    "disease progression",
    "neurodegeneration",
    "neurology",
    "oncology",
    "patient stratification",
    "progression modeling",
    "trial enrichment",
}

DATA_RESOURCE_DOMAINS = {
    "cohort data",
    "clinical registry",
    "EHR/RWD",
    "real-world data",
    "registry",
    "trial enrichment",
}

METHOD_HEAVY_KEYWORDS = {
    "algorithm design",
    "benchmark-only",
    "foundation model architecture",
    "ml architecture",
    "optimization theory",
    "pure methodology",
    "simulation-only",
    "statistical theory",
}


def calculate_weighted_score(dimensions: list[ScoreDimension]) -> float:
    """Calculate the 0-5 weighted score from dimensions."""
    total_weight = sum(dimension.weight for dimension in dimensions)
    if total_weight <= 0:
        return 0.0
    return round(sum(dimension.weighted_contribution for dimension in dimensions) / total_weight, 3)


def numeric_score_to_stars(score: float) -> str:
    """Convert a 0-5 numeric score into a compact star string."""
    rounded = max(0, min(5, round(score)))
    return "★" * rounded + "☆" * (5 - rounded)


def assign_priority_label(score: float) -> str:
    """Assign a priority label from a 0-5 score."""
    if score >= 4.6:
        return "A+"
    if score >= 4.2:
        return "A"
    if score >= 3.8:
        return "A-"
    if score >= 3.2:
        return "B"
    if score >= 2.5:
        return "C"
    return "D"


def _collect_candidate_domains(candidate: SupervisorCandidate) -> Counter[str]:
    domains: Counter[str] = Counter(candidate.domains)
    for publication in candidate.publications:
        domains.update(publication.relevance_domains)
        for evidence in publication.evidence_items:
            domains.update(evidence.relevance_domains)
    for grant in candidate.grants:
        domains.update(grant.relevance_domains)
        for evidence in grant.evidence_items:
            domains.update(evidence.relevance_domains)
    for evidence in candidate.evidence_items:
        domains.update(evidence.relevance_domains)
    return domains


def _collect_evidence(candidate: SupervisorCandidate) -> list[EvidenceItem]:
    evidence_items = list(candidate.evidence_items)
    for publication in candidate.publications:
        evidence_items.extend(publication.evidence_items)
    for grant in candidate.grants:
        evidence_items.extend(grant.evidence_items)
    return evidence_items


def _candidate_text(candidate: SupervisorCandidate) -> str:
    parts = [
        candidate.name,
        candidate.notes,
        " ".join(candidate.domains),
        " ".join(candidate.departments_or_centers),
        " ".join(candidate.institution_units),
    ]
    parts.extend(publication.title for publication in candidate.publications)
    parts.extend(publication.abstract for publication in candidate.publications)
    parts.extend(grant.title for grant in candidate.grants)
    parts.extend(
        evidence.quoted_or_paraphrased_evidence for evidence in _collect_evidence(candidate)
    )
    parts.extend(evidence.note for evidence in _collect_evidence(candidate))
    parts.extend(evidence.notes for evidence in _collect_evidence(candidate))
    return " ".join(part for part in parts if part).casefold()


def _supporting_evidence_ids(
    evidence_items: list[EvidenceItem],
    target_domains: set[str],
    limit: int = 6,
) -> list[str]:
    ids: list[str] = []
    for evidence in evidence_items:
        if not evidence.evidence_id:
            continue
        if target_domains & set(evidence.relevance_domains):
            ids.append(evidence.evidence_id)
    return ids[:limit]


def _score_from_matches(match_count: int, max_full_score_count: int) -> float:
    if match_count <= 0:
        return 0.5
    scaled_score = 1.0 + 4.0 * min(match_count, max_full_score_count) / max_full_score_count
    return round(min(5.0, scaled_score), 2)


def explain_score_dimension(
    name: str,
    score: float,
    domains: list[str],
    evidence_count: int,
) -> str:
    """Create a concise explanation for a score dimension."""
    matched_domains = ", ".join(domains) if domains else "no strong domain matches"
    return (
        f"{name} scored {score:.2f}/5 based on {matched_domains} "
        f"and {evidence_count} supporting evidence item(s)."
    )


def _make_dimension(
    name: str,
    score: float,
    weight: float,
    matched_domains: list[str],
    supporting_evidence_ids: list[str],
    warnings: list[str] | None = None,
) -> ScoreDimension:
    return ScoreDimension(
        name=name,
        numeric_score=score,
        stars=numeric_score_to_stars(score),
        weight=weight,
        weighted_contribution=round(score * weight, 3),
        explanation=explain_score_dimension(
            name,
            score,
            matched_domains,
            len(supporting_evidence_ids),
        ),
        supporting_evidence_ids=supporting_evidence_ids,
        warnings=warnings or [],
    )


def detect_method_heavy_profile(candidate: SupervisorCandidate) -> tuple[bool, float, list[str]]:
    """Detect method-heavy candidates and return a modest penalty."""
    text = _candidate_text(candidate)
    method_hits = sorted(keyword for keyword in METHOD_HEAVY_KEYWORDS if keyword in text)
    domain_counts = _collect_candidate_domains(candidate)
    clinical_hits = sorted(set(domain_counts) & CLINICAL_TRANSLATION_DOMAINS)

    if not method_hits:
        return False, 0.0, []
    if clinical_hits:
        warning = (
            "Method-heavy signals detected, but clinical/translational evidence is present: "
            f"{', '.join(method_hits)}."
        )
        return True, 0.2, [warning]

    warning = (
        "Method-heavy profile with limited clinical translation evidence: "
        f"{', '.join(method_hits)}."
    )
    return True, 0.55, [warning]


def _score_digital_medicine(
    candidate: SupervisorCandidate,
    domain_counts: Counter[str],
    evidence_items: list[EvidenceItem],
) -> ScoreDimension:
    matched = sorted(set(domain_counts) & DIGITAL_MEDICINE_DOMAINS)
    score = _score_from_matches(sum(domain_counts[domain] for domain in matched), 5)
    return _make_dimension(
        "digital_medicine_relevance",
        score,
        DEFAULT_SCORE_WEIGHTS["digital_medicine_relevance"],
        matched,
        _supporting_evidence_ids(evidence_items, DIGITAL_MEDICINE_DOMAINS),
    )


def _score_disease_fit(
    candidate: SupervisorCandidate,
    domain_counts: Counter[str],
    evidence_items: list[EvidenceItem],
) -> ScoreDimension:
    matched = sorted(set(domain_counts) & DISEASE_STRATEGIC_DOMAINS)
    score = _score_from_matches(sum(domain_counts[domain] for domain in matched), 5)
    return _make_dimension(
        "disease_domain_strategic_fit",
        score,
        DEFAULT_SCORE_WEIGHTS["disease_domain_strategic_fit"],
        matched,
        _supporting_evidence_ids(evidence_items, DISEASE_STRATEGIC_DOMAINS),
    )


def _score_data_strength(
    candidate: SupervisorCandidate,
    domain_counts: Counter[str],
    evidence_items: list[EvidenceItem],
) -> ScoreDimension:
    matched = sorted(set(domain_counts) & DATA_RESOURCE_DOMAINS)
    score = _score_from_matches(sum(domain_counts[domain] for domain in matched), 4)
    return _make_dimension(
        "data_resource_strength",
        score,
        DEFAULT_SCORE_WEIGHTS["data_resource_strength"],
        matched,
        _supporting_evidence_ids(evidence_items, DATA_RESOURCE_DOMAINS),
    )


def _score_publication_potential(
    candidate: SupervisorCandidate,
    evidence_items: list[EvidenceItem],
) -> ScoreDimension:
    impact_count = sum(
        publication.is_high_impact_journal or publication.is_field_leading_journal
        for publication in candidate.publications
    )
    senior_count = sum(
        publication.candidate_author_position in {"senior", "corresponding"}
        for publication in candidate.publications
    )
    translational_pub_count = sum(
        bool(set(publication.relevance_domains) & CLINICAL_TRANSLATION_DOMAINS)
        for publication in candidate.publications
    )
    score = _score_from_matches(impact_count + senior_count + translational_pub_count, 7)
    return _make_dimension(
        "translational_publication_potential",
        score,
        DEFAULT_SCORE_WEIGHTS["translational_publication_potential"],
        ["publication impact", "translation"] if score >= 2 else [],
        _supporting_evidence_ids(evidence_items, CLINICAL_TRANSLATION_DOMAINS),
    )


def _score_recent_impact(
    candidate: SupervisorCandidate,
    evidence_items: list[EvidenceItem],
) -> ScoreDimension:
    recent_publications = sum(
        publication.year is not None and publication.year >= 2021
        for publication in candidate.publications
    )
    active_or_recent_grants = sum(
        grant.end_year is not None and grant.end_year >= 2026 for grant in candidate.grants
    )
    score = _score_from_matches(recent_publications + active_or_recent_grants, 6)
    return _make_dimension(
        "recent_academic_impact",
        score,
        DEFAULT_SCORE_WEIGHTS["recent_academic_impact"],
        ["recent publications", "active grants"] if score >= 2 else [],
        [item.evidence_id for item in evidence_items if item.evidence_id][:6],
    )


def _score_hiring_accessibility(candidate: SupervisorCandidate) -> ScoreDimension:
    signals = 0
    matched: list[str] = []
    if candidate.current_opening_signal:
        signals += 2
        matched.append("opening signal")
    if candidate.email:
        signals += 1
        matched.append("email")
    if candidate.contact_url:
        signals += 1
        matched.append("contact URL")
    if candidate.profile_urls:
        signals += 1
        matched.append("profile URL")
    score = _score_from_matches(signals, 4)
    return _make_dimension(
        "hiring_accessibility",
        score,
        DEFAULT_SCORE_WEIGHTS["hiring_accessibility"],
        matched,
        [],
    )


def _score_methodological_alignment(candidate: SupervisorCandidate) -> ScoreDimension:
    text = _candidate_text(candidate)
    method_hits = sorted(keyword for keyword in METHOD_HEAVY_KEYWORDS if keyword in text)
    domain_counts = _collect_candidate_domains(candidate)
    has_clinical_translation = bool(set(domain_counts) & CLINICAL_TRANSLATION_DOMAINS)
    if method_hits and has_clinical_translation:
        score = 4.0
        warnings: list[str] = []
    elif method_hits:
        score = 2.5
        warnings = ["Method evidence appears weakly connected to clinical translation."]
    else:
        score = 3.0 if has_clinical_translation else 1.5
        warnings = []
    return _make_dimension(
        "methodological_alignment",
        score,
        DEFAULT_SCORE_WEIGHTS["methodological_alignment"],
        method_hits,
        [],
        warnings,
    )


def score_candidate(candidate: SupervisorCandidate) -> CandidateReport:
    """Score one candidate and return an auditable candidate report."""
    domain_counts = _collect_candidate_domains(candidate)
    evidence_items = _collect_evidence(candidate)
    dimensions = [
        _score_digital_medicine(candidate, domain_counts, evidence_items),
        _score_disease_fit(candidate, domain_counts, evidence_items),
        _score_data_strength(candidate, domain_counts, evidence_items),
        _score_publication_potential(candidate, evidence_items),
        _score_recent_impact(candidate, evidence_items),
        _score_hiring_accessibility(candidate),
        _score_methodological_alignment(candidate),
    ]
    raw_score = calculate_weighted_score(dimensions)
    penalty_applied, penalty, warnings = detect_method_heavy_profile(candidate)
    overall_score = round(max(0.0, raw_score - penalty), 3)
    breakdown = ScoreBreakdown(
        dimensions=dimensions,
        overall_score=overall_score,
        priority_label=assign_priority_label(overall_score),
        method_heavy_penalty_applied=penalty_applied,
        method_heavy_penalty=penalty,
        warnings=warnings,
    )
    return CandidateReport(candidate=candidate, score_breakdown=breakdown)


def rank_candidates(candidates: list[SupervisorCandidate]) -> RankedCandidateList:
    """Score and rank candidates deterministically."""
    reports = [score_candidate(candidate) for candidate in candidates]
    reports.sort(
        key=lambda report: (
            -report.score_breakdown.overall_score,
            report.candidate.name.casefold(),
        )
    )
    for index, report in enumerate(reports, start=1):
        report.rank = index
    return RankedCandidateList(
        candidates=reports,
        scoring_version=SCORING_VERSION,
        notes="Deterministic mock scoring; no external APIs or scraping used.",
    )


def load_candidates_from_yaml(input_path: Path) -> list[SupervisorCandidate]:
    """Load supervisor candidates from a YAML file."""
    payload = yaml.safe_load(input_path.read_text(encoding="utf-8")) or {}
    raw_candidates = payload.get("candidates", [])
    if not isinstance(raw_candidates, list):
        raise ValueError("Candidate YAML must contain a top-level candidates list.")
    return [SupervisorCandidate.model_validate(candidate) for candidate in raw_candidates]


def write_candidate_scores_json(ranked: RankedCandidateList, output_dir: Path) -> Path:
    """Write ranked candidate scores as JSON."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "mock_candidate_scores.json"
    output_path.write_text(ranked.model_dump_json(indent=2), encoding="utf-8")
    return output_path


def write_candidate_scores_markdown(ranked: RankedCandidateList, output_dir: Path) -> Path:
    """Write ranked candidate scores as Markdown."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "mock_candidate_scores.md"
    lines = [
        "# Mock Candidate Scores",
        "",
        f"- Scoring version: {ranked.scoring_version}",
        f"- Candidates: {len(ranked.candidates)}",
        "",
        "## Ranked Candidates",
        "",
    ]
    for report in ranked.candidates:
        breakdown = report.score_breakdown
        candidate = report.candidate
        lines.extend(
            [
                f"### {report.rank}. {candidate.name}",
                "",
                f"- Overall score: {breakdown.overall_score:.3f}",
                f"- Priority label: {breakdown.priority_label}",
                f"- Method-heavy penalty applied: {breakdown.method_heavy_penalty_applied}",
                f"- Method-heavy penalty: {breakdown.method_heavy_penalty:.2f}",
                f"- Domains: {', '.join(candidate.domains) or 'None listed'}",
                "",
                "| Dimension | Score | Stars | Weight | Contribution | Evidence IDs |",
                "| --- | ---: | --- | ---: | ---: | --- |",
            ]
        )
        for dimension in breakdown.dimensions:
            lines.append(
                "| "
                f"{dimension.name} | {dimension.numeric_score:.2f} | {dimension.stars} | "
                f"{dimension.weight:.1f} | {dimension.weighted_contribution:.2f} | "
                f"{', '.join(dimension.supporting_evidence_ids) or 'None'} |"
            )
        lines.extend(["", "Supporting evidence:"])
        evidence_items = _collect_evidence(candidate)
        if evidence_items:
            for evidence in evidence_items:
                evidence_id = evidence.evidence_id or "untracked"
                text = evidence.quoted_or_paraphrased_evidence or evidence.note
                lines.append(
                    f"- `{evidence_id}`: {evidence.title or evidence.source_name} - {text}"
                )
        else:
            lines.append("- None")
        lines.extend(["", "Warnings:"])
        warnings = [
            *breakdown.warnings,
            *(warning for dimension in breakdown.dimensions for warning in dimension.warnings),
        ]
        lines.extend(f"- {warning}" for warning in warnings or ["None"])
        lines.append("")

    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


def score_candidates_from_file(
    input_path: Path,
    output_dir: Path,
) -> tuple[RankedCandidateList, list[Path]]:
    """Load, score, rank, and write candidate score reports."""
    ranked = rank_candidates(load_candidates_from_yaml(input_path))
    output_paths = [
        write_candidate_scores_json(ranked, output_dir),
        write_candidate_scores_markdown(ranked, output_dir),
    ]
    return ranked, output_paths
