from pathlib import Path

from typer.testing import CliRunner

from postdoc_scout.candidate_ranker import rank_candidates_from_files
from postdoc_scout.cli import app
from postdoc_scout.models import Publication
from postdoc_scout.publication_calibration import (
    calculate_publication_impact_score,
    calibrate_candidate_publication_profile,
    classify_field_journal,
    classify_journal_tier,
    detect_consortium_or_group_authorship,
    detect_method_heavy_publication,
    normalize_journal_name,
    score_author_position,
    score_recency,
)

FIXTURE_CANDIDATE_FILE = Path("tests/fixtures/candidate_extraction_ranking_mock.json")
FIXTURE_EVIDENCE_FILE = Path("tests/fixtures/evidence_collection_mock.json")


def test_journal_normalization() -> None:
    assert normalize_journal_name("NeuroImage: Clinical") == "neuroimage clinical"
    assert normalize_journal_name("Alzheimer's & Dementia") == "alzheimer s and dementia"


def test_journal_tier_classification() -> None:
    classification = classify_journal_tier("Nature Medicine")

    assert classification.journal_tier == "flagship_subjournals"
    assert classification.field_basket == "flagship_subjournals"
    assert classification.configured_weight > 0.8


def test_field_basket_classification() -> None:
    assert classify_field_journal("npj Digital Medicine") == "field_leading_digital_medicine"
    assert classify_field_journal("Journal of Clinical Oncology") == "field_leading_oncology"


def test_author_position_weighting() -> None:
    senior = score_author_position("senior")
    middle = score_author_position("middle")

    assert senior.author_position_weight > middle.author_position_weight
    assert middle.warnings


def test_recency_weighting() -> None:
    assert score_recency(2026, current_year=2026) > score_recency(2018, current_year=2026)
    assert score_recency(None, current_year=2026) == 0.55


def test_middle_author_paper_scores_lower_than_senior_paper() -> None:
    senior = _publication(author_position="senior")
    middle = _publication(author_position="middle")

    senior_score = calculate_publication_impact_score(senior, "senior_pub")
    middle_score = calculate_publication_impact_score(middle, "middle_pub")

    assert senior_score.calibrated_score > middle_score.calibrated_score


def test_consortium_warning_detection() -> None:
    publication = _publication(
        title="Clinical AI Consortium study using EHR data",
        authors=["Clinical AI Consortium"],
    )

    assert "consortium" in detect_consortium_or_group_authorship(publication).casefold()


def test_pure_method_heavy_publication_warning() -> None:
    publication = _publication(
        title="Benchmark-only foundation model architecture",
        journal="NeurIPS",
        abstract="Optimization theory and simulation-only benchmark study.",
        relevance_domains=[],
    )

    warning = detect_method_heavy_publication(
        publication,
        "field_leading_methods_but_downweighted_if_pure",
    )

    assert "downweighted" in warning


def test_candidate_level_calibration() -> None:
    calibration = calibrate_candidate_publication_profile(
        candidate_id="cand_demo",
        display_name="Dr. Demo",
        publications=[
            _publication(author_position="senior"),
            _publication(author_position="middle", title="Benchmark-only consortium paper"),
        ],
    )

    assert calibration.publication_count == 2
    assert calibration.mean_calibrated_score > 0
    assert calibration.middle_author_count == 1


def test_calibrate_publications_cli_generates_outputs(tmp_path) -> None:
    ranked_file = _ranked_file(tmp_path)

    result = CliRunner().invoke(
        app,
        [
            "calibrate-publications",
            "--ranked-file",
            str(ranked_file),
            "--output-dir",
            str(tmp_path),
            "--format",
            "all",
        ],
    )

    assert result.exit_code == 0
    assert (tmp_path / "publication_calibration.json").exists()
    assert (tmp_path / "publication_calibration.md").exists()
    assert (tmp_path / "publication_calibration.csv").exists()


def test_ranking_uses_calibrated_publication_dimension() -> None:
    report = rank_candidates_from_files(
        candidate_file=FIXTURE_CANDIDATE_FILE,
        evidence_file=FIXTURE_EVIDENCE_FILE,
        institution="Harvard University",
        mode="broad",
    )
    top = report.ranked_candidates[0]
    dimensions = {dimension.name: dimension for dimension in top.score_breakdown.dimensions}

    assert "Calibrated with journal tier" in dimensions[
        "translational_publication_potential"
    ].explanation
    assert "Calibrated with publication recency" in dimensions[
        "recent_academic_impact"
    ].explanation


def _publication(
    title: str = "Clinical AI risk prediction using EHR data",
    journal: str = "npj Digital Medicine",
    author_position: str = "senior",
    year: int = 2025,
    abstract: str = "Clinical AI risk prediction using EHR real-world data.",
    relevance_domains: list[str] | None = None,
    authors: list[str] | None = None,
) -> Publication:
    return Publication(
        title=title,
        journal=journal,
        candidate_author_position=author_position,  # type: ignore[arg-type]
        year=year,
        abstract=abstract,
        relevance_domains=(
            ["clinical AI", "EHR/RWD"] if relevance_domains is None else relevance_domains
        ),
        authors=authors or ["First Author", "Demo Senior"],
    )


def _ranked_file(tmp_path: Path) -> Path:
    ranked = rank_candidates_from_files(
        candidate_file=FIXTURE_CANDIDATE_FILE,
        evidence_file=FIXTURE_EVIDENCE_FILE,
        institution="Harvard University",
        mode="broad",
    )
    ranked_file = tmp_path / "ranked_supervisors.json"
    ranked_file.write_text(ranked.model_dump_json(indent=2), encoding="utf-8")
    return ranked_file
