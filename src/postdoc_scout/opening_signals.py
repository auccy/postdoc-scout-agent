"""Deterministic lab/profile/opening signal detection from manual evidence."""

import csv
import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from postdoc_scout.models import (
    CandidateOpportunityAssessment,
    CandidateRankingReport,
    EnrichedCandidateReport,
    EvidenceItem,
    OpeningSignalEvidence,
    OpeningSignalReport,
    OpeningSignalStrength,
    OpeningSignalType,
    RankedSupervisorCandidate,
)

OPENING_SIGNAL_LIMITATIONS = [
    "Opening signals are derived only from provided snippets, URLs, or future manual review.",
    "The detector does not scrape arbitrary websites or call live web search.",
    "No candidate should be treated as hiring unless explicit current evidence is verified.",
    "Human review is required before outreach.",
]

EXPLICIT_POSTDOC_PATTERNS = [
    "postdoc opening",
    "postdoctoral opening",
    "postdoctoral position",
    "postdoctoral fellow position",
    "hiring a postdoc",
    "hiring a postdoctoral",
    "postdocs are encouraged to apply",
]
HIRING_PATTERNS = [
    "we are hiring",
    "positions available",
    "open positions",
    "join our lab",
    "join the lab",
    "lab is hiring",
]
CONTACT_PATTERNS = [
    "prospective postdocs should contact",
    "prospective postdoctoral fellows should contact",
    "contact us about postdoctoral opportunities",
    "contact for positions",
    "interested postdocs should contact",
]
RECENT_GRANT_PATTERNS = [
    "recent grant",
    "newly funded",
    "funded project",
    "grant supported",
]
MISMATCH_PATTERNS = [
    "clinical fellowship only",
    "wet-lab only",
    "wet lab only",
    "not accepting postdocs",
    "not currently accepting postdocs",
]


def detect_openings_from_file(
    ranked_file: Path,
    output_dir: Path,
    manual_signals: Path | None = None,
    top_n: int | None = None,
    output_format: str = "all",
) -> tuple[OpeningSignalReport, list[Path]]:
    """Load candidates, detect opening signals, and write reports."""
    report = build_opening_signal_report(
        ranked_file=ranked_file,
        manual_signals=manual_signals,
        top_n=top_n,
    )
    return report, write_opening_signal_reports(report, output_dir, output_format)


def build_opening_signal_report(
    ranked_file: Path,
    manual_signals: Path | None = None,
    top_n: int | None = None,
) -> OpeningSignalReport:
    """Build an opening-signal report from ranked/enriched candidate files."""
    candidates = load_ranked_candidates(ranked_file)
    if top_n is not None:
        candidates = candidates[: max(0, top_n)]
    manual_records = load_manual_signal_records(manual_signals)
    assessments = [
        assess_candidate_opening_signal(candidate, manual_records)
        for candidate in candidates
    ]
    return OpeningSignalReport(
        generated_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
        ranked_file=str(ranked_file),
        manual_signals_file=str(manual_signals) if manual_signals else None,
        candidate_count=len(assessments),
        candidates=assessments,
        warnings=[],
        limitations=OPENING_SIGNAL_LIMITATIONS,
    )


def load_ranked_candidates(ranked_file: Path) -> list[RankedSupervisorCandidate]:
    """Load ranked candidates from ranked or enriched supervisor reports."""
    payload = yaml.safe_load(ranked_file.read_text(encoding="utf-8")) or {}
    if "ranked_candidates" in payload:
        return CandidateRankingReport.model_validate(payload).ranked_candidates
    if "candidates" in payload and payload["candidates"]:
        first = payload["candidates"][0]
        if isinstance(first, dict) and "ranked_candidate" in first:
            enriched = EnrichedCandidateReport.model_validate(payload)
            return [candidate.ranked_candidate for candidate in enriched.candidates]
    raise ValueError("Expected ranked_supervisors.json or enriched_supervisors.json.")


