"""Deterministic CV-to-PI fit matching for ranked supervisor candidates."""

import csv
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from postdoc_scout.models import (
    CandidateFitAssessment,
    CandidateOpportunityAssessment,
    CandidateRankingReport,
    EnrichedCandidateReport,
    EnrichedSupervisorCandidate,
    EvidenceItem,
    FitDimension,
    FitMatchingReport,
    FitPriority,
    OpeningSignal,
    OpeningSignalReport,
    RankedSupervisorCandidate,
    ReviewStatus,
    UserResearchProfile,
)

FIT_LIMITATIONS = [
    "Fit matching is deterministic and based only on supplied profile and candidate evidence.",
    (
        "The report does not infer private facts, availability, visa fit, funding "
        "certainty, or mentorship quality."
    ),
    "Opening signals are preliminary and require manual verification.",
    "Human review is required before any application decision.",
]

FIT_WEIGHTS = {
    "domain_fit": 22.0,
    "data_fit": 18.0,
    "translational_fit": 18.0,
    "disease_fit": 15.0,
    "method_fit": 10.0,
    "opportunity_fit": 7.0,
    "mismatch_risk": 10.0,
}

SUPPORTED_FORMATS = {"json", "md", "csv", "all"}

METHOD_HEAVY_PATTERNS = [
    "benchmark-only",
    "simulation-only",
    "optimization theory",
    "statistical theory",
    "foundation model architecture",
    "pure method",
    "method-heavy",
]
WET_LAB_PATTERNS = ["wet-lab only", "wet lab only", "bench-only", "animal model only"]
CLINICAL_FELLOWSHIP_PATTERNS = ["clinical fellowship only", "medical fellowship only"]

DOMAIN_SYNONYMS = {
    "ad/adrd": ["ad/adrd", "alzheimer", "dementia", "neurodegeneration", "cognitive decline"],
    "ehr/rwd": ["ehr", "electronic health record", "real-world data", "rwd"],
    "clinical ai": ["clinical ai", "clinical artificial intelligence"],
    "digital medicine": ["digital medicine", "digital health"],
    "clinical decision support": ["clinical decision support", "decision support"],
    "oncology": ["oncology", "cancer"],
}


@dataclass(frozen=True)
class CandidateContext:
    """Ranked candidate plus optional enrichment and opportunity context."""

    ranked: RankedSupervisorCandidate
    enriched: EnrichedSupervisorCandidate | None = None
    opportunity: CandidateOpportunityAssessment | None = None


def match_fit_from_files(
    ranked_file: Path,
    user_profile: Path,
    output_dir: Path,
    top_n: int | None = None,
    output_format: str = "all",
) -> tuple[FitMatchingReport, list[Path]]:
    """Load profile/candidates, build fit assessments, and write requested reports."""
    report = build_fit_matching_report(
        ranked_file=ranked_file,
        user_profile_file=user_profile,
        top_n=top_n,
    )
    return report, write_fit_matching_reports(report, output_dir, output_format)


def build_fit_matching_report(
    ranked_file: Path,
    user_profile_file: Path,
    top_n: int | None = None,
) -> FitMatchingReport:
    """Build a deterministic fit report from a user profile and ranked/enriched file."""
    profile = load_user_profile(user_profile_file)
    contexts = load_candidate_contexts(ranked_file)
    if top_n is not None:
        contexts = contexts[: max(0, top_n)]
    assessments = [assess_candidate_fit(context, profile) for context in contexts]
    assessments.sort(key=lambda item: (-item.fit_score, item.display_name.casefold()))
    return FitMatchingReport(
        generated_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
        ranked_file=str(ranked_file),
        user_profile_file=str(user_profile_file),
        user_profile=profile,
        candidate_count=len(assessments),
        candidates=assessments,
        warnings=[],
        limitations=FIT_LIMITATIONS,
    )


def load_user_profile(path: Path) -> UserResearchProfile:
    """Load a user research profile from YAML."""
    if not path.exists():
        raise FileNotFoundError(path)
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("User profile YAML must contain a mapping.")
    return UserResearchProfile.model_validate(payload)


