from pathlib import Path

import yaml
from typer.testing import CliRunner

from postdoc_scout.candidate_ranker import rank_candidates_from_files
from postdoc_scout.cli import app
from postdoc_scout.opening_signals import (
    build_opening_signal_report,
    classify_opening_signal,
    detect_openings_from_file,
    generate_opening_search_queries,
    load_ranked_candidates,
)
from postdoc_scout.review_tracker import (
    export_shortlist,
    init_review_tracker,
    read_review_tracker,
    update_candidate_review,
)

FIXTURE_CANDIDATE_FILE = Path("tests/fixtures/candidate_extraction_ranking_mock.json")
FIXTURE_EVIDENCE_FILE = Path("tests/fixtures/evidence_collection_mock.json")


def test_explicit_postdoc_opening_detection(tmp_path) -> None:
    ranked_file = _ranked_file(tmp_path)
    candidate = load_ranked_candidates(ranked_file)[0]
    signal = classify_opening_signal(
        candidate,
        {
            "evidence_snippet": "The lab has a postdoctoral position available in clinical AI.",
            "source_url": "https://example.org/opening",
        },
        generate_opening_search_queries(candidate),
    )

    assert signal.opening_signal_type == "explicit_postdoc_opening"
    assert signal.opening_signal_strength == "high"
    assert signal.opportunity_score_adjustment > 0


def test_generic_hiring_statement_detection(tmp_path) -> None:
    ranked_file = _ranked_file(tmp_path)
    candidate = load_ranked_candidates(ranked_file)[0]
    signal = classify_opening_signal(
        candidate,
        {"evidence_snippet": "We are hiring motivated researchers to join our lab."},
    )

    assert signal.opening_signal_type == "lab_hiring_statement"
    assert signal.opening_signal_strength == "medium"


def test_outdated_signal_detection(tmp_path) -> None:
    ranked_file = _ranked_file(tmp_path)
    candidate = load_ranked_candidates(ranked_file)[0]
    signal = classify_opening_signal(
        candidate,
        {"evidence_snippet": "Postdoc opening for 2021 in clinical data science."},
    )

    assert signal.opening_signal_type == "outdated_signal"
    assert signal.warnings


def test_mismatch_signal_detection(tmp_path) -> None:
    ranked_file = _ranked_file(tmp_path)
    candidate = load_ranked_candidates(ranked_file)[0]
    signal = classify_opening_signal(
        candidate,
        {"evidence_snippet": "Clinical fellowship only; wet-lab only experience required."},
    )

    assert signal.opening_signal_type == "mismatch_signal"
    assert signal.opportunity_score_adjustment < 0


def test_no_signal_does_not_crash(tmp_path) -> None:
    ranked_file = _ranked_file(tmp_path)
    report = build_opening_signal_report(ranked_file)

    assert report.candidates
    assert report.candidates[0].opening_signal_type == "no_signal_found"
    assert report.candidates[0].opening_signal_strength == "none"


def test_opening_signal_reports_are_written(tmp_path) -> None:
    ranked_file = _ranked_file(tmp_path)
    manual_file = tmp_path / "manual_signals.yml"
    manual_file.write_text(
        yaml.safe_dump(
            {
                "signals": [
                    {
                        "candidate_id": "cand_0001",
                        "evidence_snippet": "Prospective postdocs should contact the lab.",
                        "source_url": "https://example.org/lab",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    report, paths = detect_openings_from_file(
        ranked_file=ranked_file,
        manual_signals=manual_file,
        output_dir=tmp_path,
        output_format="all",
    )

    assert report.candidates[0].opening_signal_type == "contact_for_positions"
    assert tmp_path / "opening_signals.json" in paths
    assert (tmp_path / "opening_signals.md").exists()
    assert (tmp_path / "opening_signals.csv").exists()


def test_init_review_tracker_update_candidate_and_export_shortlist(tmp_path) -> None:
    ranked_file = _ranked_file(tmp_path)
    tracker = tmp_path / "review_tracker.csv"
    shortlist = tmp_path / "shortlist.csv"

    init_review_tracker(ranked_file=ranked_file, output=tracker)
    updated = update_candidate_review(
        tracker=tracker,
        candidate_id="cand_0001",
        review_status="interested",
        outreach_status="not_contacted",
        note="Strong digital medicine fit",
    )
    report = export_shortlist(tracker=tracker, status="interested", output=shortlist)
    rows = read_review_tracker(shortlist)

    assert updated.review_status == "interested"
    assert "Strong digital medicine fit" in updated.user_notes
    assert report.candidate_count == 1
    assert rows[0].candidate_id == "cand_0001"


def test_opening_and_review_cli_commands(tmp_path) -> None:
    ranked_file = _ranked_file(tmp_path)
    manual_file = tmp_path / "manual_signals.csv"
    manual_file.write_text(
        "candidate_id,evidence_snippet,source_url\n"
        "cand_0001,The lab has a postdoc opening in EHR AI,https://example.org/opening\n",
        encoding="utf-8",
    )
    runner = CliRunner()

    detect_result = runner.invoke(
        app,
        [
            "detect-openings",
            "--ranked-file",
            str(ranked_file),
            "--manual-signals",
            str(manual_file),
            "--output-dir",
            str(tmp_path),
            "--format",
            "all",
        ],
    )
    init_result = runner.invoke(
        app,
        [
            "init-review-tracker",
            "--ranked-file",
            str(ranked_file),
            "--output",
            str(tmp_path / "review_tracker.csv"),
            "--opening-signals-file",
            str(tmp_path / "opening_signals.json"),
        ],
    )
    update_result = runner.invoke(
        app,
        [
            "review-candidate",
            "--tracker",
            str(tmp_path / "review_tracker.csv"),
            "--candidate-id",
            "cand_0001",
            "--review-status",
            "interested",
            "--outreach-status",
            "not_contacted",
            "--note",
            "Strong translational fit",
        ],
    )
    export_result = runner.invoke(
        app,
        [
            "export-shortlist",
            "--tracker",
            str(tmp_path / "review_tracker.csv"),
            "--status",
            "interested",
            "--output",
            str(tmp_path / "shortlist.csv"),
        ],
    )

    assert detect_result.exit_code == 0
    assert init_result.exit_code == 0
    assert update_result.exit_code == 0
    assert export_result.exit_code == 0
    assert (tmp_path / "opening_signals.json").exists()
    assert (tmp_path / "review_tracker.csv").exists()
    assert (tmp_path / "shortlist.csv").exists()


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