def load_manual_signal_records(path: Path | None) -> list[dict[str, Any]]:
    """Load optional manual snippets/URLs from YAML or CSV."""
    if path is None:
        return []
    if not path.exists():
        raise FileNotFoundError(path)
    if path.suffix.casefold() in {".yml", ".yaml"}:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if isinstance(payload, list):
            return [record for record in payload if isinstance(record, dict)]
        records = payload.get("signals", [])
        return [record for record in records if isinstance(record, dict)]
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def assess_candidate_opening_signal(
    candidate: RankedSupervisorCandidate,
    manual_records: list[dict[str, Any]],
) -> CandidateOpportunityAssessment:
    """Assess one candidate using deterministic manual-signal classification."""
    matched_records = _records_for_candidate(candidate, manual_records)
    generated_queries = generate_opening_search_queries(candidate)
    profile_urls = _dedupe(_urls_from_records(matched_records, "profile_url"))
    lab_urls = _dedupe(_urls_from_records(matched_records, "lab_url"))
    evidence = [
        classify_opening_signal(candidate, record, generated_queries)
        for record in matched_records
    ]
    best = _best_evidence(candidate, evidence, generated_queries)
    warnings = _dedupe([warning for item in evidence for warning in item.warnings])
    warnings.extend(warning for warning in best.warnings if warning not in warnings)
    return CandidateOpportunityAssessment(
        candidate_id=candidate.candidate_id,
        display_name=candidate.display_name,
        possible_affiliations=candidate.possible_affiliations,
        original_priority_label=candidate.priority_label,
        original_score=candidate.overall_score,
        generated_search_queries=generated_queries,
        profile_urls=profile_urls,
        lab_urls=lab_urls,
        opening_signal_type=best.opening_signal_type,
        opening_signal_strength=best.opening_signal_strength,
        confidence=best.confidence,
        source_url=best.source_url,
        evidence_snippet=best.evidence_snippet,
        source_query=best.source_query,
        opportunity_score_adjustment=best.opportunity_score_adjustment,
        suggested_next_manual_check=suggest_next_manual_check(best),
        warnings=warnings,
        evidence_items=best.evidence_items,
    )


def generate_opening_search_queries(candidate: RankedSupervisorCandidate) -> list[str]:
    """Generate deterministic manual web/profile search queries for a candidate."""
    name = candidate.display_name
    institution = (
        candidate.possible_affiliations[0]
        if candidate.possible_affiliations
        else "institution"
    )
    return [
        f'"{name}" "{institution}" lab',
        f'"{name}" "{institution}" postdoctoral fellow',
        f'"{name}" "postdoc opening"',
        f'"{name}" "positions available"',
        f'"{name}" "we are hiring"',
        f'"{name}" "prospective postdocs"',
    ]


def classify_opening_signal(
    candidate: RankedSupervisorCandidate,
    record: dict[str, Any],
    generated_queries: list[str] | None = None,
) -> OpeningSignalEvidence:
    """Classify a manual snippet/URL into a conservative opening signal."""
    generated_queries = generated_queries or generate_opening_search_queries(candidate)
    snippet = str(
        record.get("evidence_snippet")
        or record.get("snippet")
        or record.get("text")
        or record.get("manual_note")
        or ""
    ).strip()
    source_url = str(record.get("source_url") or record.get("url") or "").strip() or None
    source_query = str(record.get("source_query") or generated_queries[0]).strip()
    normalized = snippet.casefold()
    forced_type = str(record.get("opening_signal_type") or "").strip()

    if forced_type:
        signal_type = forced_type  # type: ignore[assignment]
        strength, adjustment, confidence = _signal_defaults(signal_type)
        warnings = _signal_warnings(signal_type, normalized)
    else:
        signal_type, strength, adjustment, confidence, warnings = _classify_text(normalized)

    evidence_items = []
    if snippet or source_url:
        evidence_items.append(
            EvidenceItem(
                evidence_id=(
                    f"opening:{candidate.candidate_id}:"
                    f"{_stable_suffix(snippet, source_url)}"
                ),
                source_type="lab_page" if source_url else "manual_note",
                title=f"Opening signal for {candidate.display_name}",
                url=source_url,
                source_name="manual opening signal",
                quoted_or_paraphrased_evidence=snippet,
                relevance_domains=candidate.inferred_domains,
                note="Manual opening-signal evidence; verify before outreach.",
                confidence=confidence,
            )
        )
    return OpeningSignalEvidence(
        candidate_id=candidate.candidate_id,
        display_name=candidate.display_name,
        opening_signal_type=signal_type,
        opening_signal_strength=strength,
        confidence=confidence,
        source_url=source_url,
        evidence_snippet=snippet,
        source_query=source_query,
        opportunity_score_adjustment=adjustment,
        warnings=warnings,
        evidence_items=evidence_items,
    )


def write_opening_signal_reports(
    report: OpeningSignalReport,
    output_dir: Path,
    output_format: str = "all",
) -> list[Path]:
    """Write opening-signal report outputs."""
    output_format = output_format.casefold()
    if output_format not in {"json", "md", "csv", "all"}:
        raise ValueError("output_format must be one of: json, md, csv, all")
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    if output_format in {"json", "all"}:
        paths.append(write_opening_signal_json(report, output_dir))
    if output_format in {"md", "all"}:
        paths.append(write_opening_signal_markdown(report, output_dir))
    if output_format in {"csv", "all"}:
        paths.append(write_opening_signal_csv(report, output_dir))
    return paths


def write_opening_signal_json(report: OpeningSignalReport, output_dir: Path) -> Path:
    """Write opening signals JSON."""
    output_path = output_dir / "opening_signals.json"
    output_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return output_path


