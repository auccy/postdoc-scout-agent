from pathlib import Path

from typer.testing import CliRunner

from postdoc_scout.candidate_extractor import (
    extract_author_mentions,
    extract_candidates,
    extract_candidates_from_file,
)
from postdoc_scout.cli import app
from postdoc_scout.models import (
    EvidenceCollection,
    EvidenceItem,
    Publication,
    RetrievedPublicationEvidence,
)


def test_extracts_author_mentions_from_mock_openalex_evidence() -> None:
    record = _record(
        source_connector="openalex",
        title="Clinical AI risk prediction",
        authors=["Alice First", "Sam Middle", "Nora Senior"],
        author_affiliations={"Nora Senior": ["Harvard Medical School"]},
        evidence_id="openalex:1",
    )

    mentions = extract_author_mentions(record)
    senior = [mention for mention in mentions if mention.author_name == "Nora Senior"][0]

    assert len(mentions) == 3
    assert senior.author_position == "last"
    assert senior.matched_institution_units == ["Harvard Medical School"]
    assert senior.evidence_id == "openalex:1"


def test_extracts_author_mentions_from_mock_pubmed_evidence() -> None:
    record = _record(
        source_connector="pubmed",
        title="Oncology digital medicine implementation",
        authors=["Alex Doe", "Morgan Corresponding"],
        author_affiliations={"Morgan Corresponding": ["MD Anderson Cancer Center"]},
        corresponding_authors=["Morgan Corresponding"],
        matched_unit_name="MD Anderson Cancer Center",
        evidence_id="pubmed:123",
    )

    mentions = extract_author_mentions(record)
    corresponding = [
        mention for mention in mentions if mention.author_name == "Morgan Corresponding"
    ][0]

    assert corresponding.author_position == "corresponding"
    assert corresponding.source_connector == "pubmed"
    assert "oncology" in corresponding.relevance_domains


def test_clusters_repeated_senior_author_mentions() -> None:
    collection = EvidenceCollection(
        institution="Harvard University",
        normalized_institution="harvard university",
        generated_at="2026-06-29T00:00:00+00:00",
        publications=[
            _record(
                title="Clinical AI risk prediction",
                authors=["Alice First", "Nora Senior"],
                author_affiliations={"Nora Senior": ["Harvard Medical School"]},
                evidence_id="ev:1",
            ),
            _record(
                title="EHR real-world data progression modeling",
                authors=["Bob First", "Nora Senior"],
                author_affiliations={"Nora Senior": ["Harvard Medical School"]},
                evidence_id="ev:2",
            ),
        ],
    )

    report = extract_candidates(collection, "Harvard University", "broad", "fixture.json")
    cluster = [
        cluster for cluster in report.candidate_clusters if cluster.display_name == "Nora Senior"
    ][0]

    assert cluster.senior_author_count == 2
    assert cluster.recent_publication_count == 2
    assert cluster.candidate_confidence >= 0.8
    assert {mention.evidence_id for mention in cluster.author_mentions} == {"ev:1", "ev:2"}


def test_same_name_with_conflicting_affiliations_has_warning() -> None:
    collection = EvidenceCollection(
        institution="Harvard University",
        normalized_institution="harvard university",
        generated_at="2026-06-29T00:00:00+00:00",
        publications=[
            _record(
                title="Clinical AI risk prediction",
                authors=["Jordan Lee"],
                author_affiliations={"Jordan Lee": ["Harvard Medical School"]},
                evidence_id="ev:harvard",
            ),
            _record(
                title="Oncology EHR prediction",
                authors=["Jordan Lee"],
                author_affiliations={"Jordan Lee": ["Stanford Medicine"]},
                evidence_id="ev:stanford",
            ),
        ],
    )

    report = extract_candidates(collection, "Harvard University", "broad", "fixture.json")
    cluster = [
        cluster for cluster in report.candidate_clusters if cluster.display_name == "Jordan Lee"
    ][0]

    assert any("multiple affiliation strings" in warning for warning in cluster.ambiguity_warnings)
    assert cluster.candidate_confidence < 0.9


def test_missing_affiliations_are_handled_gracefully() -> None:
    collection = EvidenceCollection(
        institution="Harvard University",
        normalized_institution="harvard university",
        generated_at="2026-06-29T00:00:00+00:00",
        publications=[
            _record(
                title="Digital medicine deployment",
                authors=["No Affiliation", "Senior Missing"],
                author_affiliations={},
                evidence_id="ev:missing",
            )
        ],
    )

    report = extract_candidates(collection, "Harvard University", "broad", "fixture.json")
    cluster = [
        cluster for cluster in report.candidate_clusters if cluster.display_name == "Senior Missing"
    ][0]

    assert any(
        "affiliation metadata is missing" in warning for warning in cluster.ambiguity_warnings
    )
    assert cluster.candidate_confidence < 0.8


