from pathlib import Path

from postdoc_scout.dashboard_utils import (
    available_downloads,
    build_queries_for_dashboard,
    candidate_score_rows,
    queries_by_source,
    report_markdown_options,
    resolve_dashboard_output_dir,
    run_dashboard_pipeline,
    safe_load_markdown,
    score_breakdown_rows,
    score_mock_candidates_for_dashboard,
)


def test_resolve_dashboard_output_dir_accepts_string_path(tmp_path) -> None:
    output_dir = resolve_dashboard_output_dir(str(tmp_path / "dashboard"))

    assert output_dir == tmp_path / "dashboard"


def test_safe_load_markdown_returns_placeholder_for_missing_file(tmp_path) -> None:
    missing_path = tmp_path / "missing.md"

    assert "No report found" in safe_load_markdown(missing_path)


def test_safe_load_markdown_reads_existing_file(tmp_path) -> None:
    report_path = tmp_path / "pipeline_summary.md"
    report_path.write_text("# Demo report", encoding="utf-8")

    assert safe_load_markdown(report_path) == "# Demo report"


def test_report_markdown_options_and_downloads_only_include_existing_files(tmp_path) -> None:
    (tmp_path / "ecosystem.md").write_text("# Ecosystem", encoding="utf-8")
    (tmp_path / "ranked_supervisors.csv").write_text("rank,name\n1,Demo", encoding="utf-8")

    markdown_options = report_markdown_options(tmp_path)
    downloads = available_downloads(tmp_path)

    assert markdown_options == {"Ecosystem map": tmp_path / "ecosystem.md"}
    assert tmp_path / "ecosystem.md" in downloads
    assert tmp_path / "ranked_supervisors.csv" in downloads
    assert tmp_path / "pipeline_summary.md" not in downloads


def test_build_queries_for_dashboard_groups_queries_by_source() -> None:
    bundle = build_queries_for_dashboard(
        institution="Harvard University",
        mode="broad",
        country="us",
        limit=12,
    )
    grouped = queries_by_source(bundle)

    assert bundle.queries
    assert "pubmed" in grouped
    assert "openalex" in grouped
    assert all("query" in row for rows in grouped.values() for row in rows)


def test_mock_candidate_score_table_generation() -> None:
    ranked = score_mock_candidates_for_dashboard(Path("examples/mock_candidates.yml"))
    rows = candidate_score_rows(ranked)
    first_candidate = rows[0]["candidate name"]
    breakdown = score_breakdown_rows(ranked, first_candidate)

    assert rows[0]["rank"] == 1
    assert rows[0]["overall score"] > 0
    assert "method-heavy penalty" in rows[0]
    assert breakdown
    assert "dimension" in breakdown[0]


def test_dashboard_dry_pipeline_writes_reports_without_network(tmp_path, monkeypatch) -> None:
    def fail_if_called(**kwargs: object):
        raise AssertionError("dry dashboard pipeline should not collect external evidence")

    monkeypatch.setattr(
        "postdoc_scout.pipeline.collect_evidence_from_query_file",
        fail_if_called,
    )

    report = run_dashboard_pipeline(
        institution="Harvard University",
        mode="broad",
        country="us",
        output_dir=tmp_path,
        dry_run=True,
        limit_queries=5,
        limit_per_source=0,
    )

    assert report.dry_run
    assert (tmp_path / "ecosystem.md").exists()
    assert (tmp_path / "discovery_queries.md").exists()
    assert (tmp_path / "pipeline_summary.md").exists()
    assert not (tmp_path / "evidence_collection.md").exists()

