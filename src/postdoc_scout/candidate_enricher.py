"""Enrich ranked supervisor candidates with profile and funding evidence."""

import csv
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from postdoc_scout.connectors import ConnectorError, NIHReporterConnector, SemanticScholarConnector
from postdoc_scout.models import (
    AuthorProfileEvidence,
    CandidateProfileEnrichment,
    CandidateRankingReport,
    EnrichedCandidateReport,
    EnrichedSupervisorCandidate,
    EnrichmentRunSummary,
    EnrichmentSource,
    EvidenceItem,
    FundingEvidence,
    OpeningSignal,
    RankedSupervisorCandidate,
)

ENRICHMENT_LIMITATIONS = [
    "Profile matches are preliminary.",
    "NIH RePORTER may miss non-NIH funding.",
    "Semantic Scholar author disambiguation can be incomplete.",
    "Lab openings are not fully scraped yet.",
    "Human review is required before contacting any PI.",
]


class SemanticScholarLike(Protocol):
    """Protocol for Semantic Scholar profile connectors."""

    def search_author_profiles(
        self,
        candidate_name: str,
        affiliations: list[str] | None = None,
        limit: int = 5,
    ) -> list[AuthorProfileEvidence]:
        """Return possible author profiles."""

    def close(self) -> None:
        """Release resources."""


class NIHReporterLike(Protocol):
    """Protocol for NIH RePORTER funding connectors."""

    def search_projects(
        self,
        candidate_name: str,
        organizations: list[str] | None = None,
        year_from: int | None = None,
        year_to: int | None = None,
        limit: int = 10,
    ) -> list[FundingEvidence]:
        """Return possible grant records."""

    def close(self) -> None:
        """Release resources."""


def load_candidate_ranking_report(ranked_file: Path) -> CandidateRankingReport:
    """Load ranked supervisors JSON."""
    return CandidateRankingReport.model_validate_json(ranked_file.read_text(encoding="utf-8"))


def parse_enrichment_sources(sources: str | list[str]) -> list[EnrichmentSource]:
    """Parse comma-separated enrichment source names."""
    raw_sources = sources.split(",") if isinstance(sources, str) else sources
    parsed = [source.strip().casefold() for source in raw_sources if source.strip()]
    allowed = {"nih_reporter", "semantic_scholar", "manual"}
    unsupported = sorted(set(parsed) - allowed)
    if unsupported:
        raise ValueError(f"Unsupported enrichment source(s): {', '.join(unsupported)}")
    deduped = []
    for source in parsed:
        if source not in deduped:
            deduped.append(source)
    return deduped  # type: ignore[return-value]


def enrich_candidates_from_file(
    ranked_file: Path,
    sources: str | list[str] = "nih_reporter,semantic_scholar,manual",
    year_from: int | None = None,
    year_to: int | None = None,
    top_n: int | None = None,
    semantic_scholar: SemanticScholarLike | None = None,
    nih_reporter: NIHReporterLike | None = None,
) -> EnrichedCandidateReport:
    """Load ranked supervisors and enrich selected candidates."""
    ranked_report = load_candidate_ranking_report(ranked_file)
    return enrich_ranked_candidates(
        ranked_report=ranked_report,
        ranked_file=ranked_file,
        sources=sources,
        year_from=year_from,
        year_to=year_to,
        top_n=top_n,
        semantic_scholar=semantic_scholar,
        nih_reporter=nih_reporter,
    )