def test_middle_author_only_candidate_has_lower_confidence() -> None:
    collection = EvidenceCollection(
        institution="Harvard University",
        normalized_institution="harvard university",
        generated_at="2026-06-29T00:00:00+00:00",
        publications=[
            _record(
                title="Clinical decision support study",
                authors=["First Author", "Middle Candidate", "Senior Author"],
                author_affiliations={"Middle Candidate": ["Harvard Medical School"]},
                evidence_id="ev:middle",
            )
        ],
    )

    report = extract_candidates(collection, "Harvard University", "broad", "fixture.json")
    cluster = [
        cluster
        for cluster in report.candidate_clusters
        if cluster.display_name == "Middle Candidate"
    ][0]

    assert cluster.senior_author_count == 0
    assert cluster.candidate_confidence < 0.6
    assert any("middle-author" in warning for warning in cluster.ambiguity_warnings)


def test_extract_candidates_cli_generates_json_markdown_and_csv(tmp_path) -> None:
    collection = EvidenceCollection(
        institution="Harvard University",
        normalized_institution="harvard university",
        generated_at="2026-06-29T00:00:00+00:00",
        publications=[
            _record(
                title="Clinical AI risk prediction",
                authors=["Alice First", "Nora Senior"],
                author_affiliations={"Nora Senior": ["Harvard Medical School"]},
                evidence_id="ev:cli",
            )
        ],
    )
    evidence_file = tmp_path / "evidence_collection.json"
    evidence_file.write_text(collection.model_dump_json(), encoding="utf-8")

    result = CliRunner().invoke(
        app,
        [
            "extract-candidates",
            "--evidence-file",
            str(evidence_file),
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
    assert "Candidate Extraction" in result.output
    assert (tmp_path / "candidate_extraction.json").exists()
    assert (tmp_path / "candidate_extraction.md").exists()
    assert (tmp_path / "candidate_extraction.csv").exists()

    report = extract_candidates_from_file(
        evidence_file,
        institution="Harvard University",
        mode="broad",
    )
    assert report.total_candidate_clusters >= 1


def test_extract_candidates_from_fixture_evidence_file() -> None:
    report = extract_candidates_from_file(
        evidence_file=Path("tests/fixtures/evidence_collection_mock.json"),
        institution="Harvard University",
        mode="broad",
    )
    cluster = [
        cluster for cluster in report.candidate_clusters if cluster.display_name == "Nora Senior"
    ][0]

    assert report.total_publications_processed == 2
    assert cluster.senior_author_count == 1
    assert cluster.corresponding_author_count == 1
    assert cluster.matched_institution_units == ["Harvard Medical School"]


def _record(
    title: str,
    authors: list[str],
    author_affiliations: dict[str, list[str]],
    evidence_id: str,
    source_connector: str = "openalex",
    matched_unit_name: str = "Harvard Medical School",
    corresponding_authors: list[str] | None = None,
) -> RetrievedPublicationEvidence:
    publication = Publication(
        title=title,
        year=2024,
        journal="Mock Translational Journal",
        authors=authors,
        affiliations=[
            affiliation
            for affiliations in author_affiliations.values()
            for affiliation in affiliations
        ],
        author_affiliations=author_affiliations,
        corresponding_authors=corresponding_authors or [],
        abstract="Clinical AI and EHR real-world data evidence.",
        relevance_domains=["clinical AI", "EHR/RWD", "oncology"],
        evidence_items=[
            EvidenceItem(
                evidence_id=evidence_id,
                source_type="publication",
                title=title,
                source_name="Mock source",
                quoted_or_paraphrased_evidence="Mock publication evidence.",
                relevance_domains=["clinical AI", "EHR/RWD"],
                note="Fixture evidence.",
                confidence=0.8,
            )
        ],
    )
    return RetrievedPublicationEvidence(
        publication=publication,
        source_connector=source_connector,
        originating_query_id=f"q_fixture_{source_connector}",
        originating_query_text="fixture query",
        matched_unit_name=matched_unit_name,
        relevance_domains=["clinical AI", "EHR/RWD", "oncology"],
    )
