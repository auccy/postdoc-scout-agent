"""Deterministic publication impact calibration for ranked supervisor candidates."""

import csv
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from postdoc_scout.models import (
    AuthorPosition,
    AuthorshipCalibration,
    CandidateCluster,
    CandidateExtractionReport,
    CandidatePublicationCalibration,
    CandidateRankingReport,
    JournalClassification,
    Publication,
    PublicationCalibrationReport,
    PublicationImpactScore,
)

CALIBRATION_LIMITATIONS = [
    "Journal baskets are configured scouting heuristics, not live impact-factor claims.",
    "Publication calibration does not verify author identity or current affiliation.",
    "Scores should be interpreted with domain fit, data richness, and human review.",
    "Pure method-heavy venues are downweighted only when clinical translation is unclear.",
]

CLINICAL_DOMAIN_TERMS = {
    "ad/adrd",
    "aging",
    "biomedical ai",
    "biomedical informatics",
    "clinical ai",
    "clinical decision support",
    "cohort data",
    "digital medicine",
    "ehr/rwd",
    "oncology",
    "patient stratification",
    "progression modeling",
    "public health",
    "real-world data",
    "risk prediction",
    "trial enrichment",
}

METHOD_HEAVY_TERMS = {
    "algorithm",
    "benchmark-only",
    "foundation model architecture",
    "methodology",
    "optimization theory",
    "simulation-only",
    "statistical theory",
}

CONSORTIUM_TERMS = ["consortium", "study group", "working group", "collaboration"]


def normalize_journal_name(journal: str) -> str:
    """Normalize journal names for configured basket matching."""
    normalized = journal.casefold().replace("&", "and")
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return " ".join(normalized.split())


def classify_journal_tier(
    journal: str,
    config_path: Path = Path("configs/journal_tiers.yml"),
) -> JournalClassification:
    """Classify a journal into a configured journal tier and field basket."""
    normalized = normalize_journal_name(journal)
    baskets = _load_journal_baskets(config_path)
    for basket_name, basket in baskets.items():
        examples = basket.get("examples", [])
        normalized_examples = {normalize_journal_name(str(example)) for example in examples}
        if normalized in normalized_examples:
            journal_tier = _journal_tier_from_basket(basket_name)
            return JournalClassification(
                journal=journal,
                normalized_journal=normalized,
                journal_tier=journal_tier,
                field_basket=classify_field_journal(journal, config_path),
                configured_weight=float(basket.get("weight", 0.45)),
                explanation=f"Matched configured journal basket `{basket_name}`.",
            )
    return JournalClassification(
        journal=journal,
        normalized_journal=normalized,
        journal_tier="other",
        field_basket="other",
        configured_weight=0.45,
        explanation="Journal was not found in configured baskets.",
    )


def classify_field_journal(
    journal: str,
    config_path: Path = Path("configs/journal_tiers.yml"),
) -> str:
    """Return the configured field-specific basket for a journal, if any."""
    normalized = normalize_journal_name(journal)
    baskets = _load_journal_baskets(config_path)
    for basket_name, basket in baskets.items():
        normalized_examples = {
            normalize_journal_name(str(example)) for example in basket.get("examples", [])
        }
        if normalized in normalized_examples:
            if basket_name.startswith("field_leading_"):
                return basket_name
            return basket_name
    return "other"


def score_author_position(author_position: AuthorPosition) -> AuthorshipCalibration:
    """Score candidate author position for publication calibration."""
    weights = {
        "senior": 1.0,
        "corresponding": 1.0,
        "last": 0.95,
        "first": 0.85,
        "co_first": 0.85,
        "middle": 0.35,
        "unknown": 0.55,
    }
    explanations = {
        "senior": "Senior-author role is weighted strongly for supervisor scouting.",
        "corresponding": "Corresponding-author role is weighted strongly.",
        "last": "Last-author role is treated as senior-style evidence.",
        "first": "First-author role is valuable but less supervisor-specific.",
        "co_first": "Co-first role is valuable but less supervisor-specific.",
        "middle": "Middle-author role is downweighted to avoid publication-count inflation.",
        "unknown": "Unknown author position receives a conservative neutral weight.",
    }
    warnings = (
        ["Middle-author paper is downweighted relative to senior/corresponding roles."]
        if author_position == "middle"
        else []
    )
    return AuthorshipCalibration(
        author_position=author_position,
        author_position_weight=weights.get(author_position, 0.55),
        explanation=explanations.get(author_position, explanations["unknown"]),
        warnings=warnings,
    )