def load_candidate_contexts(ranked_file: Path) -> list[CandidateContext]:
    """Load ranked or enriched candidates and optional sibling opening-signal report."""
    payload = yaml.safe_load(ranked_file.read_text(encoding="utf-8")) or {}
    opportunity_by_id = _load_sibling_opening_signals(ranked_file)
    if "ranked_candidates" in payload:
        ranked = CandidateRankingReport.model_validate(payload).ranked_candidates
        return [
            CandidateContext(
                ranked=candidate,
                opportunity=opportunity_by_id.get(candidate.candidate_id),
            )
            for candidate in ranked
        ]
    if "candidates" in payload and payload["candidates"]:
        first = payload["candidates"][0]
        if isinstance(first, dict) and "ranked_candidate" in first:
            enriched = EnrichedCandidateReport.model_validate(payload).candidates
            return [
                CandidateContext(
                    ranked=candidate.ranked_candidate,
                    enriched=candidate,
                    opportunity=opportunity_by_id.get(candidate.ranked_candidate.candidate_id),
                )
                for candidate in enriched
            ]
    raise ValueError("Expected ranked_supervisors.json or enriched_supervisors.json.")


def assess_candidate_fit(
    context: CandidateContext,
    profile: UserResearchProfile,
) -> CandidateFitAssessment:
    """Assess one candidate against one user research profile."""
    ranked = context.ranked
    candidate_text = _candidate_text(context)
    evidence_ids = _candidate_evidence_ids(context)
    dimensions = [
        _term_dimension(
            name="domain_fit",
            profile_terms=profile.preferred_domains,
            candidate_text=candidate_text,
            evidence_ids=evidence_ids,
            explanation_label="preferred domain",
            secondary_terms=profile.secondary_domains,
        ),
        _term_dimension(
            name="data_fit",
            profile_terms=profile.datasets,
            candidate_text=candidate_text,
            evidence_ids=evidence_ids,
            explanation_label="dataset or data-resource",
        ),
        _term_dimension(
            name="translational_fit",
            profile_terms=profile.translational_strengths,
            candidate_text=candidate_text,
            evidence_ids=evidence_ids,
            explanation_label="translational strength",
        ),
        _term_dimension(
            name="disease_fit",
            profile_terms=profile.disease_areas,
            candidate_text=candidate_text,
            evidence_ids=evidence_ids,
            explanation_label="disease area",
        ),
        _term_dimension(
            name="method_fit",
            profile_terms=profile.methods,
            candidate_text=candidate_text,
            evidence_ids=evidence_ids,
            explanation_label="method",
        ),
        _opportunity_dimension(context),
        _mismatch_dimension(context, profile, candidate_text),
    ]
    total_weight = sum(dimension.weight for dimension in dimensions)
    fit_score = round(
        sum(dimension.weighted_contribution for dimension in dimensions) / total_weight,
        3,
    )
    mismatch_warnings = _dedupe(
        warning for dimension in dimensions for warning in dimension.warnings
    )
    fit_priority = _fit_priority(fit_score, mismatch_warnings)
    status = _recommended_status(fit_priority, mismatch_warnings)
    strengths = _transferable_strengths(profile, dimensions)
    explanation = _fit_explanation(ranked, dimensions, mismatch_warnings)
    return CandidateFitAssessment(
        candidate_id=ranked.candidate_id,
        display_name=ranked.display_name,
        original_priority_label=ranked.priority_label,
        original_score=ranked.overall_score,
        fit_score=fit_score,
        fit_priority=fit_priority,
        recommended_shortlist_status=status,
        dimensions=dimensions,
        transferable_strengths=strengths,
        mismatch_warnings=mismatch_warnings,
        evidence_ids=evidence_ids,
        explanation=explanation,
        human_review_checklist=[
            "Verify current role, lab activity, and institutional affiliation.",
            "Check recent publications for senior or corresponding authorship.",
            "Confirm whether the lab has current postdoctoral capacity.",
            "Review mentorship environment and funding fit manually.",
            "Treat this report as triage evidence, not an application recommendation.",
        ],
    )


def write_fit_matching_reports(
    report: FitMatchingReport,
    output_dir: Path,
    output_format: str = "all",
) -> list[Path]:
    """Write fit matching reports in JSON, Markdown, CSV, or all formats."""
    normalized_format = output_format.casefold()
    if normalized_format not in SUPPORTED_FORMATS:
        raise ValueError(f"Unsupported output format: {output_format}")
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    if normalized_format in {"json", "all"}:
        paths.append(write_fit_matching_json(report, output_dir))
    if normalized_format in {"md", "all"}:
        paths.append(write_fit_matching_markdown(report, output_dir))
    if normalized_format in {"csv", "all"}:
        paths.append(write_fit_matching_csv(report, output_dir))
    return paths


