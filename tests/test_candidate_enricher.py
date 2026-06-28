from pathlib import Path

import httpx
from typer.testing import CliRunner

from postdoc_scout.candidate_enricher import (
    enrich_ranked_candidates,
)
from postdoc_scout.candidate_ranker import rank_candidates_from_files
from postdoc_scout.cli import app
from postdoc_scout.connectors.nih_reporter import NIHReporterConnector
from postdoc_scout.connectors.semantic_scholar import SemanticScholarConnector
from postdoc_scout.models import (
    AuthorProfileEvidence,
    EnrichedCandidateReport,
    FundingEvidence,
)

FIXTURE_CANDIDATE_FILE = Path("tests/fixtures/candidate_extraction_ranking_mock.json")
FIXTURE_EVIDENCE_FILE = Path("tests/fixtures/evidence_collection_mock.json")


def test_semantic_scholar_connector_normalizes_mock_author_profile() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/graph/v1/author/search"
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "authorId": "123",
                        "name": "Nora Senior",
                        "url": "https://www.semanticscholar.org/author/123",
                        "affiliations": ["Harvard Medical School"],
                        "paperCount": 42,
                        "citationCount": 1000,
                        "hIndex": 17,
                        "fieldsOfStudy": ["Medicine", "Computer Science"],
                    }
                ]
            },
        )

    client = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="https://api.semanticscholar.org/graph/v1/",
    )
    connector = SemanticScholarConnector(client=client, delay_seconds=0)
    profiles = connector.search_author_profiles("Nora Senior", ["Harvard Medical School"])

    assert len(profiles) == 1
    assert profiles[0].author_id == "123"
    assert profiles[0].paper_count == 42
    assert profiles[0].confidence >= 0.8


def test_nih_reporter_connector_normalizes_mock_grant_record() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/projects/search"
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "project_num": "R01LM000001",
                        "project_title": "Clinical AI for EHR risk prediction",
                        "fiscal_year": 2024,
                        "principal_investigators": [{"full_name": "Nora Senior"}],
                        "organization": {"org_name": "Harvard Medical School"},
                        "agency_ic_admin": "NLM",
                        "project_detail_url": "https://reporter.nih.gov/project-details/1",
                        "abstract_text": "Clinical AI using electronic health records.",
                    }
                ]
            },
        )

    client = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="https://api.reporter.nih.gov/v2/",
    )
    connector = NIHReporterConnector(client=client, delay_seconds=0)
    grants = connector.search_projects("Nora Senior", ["Harvard Medical School"], 2021, 2026)

    assert len(grants) == 1
    assert grants[0].project_number == "R01LM000001"
    assert grants[0].role == "PI"
    assert "clinical AI" in grants[0].relevance_domains


def test_ambiguous_author_profile_matches_produce_warnings() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {"authorId": "1", "name": "Jordan Lee", "affiliations": ["A"]},
                    {"authorId": "2", "name": "Jordan Lee", "affiliations": ["B"]},
                ]
            },
        )

    client = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="https://api.semanticscholar.org/graph/v1/",
    )
    connector = SemanticScholarConnector(client=client, delay_seconds=0)
    profiles = connector.search_author_profiles("Jordan Lee", ["A"])

    assert len(profiles) == 2
    assert any("Multiple Semantic Scholar profiles" in warning for warning in profiles[0].warnings)


def test_candidate_enricher_preserves_original_ranking_fields() -> None:
    ranked = _ranked_report()
    report = enrich_ranked_candidates(
        ranked,
        ranked_file="fixture_ranked.json",
        sources="manual",
    )
    enriched = report.candidates[0]

    assert enriched.ranked_candidate.rank == ranked.ranked_candidates[0].rank
    assert enriched.ranked_candidate.overall_score == ranked.ranked_candidates[0].overall_score
    assert enriched.ranked_candidate.priority_label == ranked.ranked_candidates[0].priority_label


