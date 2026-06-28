"""PubMed/NCBI E-utilities publication evidence connector."""

import os
import re
import xml.etree.ElementTree as ET
from typing import Any

import httpx

from postdoc_scout.connectors.base import BaseHTTPConnector
from postdoc_scout.connectors.openalex import _infer_relevance_domains, _relevance_warnings
from postdoc_scout.models import (
    EvidenceItem,
    Publication,
    RetrievedPublicationEvidence,
    SearchQuery,
)


class PubMedConnector(BaseHTTPConnector):
    """Collect and normalize publication evidence from PubMed E-utilities."""

    connector_name = "pubmed"
    base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"

    def __init__(
        self,
        client: httpx.Client | None = None,
        ncbi_api_key: str | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(client=client, api_key=ncbi_api_key or os.getenv("NCBI_API_KEY"), **kwargs)

    def search_publications(
        self,
        query: SearchQuery,
        limit: int = 10,
        year_from: int | None = None,
        year_to: int | None = None,
    ) -> list[RetrievedPublicationEvidence]:
        """Run ESearch and EFetch, then normalize PubMed article evidence."""
        term = query.query_text
        if year_from is not None or year_to is not None:
            start = year_from if year_from is not None else 1800
            end = year_to if year_to is not None else 3000
            term = f"({term}) AND ({start}:{end}[dp])"
        params: dict[str, Any] = {
            "db": "pubmed",
            "term": term,
            "retmode": "json",
            "retmax": max(1, min(limit, 100)),
        }
        if self.api_key:
            params["api_key"] = self.api_key
        search_data = self._get_json("esearch.fcgi", params)
        pmids = _extract_pmids(search_data, limit)
        if not pmids:
            return []

        fetch_params: dict[str, Any] = {
            "db": "pubmed",
            "id": ",".join(pmids),
            "retmode": "xml",
            "rettype": "abstract",
        }
        if self.api_key:
            fetch_params["api_key"] = self.api_key
        xml_text = self._get_text("efetch.fcgi", fetch_params)
        return [
            _normalize_pubmed_article(article, query)
            for article in ET.fromstring(xml_text).findall(".//PubmedArticle")
        ][:limit]


def _extract_pmids(search_data: dict[str, Any], limit: int) -> list[str]:
    result = search_data.get("esearchresult", {})
    if not isinstance(result, dict):
        return []
    idlist = result.get("idlist", [])
    if not isinstance(idlist, list):
        return []
    return [str(pmid) for pmid in idlist[:limit]]


def _normalize_pubmed_article(
    article: ET.Element,
    query: SearchQuery,
) -> RetrievedPublicationEvidence:
    pmid = _text(article.find(".//MedlineCitation/PMID"))
    title = _joined_text(article.find(".//ArticleTitle"))
    journal = _joined_text(article.find(".//Journal/Title"))
    year = _publication_year(article)
    abstract = " ".join(
        text for text in (_joined_text(node) for node in article.findall(".//AbstractText")) if text
    )
    authors = _pubmed_authors(article)
    doi = _article_id(article, "doi")
    affiliations = _pubmed_affiliations(article)
    relevance_domains = _infer_relevance_domains(
        " ".join([title, abstract, " ".join(query.relevance_domains)]),
        query.relevance_domains,
    )
    warnings = _relevance_warnings(title, abstract)
    evidence = EvidenceItem(
        evidence_id=f"pubmed:{pmid or doi or title[:40]}",
        source_type="publication",
        title=title,
        url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else None,
        year=year,
        source_name="PubMed",
        quoted_or_paraphrased_evidence=abstract[:500] or title,
        relevance_domains=relevance_domains,
        note=(
            f"Retrieved from PubMed for query {query.query_id}. "
            f"Affiliations: {', '.join(affiliations[:5])}"
        ),
        confidence=0.7,
    )
    publication = Publication(
        title=title,
        year=year,
        journal=journal,
        authors=authors,
        doi=doi,
        pmid=pmid or None,
        url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else None,
        abstract=abstract,
        relevance_domains=relevance_domains,
        evidence_items=[evidence],
    )
    return RetrievedPublicationEvidence(
        publication=publication,
        source_connector="pubmed",
        originating_query_id=query.query_id,
        originating_query_text=query.query_text,
        matched_unit_name=query.unit_name,
        relevance_domains=relevance_domains,
        retrieval_warnings=warnings,
    )


def _text(node: ET.Element | None) -> str:
    return node.text.strip() if node is not None and node.text else ""


def _joined_text(node: ET.Element | None) -> str:
    if node is None:
        return ""
    return " ".join(part.strip() for part in node.itertext() if part.strip())


def _publication_year(article: ET.Element) -> int | None:
    for path in [
        ".//JournalIssue/PubDate/Year",
        ".//ArticleDate/Year",
        ".//PubmedPubDate[@PubStatus='pubmed']/Year",
    ]:
        value = _text(article.find(path))
        if value.isdigit():
            return int(value)
    medline_date = _text(article.find(".//JournalIssue/PubDate/MedlineDate"))
    match = re.search(r"\b(19|20)\d{2}\b", medline_date)
    return int(match.group(0)) if match else None


def _pubmed_authors(article: ET.Element) -> list[str]:
    authors = []
    for author in article.findall(".//AuthorList/Author"):
        collective = _text(author.find("CollectiveName"))
        if collective:
            authors.append(collective)
            continue
        last = _text(author.find("LastName"))
        fore = _text(author.find("ForeName"))
        name = " ".join(part for part in [fore, last] if part)
        if name:
            authors.append(name)
    return _dedupe(authors)


def _article_id(article: ET.Element, id_type: str) -> str | None:
    for node in article.findall(".//ArticleId"):
        if node.attrib.get("IdType") == id_type and node.text:
            return node.text.strip()
    return None


def _pubmed_affiliations(article: ET.Element) -> list[str]:
    return _dedupe(
        [
            _joined_text(node)
            for node in article.findall(".//AffiliationInfo/Affiliation")
            if _joined_text(node)
        ]
    )


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    deduped = []
    for value in values:
        normalized = value.casefold().strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            deduped.append(value)
    return deduped
