from pathlib import Path

from typer.testing import CliRunner

from postdoc_scout.cli import app
from postdoc_scout.models import EvidenceCollection, PipelineConfig
from postdoc_scout.pipeline import run_pipeline

FIXTURE_EVIDENCE_FILE = Path("tests/fixtures/evidence_collection_mock.json")


def test_pipeline_dry_run_creates_map_and_queries_without_external_calls(
    tmp_path, monkeypatch
) -> None:
    def fail_if_called(**kwargs: object) -> EvidenceCollection:
        raise AssertionError("dry-run should not call external evidence collection")

    monkeypatch.setattr(
        "postdoc_scout.pipeline.collect_evidence_from_query_file",
        fail_if_called,
    )
    output_dir = tmp_path / "harvard"

    report = run_pipeline(
        PipelineConfig(
            institution="Harvard University",
            mode="broad",
            country="us",
            output_dir=str(output_dir),
            dry_run=True,
            limit_queries=10,
        )
    )

    assert report.dry_run
    assert (output_dir / "ecosystem.json").exists()
    assert (output_dir / "ecosystem.md").exists()
    assert (output_dir / "discovery_queries.json").exists()
    assert (output_dir / "discovery_queries.md").exists()
    assert (output_dir / "pipeline_run.json").exists()
    assert (output_dir / "pipeline_summary.md").exists()
    assert not (output_dir / "evidence_collection.json").exists()
    assert _stage_status(report, "evidence_collection") == "skipped"


def test_full_pipeline_works_with_mocked_evidence_collection(tmp_path, monkeypatch) -> None:
    def fake_collect_evidence_from_query_file(**kwargs: object) -> EvidenceCollection:
        return EvidenceCollection.model_validate_json(
            FIXTURE_EVIDENCE_FILE.read_text(encoding="utf-8")
        )

    monkeypatch.setattr(
        "postdoc_scout.pipeline.collect_evidence_from_query_file",
        fake_collect_evidence_from_query_file,
    )

    report = run_pipeline(
        PipelineConfig(
            institution="Harvard University",
            mode="broad",
            country="us",
            output_dir=str(tmp_path),
            enrichment_sources="manual",
            limit_queries=10,
            limit_per_source=2,
        )
    )

    assert _stage_status(report, "candidate_enrichment") == "completed"
    assert report.metrics["publications_retrieved"] == 2
    assert report.metrics["ranked_candidates"] >= 1
    assert (tmp_path / "candidate_extraction.json").exists()
    assert (tmp_path / "ranked_supervisors.json").exists()
    assert (tmp_path / "enriched_supervisors.json").exists()
    assert (tmp_path / "pipeline_summary.md").exists()


def test_pipeline_resume_reuses_existing_outputs(tmp_path) -> None:
    config = PipelineConfig(
        institution="Harvard University",
        mode="broad",
        country="us",
        output_dir=str(tmp_path),
        dry_run=True,
        limit_queries=5,
    )
    run_pipeline(config)

    report = run_pipeline(config)

    assert _stage_status(report, "institution_mapping") == "reused"
    assert _stage_status(report, "query_building") == "reused"
    assert _stage(report, "institution_mapping").reused_existing
    assert _stage(report, "query_building").reused_existing


def test_pipeline_no_resume_overwrites_outputs(tmp_path) -> None:
    config = PipelineConfig(
        institution="Harvard University",
        mode="broad",
        country="us",
        output_dir=str(tmp_path),
        dry_run=True,
        limit_queries=5,
    )
    run_pipeline(config)
    (tmp_path / "ecosystem.json").write_text("{not valid json", encoding="utf-8")
    (tmp_path / "discovery_queries.json").write_text("{not valid json", encoding="utf-8")

    report = run_pipeline(config.model_copy(update={"resume": False}))

    assert _stage_status(report, "institution_mapping") == "completed"
    assert _stage_status(report, "query_building") == "completed"
    assert (tmp_path / "ecosystem.json").read_text(encoding="utf-8").startswith("{")


def test_failed_stage_produces_structured_warning(tmp_path, monkeypatch) -> None:
    def fail_query_building(**kwargs: object):
        raise RuntimeError("synthetic query failure")

    monkeypatch.setattr("postdoc_scout.pipeline.build_query_bundle", fail_query_building)

    report = run_pipeline(
        PipelineConfig(
            institution="Harvard University",
            mode="broad",
            output_dir=str(tmp_path),
            dry_run=True,
        )
    )

    stage = _stage(report, "query_building")
    assert stage.status == "failed"
    assert any("synthetic query failure" in error for error in stage.errors)
    assert any("synthetic query failure" in warning for warning in report.warnings)


def test_skip_evidence_collection_works_when_evidence_file_exists(tmp_path) -> None:
    (tmp_path / "evidence_collection.json").write_text(
        FIXTURE_EVIDENCE_FILE.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    report = run_pipeline(
        PipelineConfig(
            institution="Harvard University",
            mode="broad",
            country="us",
            output_dir=str(tmp_path),
            skip_evidence_collection=True,
            enrichment_sources="manual",
            resume=False,
            limit_queries=10,
        )
    )

    assert _stage_status(report, "evidence_collection") == "reused"
    assert _stage(report, "evidence_collection").reused_existing
    assert (tmp_path / "ranked_supervisors.json").exists()


def test_skip_enrichment_still_produces_ranked_report(tmp_path, monkeypatch) -> None:
    def fake_collect_evidence_from_query_file(**kwargs: object) -> EvidenceCollection:
        return EvidenceCollection.model_validate_json(
            FIXTURE_EVIDENCE_FILE.read_text(encoding="utf-8")
        )

    monkeypatch.setattr(
        "postdoc_scout.pipeline.collect_evidence_from_query_file",
        fake_collect_evidence_from_query_file,
    )

    report = run_pipeline(
        PipelineConfig(
            institution="Harvard University",
            mode="broad",
            output_dir=str(tmp_path),
            skip_enrichment=True,
            limit_queries=10,
        )
    )

    assert _stage_status(report, "candidate_ranking") == "completed"
    assert _stage_status(report, "candidate_enrichment") == "skipped"
    assert (tmp_path / "ranked_supervisors.json").exists()
    assert not (tmp_path / "enriched_supervisors.json").exists()


def test_run_pipeline_cli_dry_run(tmp_path) -> None:
    result = CliRunner().invoke(
        app,
        [
            "run-pipeline",
            "--institution",
            "Harvard University",
            "--mode",
            "broad",
            "--country",
            "us",
            "--output-dir",
            str(tmp_path),
            "--dry-run",
            "--limit-queries",
            "5",
        ],
    )

    assert result.exit_code == 0
    assert "Postdoc Scout Pipeline" in result.output
    assert (tmp_path / "pipeline_summary.md").exists()


def _stage(report, name: str):
    return next(stage for stage in report.stages if stage.stage == name)


def _stage_status(report, name: str) -> str:
    return _stage(report, name).status