def test_funding_evidence_annotates_data_resource_strength() -> None:
    ranked = _ranked_report()
    report = enrich_ranked_candidates(
        ranked,
        ranked_file="fixture_ranked.json",
        sources="nih_reporter",
        nih_reporter=FakeNIHReporter(),
    )
    enriched = report.candidates[0]

    assert enriched.enrichment.nih_reporter_grants
    assert enriched.enrichment_adjusted_score > enriched.ranked_candidate.overall_score
    assert any("data_resource_strength" in note for note in enriched.enrichment_notes)


def test_missing_connector_results_do_not_crash() -> None:
    ranked = _ranked_report()
    report = enrich_ranked_candidates(
        ranked,
        ranked_file="fixture_ranked.json",
        sources="nih_reporter,semantic_scholar",
        nih_reporter=EmptyNIHReporter(),
        semantic_scholar=EmptySemanticScholar(),
    )

    assert report.candidates
    assert report.run_summary.warnings
    assert report.candidates[0].enrichment.nih_reporter_grants == []


def test_enrich_candidates_cli_generates_json_markdown_and_csv(tmp_path, monkeypatch) -> None:
    ranked_file = tmp_path / "ranked_supervisors.json"
    ranked = _ranked_report()
    ranked_file.write_text(ranked.model_dump_json(), encoding="utf-8")

    def fake_enrich_candidates_from_file(**kwargs: object) -> EnrichedCandidateReport:
        report = enrich_ranked_candidates(
            ranked,
            ranked_file=kwargs["ranked_file"],
            sources="manual",
        )
        return report

    monkeypatch.setattr(
        "postdoc_scout.cli.enrich_candidates_from_file",
        fake_enrich_candidates_from_file,
    )
    result = CliRunner().invoke(
        app,
        [
            "enrich-candidates",
            "--ranked-file",
            str(ranked_file),
            "--sources",
            "nih_reporter,semantic_scholar,manual",
            "--output-dir",
            str(tmp_path),
            "--format",
            "all",
        ],
    )

    assert result.exit_code == 0
    assert "Enriched Supervisor Candidates" in result.output
    assert (tmp_path / "enriched_supervisors.json").exists()
    assert (tmp_path / "enriched_supervisors.md").exists()
    assert (tmp_path / "enriched_supervisors.csv").exists()


def _ranked_report():
    return rank_candidates_from_files(
        candidate_file=FIXTURE_CANDIDATE_FILE,
        evidence_file=FIXTURE_EVIDENCE_FILE,
        institution="Harvard University",
        mode="broad",
    )


class FakeNIHReporter:
    def search_projects(
        self,
        candidate_name: str,
        organizations: list[str] | None = None,
        year_from: int | None = None,
        year_to: int | None = None,
        limit: int = 10,
    ) -> list[FundingEvidence]:
        if candidate_name != "Nora Senior":
            return []
        return [
            FundingEvidence(
                title="Clinical AI for EHR risk prediction",
                funder="NIH",
                project_number="R01LM000001",
                fiscal_years=[2024],
                role="PI",
                organization="Harvard Medical School",
                url="https://reporter.nih.gov/project-details/1",
                relevance_domains=["clinical AI", "EHR/RWD"],
                evidence_id="nih_reporter:R01LM000001",
                confidence=0.8,
                notes="Fixture NIH funding evidence.",
            )
        ]

    def close(self) -> None:
        return None


class EmptyNIHReporter:
    def search_projects(
        self,
        candidate_name: str,
        organizations: list[str] | None = None,
        year_from: int | None = None,
        year_to: int | None = None,
        limit: int = 10,
    ) -> list[FundingEvidence]:
        return []

    def close(self) -> None:
        return None


class EmptySemanticScholar:
    def search_author_profiles(
        self,
        candidate_name: str,
        affiliations: list[str] | None = None,
        limit: int = 5,
    ) -> list[AuthorProfileEvidence]:
        return []

    def close(self) -> None:
        return None