def write_fit_matching_json(report: FitMatchingReport, output_dir: Path) -> Path:
    """Write fit assessments to JSON."""
    path = output_dir / "fit_assessments.json"
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return path


def write_fit_matching_markdown(report: FitMatchingReport, output_dir: Path) -> Path:
    """Write fit assessments to Markdown."""
    path = output_dir / "fit_assessments.md"
    profile = report.user_profile
    lines = [
        "# CV-to-PI Fit Matching",
        "",
        "## User Profile Summary",
        "",
        f"- Name: {profile.name or 'Not provided'}",
        f"- Current position: {profile.current_position or 'Not provided'}",
        f"- Current affiliation: {profile.current_affiliation or 'Not provided'}",
        f"- Target role: {profile.target_role or 'Not provided'}",
        f"- Preferred domains: {_join(profile.preferred_domains)}",
        f"- Secondary domains: {_join(profile.secondary_domains)}",
        f"- Methods: {_join(profile.methods)}",
        f"- Datasets: {_join(profile.datasets)}",
        f"- Disease areas: {_join(profile.disease_areas)}",
        f"- Translational strengths: {_join(profile.translational_strengths)}",
        "",
        "## Ranked Fit Table",
        "",
        (
            "| Candidate | Original priority | Original score | Fit score | Fit priority | "
            "Shortlist status |"
        ),
        "| --- | --- | ---: | ---: | --- | --- |",
    ]
    for candidate in report.candidates:
        lines.append(
            "| "
            f"{candidate.display_name} | "
            f"{candidate.original_priority_label} | "
            f"{candidate.original_score:.3f} | "
            f"{candidate.fit_score:.3f} | "
            f"{candidate.fit_priority} | "
            f"{candidate.recommended_shortlist_status} |"
        )
    lines.extend(["", "## Candidate Details", ""])
    for candidate in report.candidates:
        lines.extend(
            [
                f"### {candidate.display_name}",
                "",
                f"- Candidate ID: {candidate.candidate_id}",
                f"- Fit score: {candidate.fit_score:.3f}",
                f"- Fit priority: {candidate.fit_priority}",
                f"- Recommended shortlist priority: {candidate.recommended_shortlist_status}",
                f"- Transferable strengths: {_join(candidate.transferable_strengths)}",
                f"- Mismatch risks: {_join(candidate.mismatch_warnings)}",
                f"- Evidence IDs: {_join(candidate.evidence_ids)}",
                f"- Summary: {candidate.explanation}",
                "",
                "| Dimension | Score | Weight | Matched terms | Explanation |",
                "| --- | ---: | ---: | --- | --- |",
            ]
        )
        for dimension in candidate.dimensions:
            warning_text = f" Warnings: {_join(dimension.warnings)}" if dimension.warnings else ""
            lines.append(
                "| "
                f"{dimension.name} | "
                f"{dimension.score:.2f} | "
                f"{dimension.weight:.1f} | "
                f"{_join(dimension.matched_terms)} | "
                f"{dimension.explanation}{warning_text} |"
            )
        lines.extend(
            [
                "",
                "Human-review checklist:",
                "",
                *[f"- {item}" for item in candidate.human_review_checklist],
                "",
            ]
        )
    lines.extend(["## Limitations", "", *[f"- {item}" for item in report.limitations], ""])
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_fit_matching_csv(report: FitMatchingReport, output_dir: Path) -> Path:
    """Write fit assessments to CSV."""
    path = output_dir / "fit_assessments.csv"
    fieldnames = [
        "candidate_id",
        "display_name",
        "original_priority_label",
        "original_score",
        "fit_score",
        "fit_priority",
        "domain_fit",
        "data_fit",
        "translational_fit",
        "disease_fit",
        "method_fit",
        "opportunity_fit",
        "mismatch_risk",
        "mismatch_warnings",
        "recommended_shortlist_status",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for candidate in report.candidates:
            dimensions = {dimension.name: dimension.score for dimension in candidate.dimensions}
            writer.writerow(
                {
                    "candidate_id": candidate.candidate_id,
                    "display_name": candidate.display_name,
                    "original_priority_label": candidate.original_priority_label,
                    "original_score": f"{candidate.original_score:.3f}",
                    "fit_score": f"{candidate.fit_score:.3f}",
                    "fit_priority": candidate.fit_priority,
                    "domain_fit": f"{dimensions['domain_fit']:.2f}",
                    "data_fit": f"{dimensions['data_fit']:.2f}",
                    "translational_fit": f"{dimensions['translational_fit']:.2f}",
                    "disease_fit": f"{dimensions['disease_fit']:.2f}",
                    "method_fit": f"{dimensions['method_fit']:.2f}",
                    "opportunity_fit": f"{dimensions['opportunity_fit']:.2f}",
                    "mismatch_risk": f"{dimensions['mismatch_risk']:.2f}",
                    "mismatch_warnings": "; ".join(candidate.mismatch_warnings),
                    "recommended_shortlist_status": candidate.recommended_shortlist_status,
                }
            )
    return path


def _term_dimension(
    name: str,
    profile_terms: list[str],
    candidate_text: str,
    evidence_ids: list[str],
    explanation_label: str,
    secondary_terms: list[str] | None = None,
) -> FitDimension:
    matched_primary = _matched_terms(profile_terms, candidate_text)
    matched_secondary = _matched_terms(secondary_terms or [], candidate_text)
    if not profile_terms and not secondary_terms:
        score = 2.5
        explanation = f"No user {explanation_label} terms were supplied; neutral score assigned."
    elif matched_primary:
        score = min(5.0, 3.2 + 0.55 * len(matched_primary) + 0.25 * len(matched_secondary))
        explanation = (
            f"Candidate evidence matches {explanation_label} terms: {_join(matched_primary)}."
        )
        if matched_secondary:
            explanation += f" Secondary matches: {_join(matched_secondary)}."
    elif matched_secondary:
        score = min(4.0, 2.8 + 0.35 * len(matched_secondary))
        explanation = (
            f"Candidate evidence matches secondary {explanation_label} terms: "
            f"{_join(matched_secondary)}."
        )
    else:
        score = 1.5
        explanation = f"No direct {explanation_label} match found in supplied candidate evidence."
    weight = FIT_WEIGHTS[name]
    return FitDimension(
        name=name,  # type: ignore[arg-type]
        score=round(score, 2),
        weight=weight,
        weighted_contribution=round(score * weight, 3),
        matched_terms=_dedupe([*matched_primary, *matched_secondary]),
        explanation=explanation,
        supporting_evidence_ids=evidence_ids if matched_primary or matched_secondary else [],
        warnings=[],
    )


def _opportunity_dimension(context: CandidateContext) -> FitDimension:
    opportunity = context.opportunity
    opening_signals = context.enriched.enrichment.opening_signals if context.enriched else []
    evidence_ids = _opportunity_evidence_ids(opportunity, opening_signals)
    warnings: list[str] = []
    matched_terms: list[str] = []
    if opportunity is not None:
        matched_terms.append(opportunity.opening_signal_type)
        warnings.extend(opportunity.warnings)
        score = {
            "high": 5.0,
            "medium": 4.0,
            "low": 3.2,
            "none": 2.5,
        }.get(opportunity.opening_signal_strength, 2.5)
        if opportunity.opening_signal_type in {"outdated_signal", "mismatch_signal"}:
            score = 1.5
        explanation = (
            f"Opening-signal report classified this candidate as "
            f"{opportunity.opening_signal_type} with "
            f"{opportunity.opening_signal_strength} strength."
        )
    elif opening_signals:
        best = _best_enriched_opening_signal(opening_signals)
        matched_terms.append(best.signal_type)
        warnings.extend(best.warnings)
        score = 4.0 if best.signal_type != "no_signal_found" else 2.5
        if best.signal_type in {"outdated_signal", "mismatch_signal"}:
            score = 1.5
        explanation = f"Enrichment evidence includes opening signal: {best.signal_type}."
    else:
        score = 2.5
        explanation = "No opening-signal evidence was supplied; neutral opportunity score assigned."
    weight = FIT_WEIGHTS["opportunity_fit"]
    return FitDimension(
        name="opportunity_fit",
        score=round(score, 2),
        weight=weight,
        weighted_contribution=round(score * weight, 3),
        matched_terms=_dedupe(matched_terms),
        explanation=explanation,
        supporting_evidence_ids=evidence_ids,
        warnings=_dedupe(warnings),
    )


def _mismatch_dimension(
    context: CandidateContext,
    profile: UserResearchProfile,
    candidate_text: str,
) -> FitDimension:
    warnings: list[str] = []
    matched_terms: list[str] = []
    avoid = {key: bool(value) for key, value in profile.avoid_directions.items()}
    if avoid.get("pure_statistical_theory") or avoid.get("pure_algorithm_architecture"):
        matched = _matched_terms(METHOD_HEAVY_PATTERNS, candidate_text)
        if matched or context.ranked.method_heavy_penalty_applied:
            matched_terms.extend(matched or ["method_heavy_penalty"])
            warnings.append(
                "Candidate evidence appears method-heavy relative to avoid_directions."
            )
    if avoid.get("wet_lab_only"):
        matched = _matched_terms(WET_LAB_PATTERNS, candidate_text)
        if matched:
            matched_terms.extend(matched)
            warnings.append("Candidate evidence may indicate wet-lab-only direction.")
    if avoid.get("clinical_fellowship_only"):
        matched = _matched_terms(CLINICAL_FELLOWSHIP_PATTERNS, candidate_text)
        if matched:
            matched_terms.extend(matched)
            warnings.append("Candidate evidence may indicate clinical-fellowship-only direction.")
    warnings.extend(
        warning
        for warning in context.ranked.warnings
        if "method-heavy" in warning.casefold() or "limited clinical" in warning.casefold()
    )
    if context.opportunity and context.opportunity.opening_signal_type == "mismatch_signal":
        warnings.append("Opening evidence contains a mismatch signal.")
    warning_count = len(_dedupe(warnings))
    score = max(0.0, 5.0 - 1.4 * warning_count)
    explanation = (
        "No avoid-direction mismatch detected in supplied evidence."
        if warning_count == 0
        else "Avoid-direction or fit-risk warnings were detected; score reflects lower safety."
    )
    weight = FIT_WEIGHTS["mismatch_risk"]
    return FitDimension(
        name="mismatch_risk",
        score=round(score, 2),
        weight=weight,
        weighted_contribution=round(score * weight, 3),
        matched_terms=_dedupe(matched_terms),
        explanation=explanation,
        supporting_evidence_ids=_candidate_evidence_ids(context) if warning_count else [],
        warnings=_dedupe(warnings),
    )


def _candidate_text(context: CandidateContext) -> str:
    ranked = context.ranked
    parts: list[str] = [
        ranked.display_name,
        *ranked.possible_affiliations,
        *ranked.matched_institution_units,
        *ranked.inferred_domains,
        *ranked.warnings,
        *ranked.limitations,
    ]
    for evidence in ranked.evidence_items:
        parts.extend(_evidence_text_parts(evidence))
    if context.enriched:
        enrichment = context.enriched.enrichment
        parts.extend(enrichment.possible_affiliations)
        parts.extend(enrichment.manual_profile_notes)
        parts.extend(enrichment.enrichment_warnings)
        for grant in enrichment.nih_reporter_grants:
            parts.extend(
                [
                    grant.title,
                    grant.funder,
                    grant.organization,
                    *grant.relevance_domains,
                    grant.notes,
                ]
            )
        for profile in enrichment.semantic_scholar_profiles:
            parts.extend([profile.name, *profile.affiliations, *profile.fields_of_study])
            parts.extend(profile.warnings)
        for evidence in enrichment.evidence_items:
            parts.extend(_evidence_text_parts(evidence))
        for opening in enrichment.opening_signals:
            parts.extend([opening.signal_type, opening.text_or_note])
            parts.extend(opening.warnings)
    if context.opportunity:
        parts.extend(
            [
                context.opportunity.opening_signal_type,
                context.opportunity.opening_signal_strength,
                context.opportunity.evidence_snippet,
                context.opportunity.source_query,
            ]
        )
        parts.extend(context.opportunity.warnings)
        for evidence in context.opportunity.evidence_items:
            parts.extend(_evidence_text_parts(evidence))
    return _normalize(" ".join(part for part in parts if part))


def _evidence_text_parts(evidence: EvidenceItem) -> list[str]:
    return [
        evidence.evidence_id,
        evidence.source_type,
        evidence.title,
        evidence.source_name,
        evidence.quoted_or_paraphrased_evidence,
        *evidence.relevance_domains,
        evidence.note,
        evidence.notes,
    ]


def _candidate_evidence_ids(context: CandidateContext) -> list[str]:
    ids = [item.evidence_id for item in context.ranked.evidence_items if item.evidence_id]
    if context.enriched:
        enrichment = context.enriched.enrichment
        ids.extend(item.evidence_id for item in enrichment.evidence_items if item.evidence_id)
        ids.extend(
            grant.evidence_id
            for grant in enrichment.nih_reporter_grants
            if grant.evidence_id
        )
        ids.extend(
            signal.evidence_id
            for signal in enrichment.opening_signals
            if signal.evidence_id
        )
    if context.opportunity:
        ids.extend(
            item.evidence_id
            for item in context.opportunity.evidence_items
            if item.evidence_id
        )
    return _dedupe(ids)


def _opportunity_evidence_ids(
    opportunity: CandidateOpportunityAssessment | None,
    opening_signals: list[OpeningSignal],
) -> list[str]:
    ids: list[str] = []
    if opportunity:
        ids.extend(item.evidence_id for item in opportunity.evidence_items if item.evidence_id)
    ids.extend(signal.evidence_id for signal in opening_signals if signal.evidence_id)
    return _dedupe(ids)


def _load_sibling_opening_signals(ranked_file: Path) -> dict[str, CandidateOpportunityAssessment]:
    opening_path = ranked_file.parent / "opening_signals.json"
    if not opening_path.exists():
        return {}
    payload = opening_path.read_text(encoding="utf-8")
    report = OpeningSignalReport.model_validate_json(payload)
    return {candidate.candidate_id: candidate for candidate in report.candidates}


def _matched_terms(terms: list[str], candidate_text: str) -> list[str]:
    matches: list[str] = []
    for term in terms:
        expanded_terms = [term, *DOMAIN_SYNONYMS.get(_normalize(term), [])]
        if any(_term_in_text(expanded, candidate_text) for expanded in expanded_terms):
            matches.append(term)
    return _dedupe(matches)


def _term_in_text(term: str, candidate_text: str) -> bool:
    normalized = _normalize(term)
    if not normalized:
        return False
    if normalized in candidate_text:
        return True
    tokens = [token for token in normalized.split() if len(token) > 2]
    return bool(tokens) and all(token in candidate_text for token in tokens)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9/+-]+", " ", text.casefold())).strip()