def score_recency(year: int | None, current_year: int | None = None) -> float:
    """Return a deterministic recency weight."""
    if year is None:
        return 0.55
    current_year = current_year or datetime.now(UTC).year
    age = max(0, current_year - year)
    if age <= 2:
        return 1.0
    if age <= 5:
        return 0.82
    if age <= 10:
        return 0.62
    return 0.38


def score_article_type(publication: Publication) -> float:
    """Score article type from title/abstract text without external metadata."""
    text = f"{publication.title} {publication.abstract}".casefold()
    if any(term in text for term in ["clinical trial", "prospective cohort", "registry"]):
        return 1.0
    if any(term in text for term in ["prediction", "decision support", "real-world"]):
        return 0.90
    if any(term in text for term in ["systematic review", "meta-analysis", "review"]):
        return 0.62
    if any(term in text for term in ["editorial", "commentary", "letter"]):
        return 0.35
    return 0.70


def detect_consortium_or_group_authorship(publication: Publication) -> str:
    """Detect consortium/group authorship warning from title and author strings."""
    text = " ".join([publication.title, *publication.authors]).casefold()
    if any(term in text for term in CONSORTIUM_TERMS):
        return "Possible consortium/group authorship; verify candidate role manually."
    if len(publication.authors) >= 25:
        return "Large author list may inflate middle-author evidence."
    return ""


def detect_method_heavy_publication(publication: Publication, field_basket: str) -> str:
    """Detect method-heavy publication evidence that lacks clinical translation signals."""
    text = " ".join(
        [
            publication.title,
            publication.abstract,
            publication.journal,
            " ".join(publication.relevance_domains),
        ]
    ).casefold()
    has_method_signal = (
        field_basket == "field_leading_methods_but_downweighted_if_pure"
        or any(term in text for term in METHOD_HEAVY_TERMS)
    )
    has_translation_signal = any(term in text for term in CLINICAL_DOMAIN_TERMS)
    if has_method_signal and not has_translation_signal:
        return (
            "Pure method-heavy publication is downweighted without clinical translation "
            "evidence."
        )
    return ""


def calculate_publication_impact_score(
    publication: Publication,
    publication_id: str,
    config_path: Path = Path("configs/journal_tiers.yml"),
) -> PublicationImpactScore:
    """Calculate a calibrated 0-5 publication impact score."""
    journal = classify_journal_tier(publication.journal, config_path)
    authorship = score_author_position(publication.candidate_author_position)
    recency_weight = score_recency(publication.year)
    domain_weight = _domain_relevance_weight(publication)
    article_type_weight = score_article_type(publication)
    consortium_warning = detect_consortium_or_group_authorship(publication)
    method_warning = detect_method_heavy_publication(publication, journal.field_basket)
    base_score = 5.0 * (
        0.34 * journal.configured_weight
        + 0.26 * authorship.author_position_weight
        + 0.18 * recency_weight
        + 0.14 * domain_weight
        + 0.08 * article_type_weight
    )
    if consortium_warning and publication.candidate_author_position == "middle":
        base_score -= 0.35
    if method_warning:
        base_score -= 0.45
    calibrated_score = round(max(0.0, min(5.0, base_score)), 3)
    return PublicationImpactScore(
        publication_id=publication_id,
        title=publication.title,
        year=publication.year,
        journal=publication.journal,
        journal_tier=journal.journal_tier,
        field_basket=journal.field_basket,
        author_position=publication.candidate_author_position,
        author_position_weight=authorship.author_position_weight,
        recency_weight=recency_weight,
        domain_relevance_weight=domain_weight,
        article_type_weight=article_type_weight,
        consortium_warning=consortium_warning,
        method_heavy_warning=method_warning,
        calibrated_score=calibrated_score,
        explanation=(
            f"Score combines journal basket ({journal.field_basket}), author role "
            f"({publication.candidate_author_position}), recency, domain relevance, "
            "and article type."
        ),
    )


