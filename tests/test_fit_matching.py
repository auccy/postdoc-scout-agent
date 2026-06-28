from pathlib import Path

from typer.testing import CliRunner

from postdoc_scout.candidate_ranker import rank_candidates_from_files
from postdoc_scout.cli import app
from postdoc_scout.fit_matching import build_fit_matching_report, load_user_profile
from postdoc_scout.models import CandidateOpportunityAssessment, OpeningSignalReport

FIXTURE_CANDIDATE_FILE = Path("tests/fixtures/candidate_extraction_ranking_mock.json")
FIXTURE_EVIDENCE_FILE = Path("tests/fixtures/evidence_collection_mock.json")
EXAMPLE_PROFILE = Path("examples/user_profile.example.yml")


def test_load_user_profile() -> None:
    profile = load_user_profile(EXAMPLE_PROFILE)

    assert profile.name == "Example Researcher"
    assert "clinical AI" in profile.preferred_domains
    assert profile.avoid_directions["pure_algorithm_architecture"] is True


def test_fit_matching_produces_domain_data_translation_explanations(tmp_path) -> None:
    report = build_fit_matching_report(
        ranked_file=_ranked_file(tmp_path),
        user_profile_file=EXAMPLE_PROFILE,
    )
    top = report.candidates[0]
    dimensions = {dimension.name: dimension for dimension in top.dimensions}

    assert top.display_name == "Nora Senior"
    assert dimensions["domain_fit"].matched_terms
    assert dimensions["data_fit"].matched_terms
    assert dimensions["translational_fit"].matched_terms
    assert "preferred domain" in dimensions["domain_fit"].explanation
    assert "dataset or data-resource" in dimensions["data_fit"].explanation
    assert "translational strength" in dimensions["translational_fit"].explanation


def test_avoid_directions_penalty_flags_method_heavy_candidate(tmp_path) -> None:
    report = build_fit_matching_report(
        ranked_file=_ranked_file(tmp_path),
        user_profile_file=EXAMPLE_PROFILE,
    )
    by_name = {candidate.display_name: candidate for candidate in report.candidates}
    method_candidate = by_name["Victor Method"]
    nora = by_name["Nora Senior"]

    assert method_candidate.mismatch_warnings
    assert method_candidate.fit_score < nora.fit_score
    assert method_candidate.fit_priority in {"avoid_or_review", "low_fit", "possible_fit"}


def test_opportunity_signal_modifies_fit_assessment(tmp_path) -> None:
    ranked_file = _ranked_file(tmp_path)
    baseline = build_fit_matching_report(ranked_file, EXAMPLE_PROFILE)
    baseline_nora = _candidate_by_id(baseline.candidates, "cand_0001")
    _write_opening_signal_report(tmp_path, ranked_file)

    with_opening = build_fit_matching_report(ranked_file, EXAMPLE_PROFILE)
    opening_nora = _candidate_by_id(with_opening.candidates, "cand_0001")
    opportunity_dimension = {
        dimension.name: dimension for dimension in opening_nora.dimensions
    }["opportunity_fit"]

    assert opportunity_dimension.score > _dimension_score(baseline_nora, "opportunity_fit")
    assert "explicit_postdoc_opening" in opportunity_dimension.matched_terms
    assert "Opening-signal report" in opportunity_dimension.explanation


def test_fit_matching_outputs_do_not_include_email_or_contact_angle_content(tmp_path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "match-fit",
            "--ranked-file",
            str(_ranked_file(tmp_path)),
            "--user-profile",
            str(EXAMPLE_PROFILE),
            "--output-dir",
            str(tmp_path),
            "--format",
            "all",
        ],
    )
    output_text = (
        (tmp_path / "fit_assessments.json").read_text(encoding="utf-8")
        + (tmp_path / "fit_assessments.md").read_text(encoding="utf-8")
        + (tmp_path / "fit_assessments.csv").read_text(encoding="utf-8")
    ).casefold()

    assert result.exit_code == 0
    assert "cold email" not in output_text
    assert "contact angle" not in output_text
    assert "suggested_contact_angle" not in output_text


def test_fit_matching_cli_writes_markdown_json_csv(tmp_path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "match-fit",
            "--ranked-file",
            str(_ranked_file(tmp_path)),
            "--user-profile",
            str(EXAMPLE_PROFILE),
            "--output-dir",
            str(tmp_path),
            "--format",
            "all",
        ],
    )

    assert result.exit_code == 0
    assert (tmp_path / "fit_assessments.json").exists()
    assert (tmp_path / "fit_assessments.md").exists()
    assert (tmp_path / "fit_assessments.csv").exists()


def test_existing_scout_command_still_works() -> None:
    result = CliRunner().invoke(
        app,
        [
            "scout",
            "--institution",
            "Harvard Medical School",
            "--mode",
            "broad",
            "--limit",
            "20",
        ],
    )

    assert result.exit_code == 0


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


def _write_opening_signal_report(tmp_path: Path, ranked_file: Path) -> None:
    report = OpeningSignalReport(
        generated_at="2026-06-29T00:00:00+00:00",
        ranked_file=str(ranked_file),
        candidate_count=1,
        candidates=[
            CandidateOpportunityAssessment(
                candidate_id="cand_0001",
                display_name="Nora Senior",
                opening_signal_type="explicit_postdoc_opening",
                opening_signal_strength="high",
                evidence_snippet="The lab has an explicit postdoc opening in clinical AI.",
            )
        ],
    )
    (tmp_path / "opening_signals.json").write_text(
        report.model_dump_json(indent=2),
        encoding="utf-8",
    )


def _candidate_by_id(candidates, candidate_id: str):
    return next(candidate for candidate in candidates if candidate.candidate_id == candidate_id)


def _dimension_score(candidate, dimension_name: str) -> float:
    return next(
        dimension.score for dimension in candidate.dimensions if dimension.name == dimension_name
    )