def write_opening_signal_markdown(report: OpeningSignalReport, output_dir: Path) -> Path:
    """Write opening signals Markdown."""
    output_path = output_dir / "opening_signals.md"
    lines = [
        "# Opening Signal Report",
        "",
        f"- Generated at: {report.generated_at}",
        f"- Ranked file: {report.ranked_file}",
        f"- Manual signals file: {report.manual_signals_file or 'None'}",
        f"- Candidates assessed: {report.candidate_count}",
        "",
        "## Candidate Signals",
        "",
        "| Candidate | Priority | Score | Signal | Strength | Confidence | Adjustment |",
        "| --- | --- | ---: | --- | --- | ---: | ---: |",
    ]
    for candidate in report.candidates:
        lines.append(
            f"| {candidate.display_name} | {candidate.original_priority_label} | "
            f"{candidate.original_score:.3f} | {candidate.opening_signal_type} | "
            f"{candidate.opening_signal_strength} | {candidate.confidence:.2f} | "
            f"{candidate.opportunity_score_adjustment:.2f} |"
        )
    lines.extend(["", "## Candidate Details", ""])
    for candidate in report.candidates:
        lines.extend(
            [
                f"### {candidate.display_name}",
                "",
                f"- Candidate ID: `{candidate.candidate_id}`",
                f"- Possible affiliations: {', '.join(candidate.possible_affiliations) or 'None'}",
                f"- Opening signal type: {candidate.opening_signal_type}",
                f"- Opening signal strength: {candidate.opening_signal_strength}",
                f"- Confidence: {candidate.confidence:.2f}",
                f"- Source URL: {candidate.source_url or 'None'}",
                f"- Evidence snippet: {candidate.evidence_snippet or 'None'}",
                f"- Source query: {candidate.source_query or 'None'}",
                f"- Opportunity score adjustment: {candidate.opportunity_score_adjustment:.2f}",
                f"- Suggested next manual check: {candidate.suggested_next_manual_check}",
                "- Generated search queries:",
            ]
        )
        lines.extend(f"  - `{query}`" for query in candidate.generated_search_queries)
        lines.extend(["- Warnings:"])
        lines.extend(f"  - {warning}" for warning in candidate.warnings or ["None"])
        lines.append("")
    lines.extend(["## Limitations", ""])
    lines.extend(f"- {limitation}" for limitation in report.limitations)
    lines.append("")
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


def write_opening_signal_csv(report: OpeningSignalReport, output_dir: Path) -> Path:
    """Write opening signals CSV."""
    output_path = output_dir / "opening_signals.csv"
    fieldnames = [
        "candidate_id",
        "display_name",
        "possible_affiliations",
        "original_priority_label",
        "original_score",
        "opening_signal_type",
        "opening_signal_strength",
        "confidence",
        "source_url",
        "evidence_snippet",
        "source_query",
        "opportunity_score_adjustment",
        "suggested_next_manual_check",
        "warnings",
    ]
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for candidate in report.candidates:
            writer.writerow(
                {
                    "candidate_id": candidate.candidate_id,
                    "display_name": candidate.display_name,
                    "possible_affiliations": "; ".join(candidate.possible_affiliations),
                    "original_priority_label": candidate.original_priority_label,
                    "original_score": f"{candidate.original_score:.3f}",
                    "opening_signal_type": candidate.opening_signal_type,
                    "opening_signal_strength": candidate.opening_signal_strength,
                    "confidence": f"{candidate.confidence:.2f}",
                    "source_url": candidate.source_url or "",
                    "evidence_snippet": candidate.evidence_snippet,
                    "source_query": candidate.source_query,
                    "opportunity_score_adjustment": f"{candidate.opportunity_score_adjustment:.2f}",
                    "suggested_next_manual_check": candidate.suggested_next_manual_check,
                    "warnings": "; ".join(candidate.warnings),
                }
            )
    return output_path


def suggest_next_manual_check(signal: OpeningSignalEvidence) -> str:
    """Suggest the next manual verification step."""
    if signal.opening_signal_type == "explicit_postdoc_opening":
        return "Open the source URL and verify the postdoc opening is current before outreach."
    if signal.opening_signal_type in {"lab_hiring_statement", "contact_for_positions"}:
        return "Review the lab/profile page for current position details and fit."
    if signal.opening_signal_type == "recent_grant_possible_hiring":
        return "Verify whether the recent funding corresponds to active hiring."
    if signal.opening_signal_type == "outdated_signal":
        return "Check whether the opportunity page has a newer current version."
    if signal.opening_signal_type == "mismatch_signal":
        return "Confirm whether the opportunity is relevant to translational digital medicine."
    return "Search lab/profile pages manually for current openings or contact guidance."