def calibrate_candidate_publication_profile(
    candidate_id: str,
    display_name: str,
    publications: list[Publication],
    config_path: Path = Path("configs/journal_tiers.yml"),
) -> CandidatePublicationCalibration:
    """Calibrate all publications for one candidate."""
    scores = [
        calculate_publication_impact_score(
            publication=publication,
            publication_id=_publication_id(candidate_id, publication, index),
            config_path=config_path,
        )
        for index, publication in enumerate(publications, start=1)
    ]
    warnings = _candidate_warnings(scores)
    return CandidatePublicationCalibration(
        candidate_id=candidate_id,
        display_name=display_name,
        publication_count=len(scores),
        mean_calibrated_score=round(
            sum(score.calibrated_score for score in scores) / len(scores), 3
        )
        if scores
        else 0.0,
        max_calibrated_score=max((score.calibrated_score for score in scores), default=0.0),
        senior_or_corresponding_count=sum(
            score.author_position in {"senior", "corresponding", "last"} for score in scores
        ),
        middle_author_count=sum(score.author_position == "middle" for score in scores),
        field_leading_count=sum(score.journal_tier != "other" for score in scores),
        method_heavy_count=sum(bool(score.method_heavy_warning) for score in scores),
        consortium_warning_count=sum(bool(score.consortium_warning) for score in scores),
        old_impact_only_warning=_old_impact_only(scores),
        warnings=warnings,
        publication_scores=scores,
    )


def calibrate_publications_from_ranked_file(
    ranked_file: Path,
    output_dir: Path,
    output_format: str = "all",
) -> tuple[PublicationCalibrationReport, list[Path]]:
    """Load a ranked report, calibrate source candidate publications, and write reports."""
    report = build_publication_calibration_report(ranked_file)
    return report, write_publication_calibration_reports(report, output_dir, output_format)


def build_publication_calibration_report(ranked_file: Path) -> PublicationCalibrationReport:
    """Build publication calibration report from a ranked supervisor report."""
    ranking = CandidateRankingReport.model_validate_json(ranked_file.read_text(encoding="utf-8"))
    candidate_file = _resolve_candidate_file(ranked_file, ranking.candidate_file)
    extraction = CandidateExtractionReport.model_validate_json(
        candidate_file.read_text(encoding="utf-8")
    )
    clusters_by_id = {cluster.candidate_id: cluster for cluster in extraction.candidate_clusters}
    calibrations = []
    warnings = []
    for ranked in ranking.ranked_candidates:
        cluster = clusters_by_id.get(ranked.candidate_id)
        if cluster is None:
            warnings.append(f"No candidate extraction cluster found for {ranked.candidate_id}.")
            calibrations.append(
                calibrate_candidate_publication_profile(
                    ranked.candidate_id,
                    ranked.display_name,
                    [],
                )
            )
            continue
        calibrations.append(_calibrate_cluster(cluster))
    return PublicationCalibrationReport(
        generated_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
        ranked_file=str(ranked_file),
        candidate_file=str(candidate_file),
        candidate_count=len(calibrations),
        candidates=calibrations,
        journal_tier_summary=dict(_journal_summary(calibrations)),
        author_position_summary=dict(_author_position_summary(calibrations)),
        warnings=warnings,
        limitations=CALIBRATION_LIMITATIONS,
    )


def write_publication_calibration_reports(
    report: PublicationCalibrationReport,
    output_dir: Path,
    output_format: str = "all",
) -> list[Path]:
    """Write publication calibration report outputs."""
    output_format = output_format.casefold()
    if output_format not in {"json", "md", "csv", "all"}:
        raise ValueError("output_format must be one of: json, md, csv, all")
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    if output_format in {"json", "all"}:
        paths.append(write_publication_calibration_json(report, output_dir))
    if output_format in {"md", "all"}:
        paths.append(write_publication_calibration_markdown(report, output_dir))
    if output_format in {"csv", "all"}:
        paths.append(write_publication_calibration_csv(report, output_dir))
    return paths


def write_publication_calibration_json(
    report: PublicationCalibrationReport,
    output_dir: Path,
) -> Path:
    """Write publication calibration JSON."""
    output_path = output_dir / "publication_calibration.json"
    output_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return output_path