def enrich_ranked_candidates(
    ranked_report: CandidateRankingReport,
    ranked_file: Path | str,
    sources: str | list[str] = "nih_reporter,semantic_scholar,manual",
    year_from: int | None = None,
    year_to: int | None = None,
    top_n: int | None = None,
    semantic_scholar: SemanticScholarLike | None = None,
    nih_reporter: NIHReporterLike | None = None,
) -> EnrichedCandidateReport:
    """Enrich ranked candidates with funding, profile, and manual placeholder evidence."""
    selected_sources = parse_enrichment_sources(sources)
    year_to = year_to or datetime.now(UTC).year
    year_from = year_from if year_from is not None else year_to - 5
    candidates = (
        ranked_report.ranked_candidates[: max(0, top_n)]
        if top_n
        else ranked_report.ranked_candidates
    )
    own_semantic = semantic_scholar is None and "semantic_scholar" in selected_sources
    own_nih = nih_reporter is None and "nih_reporter" in selected_sources
    semantic_scholar = semantic_scholar or (
        SemanticScholarConnector() if "semantic_scholar" in selected_sources else None
    )
    nih_reporter = nih_reporter or (
        NIHReporterConnector() if "nih_reporter" in selected_sources else None
    )
    enriched_candidates: list[EnrichedSupervisorCandidate] = []
    run_warnings: list[str] = []
    try:
        for candidate in candidates:
            enriched = _enrich_one_candidate(
                candidate=candidate,
                selected_sources=selected_sources,
                year_from=year_from,
                year_to=year_to,
                semantic_scholar=semantic_scholar,
                nih_reporter=nih_reporter,
            )
            enriched_candidates.append(enriched)
            run_warnings.extend(enriched.enrichment.enrichment_warnings)
    finally:
        if own_semantic and semantic_scholar is not None:
            semantic_scholar.close()
        if own_nih and nih_reporter is not None:
            nih_reporter.close()

    summary = EnrichmentRunSummary(
        sources=selected_sources,
        candidates_processed=len(enriched_candidates),
        candidates_with_funding_evidence=sum(
            bool(candidate.enrichment.nih_reporter_grants)
            for candidate in enriched_candidates
        ),
        candidates_with_author_profile_evidence=sum(
            bool(candidate.enrichment.semantic_scholar_profiles)
            for candidate in enriched_candidates
        ),
        candidates_with_opening_signals=sum(
            any(
                signal.signal_type != "no_signal_found"
                for signal in candidate.enrichment.opening_signals
            )
            for candidate in enriched_candidates
        ),
        warnings=_dedupe(run_warnings),
    )
    return EnrichedCandidateReport(
        generated_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
        ranked_file=str(ranked_file),
        run_summary=summary,
        candidates=enriched_candidates,
        limitations=ENRICHMENT_LIMITATIONS,
    )


def write_enriched_candidates_json(report: EnrichedCandidateReport, output_dir: Path) -> Path:
    """Write enriched supervisors JSON."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "enriched_supervisors.json"
    output_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return output_path


def write_enriched_candidates_markdown(report: EnrichedCandidateReport, output_dir: Path) -> Path:
    """Write enriched supervisors Markdown."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "enriched_supervisors.md"
    summary = report.run_summary
    lines = [
        "# Enriched Supervisor Candidates",
        "",
        "## Enrichment Run Summary",
        "",
        f"- Generated at: {report.generated_at}",
        f"- Ranked file: {report.ranked_file}",
        f"- Connectors used: {', '.join(summary.sources)}",
        f"- Candidates processed: {summary.candidates_processed}",
        f"- Candidates with funding evidence: {summary.candidates_with_funding_evidence}",
        f"- Candidates with author profile evidence: "
        f"{summary.candidates_with_author_profile_evidence}",
        f"- Candidates with opening signals: {summary.candidates_with_opening_signals}",
        "",
        "## Enriched Ranked Table",
        "",
        "| Rank | Name | Original Score | Adjusted Score | Funding | Profiles | "
        "Opening | Warnings |",
        "| ---: | --- | ---: | ---: | ---: | ---: | --- | ---: |",
    ]
    for candidate in report.candidates:
        enrichment = candidate.enrichment
        signal_type = _primary_opening_signal(enrichment.opening_signals).signal_type
        lines.append(
            "| "
            f"{candidate.ranked_candidate.rank} | {candidate.ranked_candidate.display_name} | "
            f"{candidate.ranked_candidate.overall_score:.3f} | "
            f"{candidate.enrichment_adjusted_score or candidate.ranked_candidate.overall_score:.3f}"
            " | "
            f"{len(enrichment.nih_reporter_grants)} | "
            f"{len(enrichment.semantic_scholar_profiles)} | "
            f"{signal_type} | "
            f"{len(enrichment.enrichment_warnings)} |"
        )
    if not report.candidates:
        lines.append("|  | None |  |  |  |  |  |  |")
    lines.extend(["", "## Candidate Details", ""])
    for candidate in report.candidates:
        lines.extend(_candidate_detail_lines(candidate))
    lines.extend(["## Run Warnings", ""])
    lines.extend(f"- {warning}" for warning in summary.warnings or ["None"])
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {limitation}" for limitation in report.limitations)
    lines.append("")
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