def _classify_text(
    text: str,
) -> tuple[
    OpeningSignalType,
    OpeningSignalStrength,
    float,
    float,
    list[str],
]:
    if not text:
        return "no_signal_found", "none", 0.0, 0.35, []
    if _contains_any(text, MISMATCH_PATTERNS):
        return (
            "mismatch_signal",
            "low",
            -0.10,
            0.75,
            ["Opening text appears mismatched for the target translational profile."],
        )
    if _is_outdated(text):
        return (
            "outdated_signal",
            "low",
            0.0,
            0.65,
            ["Opening-like signal appears outdated; verify current status."],
        )
    if _contains_any(text, EXPLICIT_POSTDOC_PATTERNS):
        return "explicit_postdoc_opening", "high", 0.35, 0.90, []
    if _contains_any(text, HIRING_PATTERNS):
        return "lab_hiring_statement", "medium", 0.25, 0.80, []
    if _contains_any(text, CONTACT_PATTERNS):
        return "contact_for_positions", "medium", 0.15, 0.75, []
    if _contains_any(text, RECENT_GRANT_PATTERNS):
        return "recent_grant_possible_hiring", "low", 0.10, 0.60, []
    return (
        "manual_note",
        "low",
        0.0,
        0.45,
        ["Manual evidence did not contain a clear opening signal."],
    )


def _signal_defaults(signal_type: str) -> tuple[OpeningSignalStrength, float, float]:
    if signal_type == "explicit_postdoc_opening":
        return "high", 0.35, 0.90
    if signal_type == "lab_hiring_statement":
        return "medium", 0.25, 0.80
    if signal_type == "contact_for_positions":
        return "medium", 0.15, 0.75
    if signal_type == "recent_grant_possible_hiring":
        return "low", 0.10, 0.60
    if signal_type == "mismatch_signal":
        return "low", -0.10, 0.75
    if signal_type == "outdated_signal":
        return "low", 0.0, 0.65
    if signal_type == "manual_note":
        return "low", 0.0, 0.45
    return "none", 0.0, 0.35


def _signal_warnings(signal_type: str, text: str) -> list[str]:
    warnings = []
    if signal_type == "outdated_signal" or _is_outdated(text):
        warnings.append("Opening-like signal appears outdated; verify current status.")
    if signal_type == "mismatch_signal":
        warnings.append("Opening text appears mismatched for the target translational profile.")
    return warnings


def _best_evidence(
    candidate: RankedSupervisorCandidate,
    evidence: list[OpeningSignalEvidence],
    generated_queries: list[str],
) -> OpeningSignalEvidence:
    if not evidence:
        return OpeningSignalEvidence(
            candidate_id=candidate.candidate_id,
            display_name=candidate.display_name,
            opening_signal_type="no_signal_found",
            opening_signal_strength="none",
            confidence=0.35,
            source_query=generated_queries[0],
            opportunity_score_adjustment=0.0,
        )
    strength_order = {"high": 3, "medium": 2, "low": 1, "none": 0}
    return sorted(
        evidence,
        key=lambda item: (
            strength_order[item.opening_signal_strength],
            item.confidence,
            item.opportunity_score_adjustment,
        ),
        reverse=True,
    )[0]


def _records_for_candidate(
    candidate: RankedSupervisorCandidate,
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    candidate_id = candidate.candidate_id.casefold()
    display_name = candidate.display_name.casefold()
    return [
        record
        for record in records
        if str(record.get("candidate_id", "")).casefold() == candidate_id
        or str(record.get("display_name", "")).casefold() == display_name
        or str(record.get("candidate_name", "")).casefold() == display_name
    ]


def _urls_from_records(records: list[dict[str, Any]], key: str) -> list[str]:
    urls = []
    for record in records:
        value = str(record.get(key) or "").strip()
        if value:
            urls.append(value)
    return urls


def _contains_any(text: str, patterns: list[str]) -> bool:
    return any(pattern in text for pattern in patterns)


def _is_outdated(text: str) -> bool:
    current_year = datetime.now(UTC).year
    years = [int(year) for year in re.findall(r"\b20\d{2}\b", text)]
    has_opening_language = _contains_any(
        text,
        [*EXPLICIT_POSTDOC_PATTERNS, *HIRING_PATTERNS, *CONTACT_PATTERNS],
    )
    return has_opening_language and bool(years) and max(years) < current_year - 2


def _dedupe(values: list[str]) -> list[str]:
    deduped = []
    seen = set()
    for value in values:
        normalized = value.casefold().strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            deduped.append(value)
    return deduped


def _stable_suffix(snippet: str, source_url: str | None) -> str:
    digest = hashlib.sha1(f"{snippet}|{source_url or ''}".encode()).hexdigest()
    return digest[:10]
