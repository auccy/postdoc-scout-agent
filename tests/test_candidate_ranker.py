from pathlib import Path

from typer.testing import CliRunner

from postdoc_scout.candidate_ranker import (
    cluster_to_supervisor_candidate,
    load_candidate_extraction_report,
    rank_candidates_from_files,
    suggested_contact_angle,
)
from postdoc_scout.cli import app

FIXTURE_CANDIDATE_FILE = Path("tests/fixtures/candidate_extraction_ranking_mock.json")
FIXTURE_EVIDENCE_FILE = Path("tests/fixtures/evidence_collection_mock.json")


def test_converts_candidate_cluster_to_supervisor_candidate() -> None:
    extraction = load_candidate_extraction_report(FIXTURE_CANDIDATE_FILE)
    cluster = extraction.candidate_clusters[0]

    supervisor = cluster_to_supervisor_candidate(cluster)

    assert supervisor.name == "Nora Senior"
    assert "Harvard Medical School" in supervisor.current_affiliations
    assert "clinical AI" in supervisor.domains
    assert supervisor.publications[0].candidate_author_position in {"senior", "corresponding"}


def test_ranks_candidates_by_overall_score() -> None:
    report = rank_candidates_from_files(
        candidate_file=FIXTURE_CANDIDATE_FILE,
        evidence_file=FIXTURE_EVIDENCE_FILE,
        institution="Harvard University",
        mode="broad",
    )

    assert report.ranked_candidates[0].display_name == "Nora Senior"
    assert report.ranked_candidates[0].overall_score >= report.ranked_candidates[1].overall_score
    assert report.ranked_candidates[0].rank == 1


def test_ranking_preserves_evidence_ids() -> None:
    report = rank_candidates_from_files(
        candidate_file=FIXTURE_CANDIDATE_FILE,
        evidence_file=FIXTURE_EVIDENCE_FILE,
        institution="Harvard University",
        mode="broad",
    )
    top = report.ranked_candidates[0]
    evidence_ids = {item.evidence_id for item in top.evidence_items}

    assert "fixture:openalex:1" in evidence_ids
    assert "fixture:pubmed:1" in evidence_ids
    assert any(
        "fixture:openalex:1" in dimension.supporting_evidence_ids
        for dimension in top.score_breakdown.dimensions
    )


def test_ranking_preserves_ambiguity_warnings() -> None:
    report = rank_candidates_from_files(
        candidate_file=FIXTURE_CANDIDATE_FILE,
        evidence_file=None,
        institution="Harvard University",
        mode="broad",
    )
    method_candidate = [
        candidate
        for candidate in report.ranked_candidates
        if candidate.display_name == "Victor Method"
    ][0]

    assert any("Method-heavy publication" in warning for warning in method_candidate.warnings)
    assert any(
        "Original evidence collection was not provided" in warning
        for warning in report.warnings
    )


def test_method_heavy_penalty_is_applied() -> None:
    report = rank_candidates_from_files(
        candidate_file=FIXTURE_CANDIDATE_FILE,
        evidence_file=FIXTURE_EVIDENCE_FILE,
        institution="Harvard University",
        mode="broad",
    )
    method_candidate = [
        candidate
        for candidate in report.ranked_candidates
        if candidate.display_name == "Victor Method"
    ][0]

    assert method_candidate.method_heavy_penalty_applied
    assert method_candidate.priority_label == "D"


def test_suggested_contact_angle_is_deterministic() -> None:
    adrd_angle = suggested_contact_angle(["AD/ADRD", "digital medicine", "clinical AI"])
    oncology_angle = suggested_contact_angle(["oncology", "digital medicine", "EHR/RWD"])
    ehr_angle = suggested_contact_angle(["EHR/RWD", "clinical decision support"])

    assert "dementia risk prediction" in adrd_angle
    assert "real-world patient stratification" in oncology_angle
    assert "clinically usable digital medicine tools" in ehr_angle


def test_rank_candidates_cli_generates_json_markdown_and_csv(tmp_path) -> None:
    result = CliRunner().invoke(
        app,
        [
            "rank-candidates",
            "--candidate-file",
            str(FIXTURE_CANDIDATE_FILE),
            "--evidence-file",
            str(FIXTURE_EVIDENCE_FILE),
            "--institution",
            "Harvard University",
            "--mode",
            "broad",
            "--output-dir",
            str(tmp_path),
            "--format",
            "all",
        ],
    )

    assert result.exit_code == 0
    assert "Ranked Supervisor Candidates" in result.output
    assert (tmp_path / "ranked_supervisors.json").exists()
    assert (tmp_path / "ranked_supervisors.md").exists()
    assert (tmp_path / "ranked_supervisors.csv").exists()