def write_enriched_candidates_csv(report: EnrichedCandidateReport, output_dir: Path) -> Path:
    """Write enriched supervisors CSV."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "enriched_supervisors.csv"
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "rank",
                "candidate_id",
                "display_name",
                "original_score",
                "original_priority_label",
                "enrichment_adjusted_score",
                "possible_affiliations",
                "funding_evidence_count",
                "semantic_scholar_profile_count",
                "opening_signal_type",
                "enrichment_confidence",
                "enrichment_warning_count",
                "suggested_contact_angle",
                "next_manual_check",
            ],
        )
        writer.writeheader()
        for candidate in report.candidates:
            ranked = candidate.ranked_candidate
            enrichment = candidate.enrichment
            writer.writerow(
                {
                    "rank": ranked.rank,
                    "candidate_id": ranked.candidate_id,
                    "display_name": ranked.display_name,
                    "original_score": f"{ranked.overall_score:.3f}",
                    "original_priority_label": ranked.priority_label,
                    "enrichment_adjusted_score": f"{candidate.enrichment_adjusted_score:.3f}"
                    if candidate.enrichment_adjusted_score is not None
                    else "",
                    "possible_affiliations": "; ".join(ranked.possible_affiliations),
                    "funding_evidence_count": len(enrichment.nih_reporter_grants),
                    "semantic_scholar_profile_count": len(enrichment.semantic_scholar_profiles),
                    "opening_signal_type": _primary_opening_signal(
                        enrichment.opening_signals
                    ).signal_type,
                    "enrichment_confidence": f"{enrichment.confidence:.3f}",
                    "enrichment_warning_count": len(enrichment.enrichment_warnings),
                    "suggested_contact_angle": ranked.suggested_contact_angle,
                    "next_manual_check": candidate.next_manual_check,
                }
            )
    return output_path


def write_enriched_candidate_reports(
    report: EnrichedCandidateReport,
    output_dir: Path,
    output_format: str,
) -> list[Path]:
    """Write enriched supervisor reports as JSON, Markdown, CSV, or all."""
    if output_format == "json":
        return [write_enriched_candidates_json(report, output_dir)]
    if output_format == "md":
        return [write_enriched_candidates_markdown(report, output_dir)]
    if output_format == "csv":
        return [write_enriched_candidates_csv(report, output_dir)]
    return [
        write_enriched_candidates_json(report, output_dir),
        write_enriched_candidates_markdown(report, output_dir),
        write_enriched_candidates_csv(report, output_dir),
    ]


def _enrich_one_candidate(
    candidate: RankedSupervisorCandidate,
    selected_sources: list[EnrichmentSource],
    year_from: int,
    year_to: int,
    semantic_scholar: SemanticScholarLike | None,
    nih_reporter: NIHReporterLike | None,
) -> EnrichedSupervisorCandidate:
    warnings = list(candidate.warnings)
    profiles: list[AuthorProfileEvidence] = []
    grants: list[FundingEvidence] = []
    opening_signals: list[OpeningSignal] = []
    manual_notes: list[str] = []

    if "semantic_scholar" in selected_sources and semantic_scholar is not None:
        try:
            profiles = semantic_scholar.search_author_profiles(
                candidate_name=candidate.display_name,
                affiliations=[
                    *candidate.possible_affiliations,
                    *candidate.matched_institution_units,
                ],
                limit=5,
            )
            warnings.extend(warning for profile in profiles for warning in profile.warnings)
            if not profiles:
                warnings.append(f"No Semantic Scholar profile found for {candidate.display_name}.")
        except ConnectorError as exc:
            warnings.append(str(exc))

    if "nih_reporter" in selected_sources and nih_reporter is not None:
        try:
            grants = nih_reporter.search_projects(
                candidate_name=candidate.display_name,
                organizations=[
                    *candidate.possible_affiliations,
                    *candidate.matched_institution_units,
                ],
                year_from=year_from,
                year_to=year_to,
                limit=10,
            )
            if not grants:
                warnings.append(f"No NIH RePORTER funding found for {candidate.display_name}.")
        except ConnectorError as exc:
            warnings.append(str(exc))

    if "manual" in selected_sources:
        manual_notes.append(
            "Manual profile review placeholder: verify lab page, role, contact route, "
            "current openings, and institutional affiliation before outreach."
        )
        opening_signals.append(
            OpeningSignal(
                signal_type="no_signal_found",
                text_or_note="No lab-opening scraper is implemented yet; manual review required.",
                confidence=0.4,
                evidence_id=f"manual_opening:{candidate.candidate_id}",
                warnings=["Opening status is a placeholder, not verified evidence."],
            )
        )
        warnings.append("Manual opening status placeholder requires human review.")

    enrichment_evidence = _enrichment_evidence_items(candidate, grants, profiles, opening_signals)
    confidence = _enrichment_confidence(profiles, grants, opening_signals, warnings)
    enrichment = CandidateProfileEnrichment(
        candidate_id=candidate.candidate_id,
        display_name=candidate.display_name,
        possible_affiliations=candidate.possible_affiliations,
        profile_urls=[profile.profile_url for profile in profiles if profile.profile_url],
        semantic_scholar_profiles=profiles,
        nih_reporter_grants=grants,
        manual_profile_notes=manual_notes,
        opening_signals=opening_signals,
        enrichment_warnings=_dedupe(warnings),
        confidence=confidence,
        evidence_items=enrichment_evidence,
    )
    return EnrichedSupervisorCandidate(
        ranked_candidate=candidate,
        enrichment=enrichment,
        enrichment_adjusted_score=_adjusted_score(candidate, grants, profiles, opening_signals),
        enrichment_notes=_enrichment_notes(grants, profiles, opening_signals),
        next_manual_check=_next_manual_check(candidate, grants, profiles, opening_signals),
    )


def _adjusted_score(
    candidate: RankedSupervisorCandidate,
    grants: list[FundingEvidence],
    profiles: list[AuthorProfileEvidence],
    opening_signals: list[OpeningSignal],
) -> float:
    boost = 0.0
    if grants:
        boost += 0.2
    if profiles:
        boost += 0.1
    if any(signal.signal_type != "no_signal_found" for signal in opening_signals):
        boost += 0.1
    return round(min(5.0, candidate.overall_score + boost), 3)


def _enrichment_confidence(
    profiles: list[AuthorProfileEvidence],
    grants: list[FundingEvidence],
    opening_signals: list[OpeningSignal],
    warnings: list[str],
) -> float:
    values = [profile.confidence for profile in profiles]
    values.extend(grant.confidence for grant in grants)
    values.extend(signal.confidence for signal in opening_signals)
    if not values:
        return 0.25
    confidence = sum(values) / len(values)
    if warnings:
        confidence -= min(0.25, 0.03 * len(warnings))
    return min(1.0, max(0.0, round(confidence, 3)))


def _enrichment_evidence_items(
    candidate: RankedSupervisorCandidate,
    grants: list[FundingEvidence],
    profiles: list[AuthorProfileEvidence],
    opening_signals: list[OpeningSignal],
) -> list[EvidenceItem]:
    items = []
    for grant in grants:
        items.append(
            EvidenceItem(
                evidence_id=grant.evidence_id,
                source_type="grant",
                title=grant.title,
                url=grant.url,
                source_name=grant.funder or "NIH RePORTER",
                quoted_or_paraphrased_evidence=grant.notes,
                relevance_domains=grant.relevance_domains,
                note=f"{grant.project_number or 'untracked project'} at {grant.organization}",
                confidence=grant.confidence,
            )
        )
    for profile in profiles:
        items.append(
            EvidenceItem(
                evidence_id=f"semantic_scholar:{profile.author_id or profile.name}",
                source_type="other",
                title=f"Semantic Scholar profile for {profile.name}",
                url=profile.profile_url,
                source_name="Semantic Scholar",
                quoted_or_paraphrased_evidence=(
                    f"{profile.paper_count or 0} papers; "
                    f"{profile.citation_count or 0} citations."
                ),
                relevance_domains=candidate.inferred_domains,
                note=profile.matched_by,
                confidence=profile.confidence,
            )
        )
    for signal in opening_signals:
        items.append(
            EvidenceItem(
                evidence_id=signal.evidence_id,
                source_type="manual_note",
                title=f"Opening signal: {signal.signal_type}",
                url=signal.source_url,
                source_name="Manual placeholder",
                quoted_or_paraphrased_evidence=signal.text_or_note,
                relevance_domains=candidate.inferred_domains,
                note="Opening signal placeholder.",
                confidence=signal.confidence,
            )
        )
    return items


def _enrichment_notes(
    grants: list[FundingEvidence],
    profiles: list[AuthorProfileEvidence],
    opening_signals: list[OpeningSignal],
) -> list[str]:
    notes = []
    if grants:
        notes.append(
            "NIH RePORTER funding evidence annotates data_resource_strength and "
            "recent_academic_impact; original score is preserved."
        )
    if profiles:
        notes.append(
            "Semantic Scholar profile evidence annotates author/profile confidence; "
            "identity remains preliminary."
        )
    if opening_signals:
        notes.append("Opening signals are placeholders until lab pages are manually checked.")
    return notes


def _next_manual_check(
    candidate: RankedSupervisorCandidate,
    grants: list[FundingEvidence],
    profiles: list[AuthorProfileEvidence],
    opening_signals: list[OpeningSignal],
) -> str:
    if not profiles:
        return "Verify author identity and affiliation on institutional profile pages."
    if not grants:
        return "Check NIH RePORTER and non-NIH funders for active support."
    if not any(signal.signal_type != "no_signal_found" for signal in opening_signals):
        return "Check lab page and department pages for postdoc opening signals."
    return f"Review {candidate.display_name}'s lab page and recent publications before outreach."


def _candidate_detail_lines(candidate: EnrichedSupervisorCandidate) -> list[str]:
    ranked = candidate.ranked_candidate
    enrichment = candidate.enrichment
    lines = [
        f"### {ranked.rank}. {ranked.display_name}",
        "",
        f"- Original priority label: {ranked.priority_label}",
        f"- Original score: {ranked.overall_score:.3f}",
        f"- Enrichment-adjusted score: {candidate.enrichment_adjusted_score:.3f}"
        if candidate.enrichment_adjusted_score is not None
        else "- Enrichment-adjusted score: not computed",
        f"- Suggested contact angle: {ranked.suggested_contact_angle}",
        f"- Next manual check: {candidate.next_manual_check}",
        "",
        "Funding evidence:",
    ]
    if enrichment.nih_reporter_grants:
        lines.extend(
            f"- `{grant.evidence_id}` {grant.title} ({grant.funder}, {grant.organization})"
            for grant in enrichment.nih_reporter_grants
        )
    else:
        lines.append("- None")
    lines.extend(["", "Author profile evidence:"])
    if enrichment.semantic_scholar_profiles:
        lines.extend(
            f"- {profile.name} ({profile.source}, confidence={profile.confidence:.2f}): "
            f"{profile.profile_url or 'no URL'}"
            for profile in enrichment.semantic_scholar_profiles
        )
    else:
        lines.append("- None")
    lines.extend(["", "Profile/opening signals:"])
    lines.extend(
        f"- {signal.signal_type}: {signal.text_or_note}"
        for signal in enrichment.opening_signals or []
    )
    if not enrichment.opening_signals:
        lines.append("- None")
    lines.extend(["", "Ambiguity warnings:"])
    lines.extend(f"- {warning}" for warning in enrichment.enrichment_warnings or ["None"])
    lines.append("")
    return lines


def _primary_opening_signal(signals: list[OpeningSignal]) -> OpeningSignal:
    if signals:
        return signals[0]
    return OpeningSignal(signal_type="no_signal_found", text_or_note="No opening signal checked.")


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    deduped = []
    for value in values:
        normalized = value.casefold().strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            deduped.append(value)
    return deduped