def write_publication_calibration_markdown(
    report: PublicationCalibrationReport,
    output_dir: Path,
) -> Path:
    """Write publication calibration Markdown."""
    output_path = output_dir / "publication_calibration.md"
    lines = [
        "# Publication Calibration Report",
        "",
        f"- Generated at: {report.generated_at}",
        f"- Ranked file: {report.ranked_file}",
        f"- Candidate file: {report.candidate_file or 'None'}",
        f"- Candidates calibrated: {report.candidate_count}",
        "",
        "## Journal Tier Summary",
        "",
    ]
    lines.extend(f"- {tier}: {count}" for tier, count in report.journal_tier_summary.items())
    if not report.journal_tier_summary:
        lines.append("- None")
    lines.extend(["", "## Author Position Summary", ""])
    lines.extend(
        f"- {position}: {count}" for position, count in report.author_position_summary.items()
    )
    if not report.author_position_summary:
        lines.append("- None")
    lines.extend(
        [
            "",
            "## Candidate-Level Calibrated Publication Impact",
            "",
            "| Candidate | Publications | Mean Score | Max Score | "
            "Senior/Corresponding | Warnings |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for candidate in report.candidates:
        lines.append(
            f"| {candidate.display_name} | {candidate.publication_count} | "
            f"{candidate.mean_calibrated_score:.3f} | {candidate.max_calibrated_score:.3f} | "
            f"{candidate.senior_or_corresponding_count} | {len(candidate.warnings)} |"
        )
    lines.extend(["", "## Candidate Details", ""])
    for candidate in report.candidates:
        lines.extend(_candidate_markdown_lines(candidate))
    lines.extend(
        [
            "## Why Calibration Differs From Raw Publication Counts",
            "",
            "- Senior/corresponding roles count more than middle-author roles.",
            "- Recent clinically relevant publications count more than old isolated impact.",
            "- Field-leading disease and digital medicine journals are handled by "
            "configured baskets.",
            "- Pure method-heavy journals are treated conservatively without clinical translation.",
            "- Consortium-heavy profiles receive warnings because author contribution may "
            "be unclear.",
            "",
            "## Limitations",
            "",
        ]
    )
    lines.extend(f"- {limitation}" for limitation in report.limitations)
    lines.append("")
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


def write_publication_calibration_csv(
    report: PublicationCalibrationReport,
    output_dir: Path,
) -> Path:
    """Write publication calibration CSV with one row per publication."""
    output_path = output_dir / "publication_calibration.csv"
    fieldnames = [
        "candidate_id",
        "display_name",
        "publication_id",
        "title",
        "year",
        "journal",
        "journal_tier",
        "field_basket",
        "author_position",
        "author_position_weight",
        "recency_weight",
        "domain_relevance_weight",
        "article_type_weight",
        "calibrated_score",
        "consortium_warning",
        "method_heavy_warning",
    ]
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for candidate in report.candidates:
            for score in candidate.publication_scores:
                writer.writerow(
                    {
                        "candidate_id": candidate.candidate_id,
                        "display_name": candidate.display_name,
                        "publication_id": score.publication_id,
                        "title": score.title,
                        "year": score.year or "",
                        "journal": score.journal,
                        "journal_tier": score.journal_tier,
                        "field_basket": score.field_basket,
                        "author_position": score.author_position,
                        "author_position_weight": f"{score.author_position_weight:.2f}",
                        "recency_weight": f"{score.recency_weight:.2f}",
                        "domain_relevance_weight": f"{score.domain_relevance_weight:.2f}",
                        "article_type_weight": f"{score.article_type_weight:.2f}",
                        "calibrated_score": f"{score.calibrated_score:.3f}",
                        "consortium_warning": score.consortium_warning,
                        "method_heavy_warning": score.method_heavy_warning,
                    }
                )
    return output_path


def _calibrate_cluster(cluster: CandidateCluster) -> CandidatePublicationCalibration:
    return calibrate_candidate_publication_profile(
        candidate_id=cluster.candidate_id,
        display_name=cluster.display_name,
        publications=cluster.publications,
    )


def _domain_relevance_weight(publication: Publication) -> float:
    domains = {domain.casefold() for domain in publication.relevance_domains}
    if domains & CLINICAL_DOMAIN_TERMS:
        return 1.0
    text = f"{publication.title} {publication.abstract}".casefold()
    if any(term in text for term in CLINICAL_DOMAIN_TERMS):
        return 0.85
    if any(term in text for term in ["patient", "clinical", "cohort", "ehr"]):
        return 0.70
    return 0.45


def _publication_id(candidate_id: str, publication: Publication, index: int) -> str:
    if publication.doi:
        return f"{candidate_id}:doi:{publication.doi}"
    if publication.pmid:
        return f"{candidate_id}:pmid:{publication.pmid}"
    title_key = normalize_journal_name(publication.title)[:40].replace(" ", "_")
    return f"{candidate_id}:pub_{index:03d}:{title_key}"


def _candidate_warnings(scores: list[PublicationImpactScore]) -> list[str]:
    warnings = []
    if not scores:
        return ["No publications available for calibration."]
    if sum(score.author_position == "middle" for score in scores) > len(scores) / 2:
        warnings.append("middle-author-heavy profile")
    if sum(bool(score.consortium_warning) for score in scores) > len(scores) / 2:
        warnings.append("consortium-heavy profile")
    if any(score.method_heavy_warning for score in scores):
        warnings.append("method-heavy profile")
    if _old_impact_only(scores):
        warnings.append("old-impact-only profile")
    return warnings


def _old_impact_only(scores: list[PublicationImpactScore]) -> bool:
    impactful = [score for score in scores if score.calibrated_score >= 3.5]
    return bool(impactful) and all(score.recency_weight <= 0.62 for score in impactful)


def _journal_summary(calibrations: list[CandidatePublicationCalibration]) -> Counter[str]:
    return Counter(
        score.journal_tier
        for calibration in calibrations
        for score in calibration.publication_scores
    )


def _author_position_summary(calibrations: list[CandidatePublicationCalibration]) -> Counter[str]:
    return Counter(
        score.author_position
        for calibration in calibrations
        for score in calibration.publication_scores
    )


def _candidate_markdown_lines(candidate: CandidatePublicationCalibration) -> list[str]:
    lines = [
        f"### {candidate.display_name}",
        "",
        f"- Candidate ID: `{candidate.candidate_id}`",
        f"- Mean calibrated score: {candidate.mean_calibrated_score:.3f}",
        f"- Max calibrated score: {candidate.max_calibrated_score:.3f}",
        f"- Warnings: {', '.join(candidate.warnings) or 'None'}",
        "",
        "| Publication | Journal | Year | Position | Score | Warnings |",
        "| --- | --- | ---: | --- | ---: | --- |",
    ]
    for score in candidate.publication_scores:
        warnings = "; ".join(
            warning for warning in [score.consortium_warning, score.method_heavy_warning] if warning
        )
        lines.append(
            f"| {score.title} | {score.journal} | {score.year or ''} | "
            f"{score.author_position} | {score.calibrated_score:.3f} | "
            f"{warnings or 'None'} |"
        )
    if not candidate.publication_scores:
        lines.append("| None |  |  |  |  |  |")
    lines.append("")
    return lines


def _resolve_candidate_file(ranked_file: Path, candidate_file: str) -> Path:
    path = Path(candidate_file)
    if path.exists():
        return path
    candidate_relative_to_ranked = ranked_file.parent / candidate_file
    if candidate_relative_to_ranked.exists():
        return candidate_relative_to_ranked
    raise FileNotFoundError(f"Candidate extraction file not found: {candidate_file}")


def _journal_tier_from_basket(basket_name: str) -> str:
    if basket_name in {"top_general_medical", "top_science_nature_cell"}:
        return basket_name
    if basket_name == "flagship_subjournals":
        return "flagship_subjournals"
    if basket_name == "field_leading_methods_but_downweighted_if_pure":
        return "methods_but_downweighted_if_pure"
    if basket_name.startswith("field_leading_"):
        return "field_leading"
    return "other"


def _load_journal_baskets(config_path: Path) -> dict[str, dict[str, Any]]:
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return payload.get("journal_baskets") or payload.get("tiers") or {}