def _best_enriched_opening_signal(signals: list[OpeningSignal]) -> OpeningSignal:
    priority = {
        "explicit_postdoc_opening": 5,
        "lab_hiring_statement": 4,
        "contact_for_positions": 4,
        "recent_grant_possible_hiring": 3,
        "manual_note": 2,
        "no_signal_found": 1,
        "outdated_signal": 0,
        "mismatch_signal": 0,
    }
    return max(signals, key=lambda signal: (priority.get(signal.signal_type, 1), signal.confidence))


def _fit_priority(fit_score: float, warnings: list[str]) -> FitPriority:
    if len(warnings) >= 2 and fit_score < 3.0:
        return "avoid_or_review"
    if fit_score >= 4.2:
        return "strong_fit"
    if fit_score >= 3.5:
        return "good_fit"
    if fit_score >= 2.8:
        return "possible_fit"
    return "low_fit"


def _recommended_status(priority: FitPriority, warnings: list[str]) -> ReviewStatus:
    if priority == "strong_fit" and len(warnings) <= 1:
        return "interested"
    if priority in {"good_fit", "possible_fit"}:
        return "maybe"
    if priority == "avoid_or_review":
        return "needs_more_review"
    return "low_priority"


def _transferable_strengths(
    profile: UserResearchProfile,
    dimensions: list[FitDimension],
) -> list[str]:
    matched = {term for dimension in dimensions for term in dimension.matched_terms}
    strengths = [
        term
        for term in [
            *profile.preferred_domains,
            *profile.datasets,
            *profile.translational_strengths,
            *profile.disease_areas,
            *profile.methods,
        ]
        if term in matched
    ]
    return _dedupe(strengths)[:8]


def _fit_explanation(
    ranked: RankedSupervisorCandidate,
    dimensions: list[FitDimension],
    mismatch_warnings: list[str],
) -> str:
    strongest = sorted(dimensions, key=lambda item: item.score, reverse=True)[:2]
    strengths = ", ".join(dimension.name for dimension in strongest)
    if mismatch_warnings:
        return (
            f"{ranked.display_name} has strongest evidence in {strengths}, "
            "but mismatch warnings require manual review."
        )
    return f"{ranked.display_name} has strongest evidence in {strengths}."


def _join(values: list[Any]) -> str:
    cleaned = [str(value) for value in values if str(value).strip()]
    return ", ".join(cleaned) if cleaned else "None"


def _dedupe(values: Any) -> list[Any]:
    seen: set[Any] = set()
    deduped: list[Any] = []
    for value in values:
        if value in seen or value in {"", None}:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped
