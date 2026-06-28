import httpx
from typer.testing import CliRunner

from postdoc_scout.cli import app
from postdoc_scout.connectors.base import ConnectorError
from postdoc_scout.connectors.openalex import OpenAlexConnector
from postdoc_scout.connectors.pubmed import PubMedConnector
from postdoc_scout.evidence_collector import (
    collect_evidence,
    deduplicate_publication_evidence,
)
from postdoc_scout.models import (
    ConnectorRunSummary,
    EvidenceCollection,
    Publication,
    QueryBundle,
    RetrievedPublicationEvidence,
    SearchQuery,
)


def _query(source: str = "openalex", query_id: str = "q_0001_openalex") -> SearchQuery:
    return SearchQuery(
        query_id=query_id,
        query_text='"Harvard Medical School" "clinical AI"',
        source=source,
        institution="Harvard University",
        unit_name="Harvard Medical School",
        unit_type="medical_school",
        mode="broad",
        relevance_domains=["clinical AI", "EHR/RWD", "digital medicine"],
        priority="high",
        rationale="Mock query.",
        expected_evidence_type="publication",
    )


def _bundle() -> QueryBundle:
    return QueryBundle(
        institution="Harvard University",
        normalized_institution="harvard university",
        mode="broad",
        generated_at="2026-06-29T00:00:00+00:00",
        queries=[
            _query("openalex", "q_0001_openalex"),
            _query("pubmed", "q_0002_pubmed"),
        ],
    )


def test_openalex_connector_normalizes_mock_work() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/works"
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "https://openalex.org/W123",
                        "title": "Clinical AI for EHR-based risk prediction",
                        "publication_year": 2024,
                        "doi": "https://doi.org/10.1000/example",
                        "primary_location": {"source": {"display_name": "Lancet Digital Health"}},
                        "abstract_inverted_index": {
                            "Clinical": [0],
                            "AI": [1],
                            "EHR": [2],
                            "prediction": [3],
                        },
                        "authorships": [
                            {
                                "author": {"display_name": "Jane Smith"},
                                "institutions": [{"display_name": "Harvard Medical School"}],
                            }
                        ],
                    }
                ]
            },
        )

    client = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="https://api.openalex.org/",
    )
    connector = OpenAlexConnector(client=client, delay_seconds=0)
    records = connector.search_publications(_query(), limit=1, year_from=2021)

    assert len(records) == 1
    publication = records[0].publication
    assert publication.title == "Clinical AI for EHR-based risk prediction"
    assert publication.year == 2024
    assert publication.journal == "Lancet Digital Health"
    assert publication.doi == "10.1000/example"
    assert publication.authors == ["Jane Smith"]
    assert "clinical AI" in publication.relevance_domains
    assert records[0].originating_query_id == "q_0001_openalex"


def test_pubmed_connector_normalizes_mock_publication() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/esearch.fcgi"):
            return httpx.Response(200, json={"esearchresult": {"idlist": ["12345"]}})
        return httpx.Response(
            200,
            text="""
            <PubmedArticleSet>
              <PubmedArticle>
                <MedlineCitation>
                  <PMID>12345</PMID>
                  <Article>
                    <Journal>
                      <JournalIssue><PubDate><Year>2023</Year></PubDate></JournalIssue>
                      <Title>JAMA Oncology</Title>
                    </Journal>
                    <ArticleTitle>Oncology digital medicine risk prediction</ArticleTitle>
                    <Abstract>
                      <AbstractText>Clinical AI using EHR real-world data.</AbstractText>
                    </Abstract>
                    <AuthorList>
                      <Author>
                        <LastName>Doe</LastName><ForeName>Alex</ForeName>
                        <AffiliationInfo>
                          <Affiliation>MD Anderson Cancer Center</Affiliation>
                        </AffiliationInfo>
                      </Author>
                    </AuthorList>
                  </Article>
                </MedlineCitation>
                <PubmedData>
                  <ArticleIdList>
                    <ArticleId IdType="doi">10.2000/pubmed</ArticleId>
                  </ArticleIdList>
                </PubmedData>
              </PubmedArticle>
            </PubmedArticleSet>
            """,
        )

    client = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="https://eutils.ncbi.nlm.nih.gov/entrez/eutils/",
    )
    connector = PubMedConnector(client=client, delay_seconds=0)
    records = connector.search_publications(_query("pubmed", "q_0002_pubmed"), limit=1)

    assert len(records) == 1
    publication = records[0].publication
    assert publication.title == "Oncology digital medicine risk prediction"
    assert publication.year == 2023
    assert publication.journal == "JAMA Oncology"
    assert publication.pmid == "12345"
    assert publication.doi == "10.2000/pubmed"
    assert publication.authors == ["Alex Doe"]
    assert records[0].source_connector == "pubmed"


def test_evidence_collector_deduplicates_doi_pmid_and_title_year() -> None:
    first = _record("First", doi="10.1/shared")
    duplicate_doi = _record("Different title", doi="10.1/shared")
    pmid = _record("Second", pmid="222")
    duplicate_pmid = _record("Second variant", pmid="222")
    title_year = _record("Same Title", year=2024)
    duplicate_title_year = _record(" same   title ", year=2024)

    deduped = deduplicate_publication_evidence(
        [first, duplicate_doi, pmid, duplicate_pmid, title_year, duplicate_title_year]
    )

    assert len(deduped) == 3


def test_connector_errors_are_handled_gracefully() -> None:
    collection = collect_evidence(
        bundle=_bundle(),
        sources="openalex",
        limit_per_source=2,
        connectors={"openalex": BrokenConnector()},
    )

    assert collection.total_queries_run == 1
    assert collection.publications == []
    assert collection.connector_summaries[0].errors
    assert collection.warnings


def test_collect_evidence_cli_writes_reports_with_mocked_collector(tmp_path, monkeypatch) -> None:
    query_file = tmp_path / "queries.json"
    query_file.write_text(_bundle().model_dump_json(), encoding="utf-8")

    def fake_collect_evidence_from_query_file(**kwargs: object) -> EvidenceCollection:
        return EvidenceCollection(
            institution="Harvard University",
            normalized_institution="harvard university",
            generated_at="2026-06-29T00:00:00+00:00",
            query_file=str(kwargs["query_file"]),
            sources=["openalex", "pubmed"],
            total_queries_run=2,
            total_publications_retrieved=1,
            deduplicated_publications=1,
            publications=[_record("Clinical AI evidence", doi="10.1/cli")],
            connector_summaries=[
                ConnectorRunSummary(
                    source_connector="openalex",
                    queries_attempted=1,
                    requests_made=1,
                    publications_retrieved=1,
                )
            ],
        )

    monkeypatch.setattr(
        "postdoc_scout.cli.collect_evidence_from_query_file",
        fake_collect_evidence_from_query_file,
    )
    result = CliRunner().invoke(
        app,
        [
            "collect-evidence",
            "--query-file",
            str(query_file),
            "--sources",
            "openalex,pubmed",
            "--limit-per-source",
            "20",
            "--output-dir",
            str(tmp_path),
            "--format",
            "both",
        ],
    )

    assert result.exit_code == 0
    assert "Publication Evidence Collection" in result.output
    assert (tmp_path / "evidence_collection.json").exists()
    assert (tmp_path / "evidence_collection.md").exists()


def _record(
    title: str,
    doi: str | None = None,
    pmid: str | None = None,
    year: int | None = 2024,
) -> RetrievedPublicationEvidence:
    return RetrievedPublicationEvidence(
        publication=Publication(
            title=title,
            year=year,
            journal="Mock Journal",
            doi=doi,
            pmid=pmid,
            relevance_domains=["clinical AI"],
        ),
        source_connector="openalex",
        originating_query_id="q_0001_openalex",
        originating_query_text="mock query",
        matched_unit_name="Harvard Medical School",
        relevance_domains=["clinical AI"],
    )


class BrokenConnector:
    connector_name = "openalex"
    requests_made = 0

    def search_publications(
        self,
        query: SearchQuery,
        limit: int = 10,
        year_from: int | None = None,
        year_to: int | None = None,
    ) -> list[RetrievedPublicationEvidence]:
        self.requests_made += 1
        raise ConnectorError("openalex", "mock outage", 503)

    def close(self) -> None:
        return None
