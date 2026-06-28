"""OpenAlex publication evidence connector."""

from typing import Any

import httpx

from postdoc_scout.connectors.base import BaseHTTPConnector
from postdoc_scout.models import (
    EvidenceItem,
    Publication,
    RetrievedPublicationEvidence,
    SearchQuery,
)

CLINICAL_RELEVANCE_MARKERS = {
    "AD/ADRD": ["ad/adrd", "alzheimer", "dementia"],
    "aging": ["aging", "older adult", "cognitive decline"],
    "biomedical AI": ["biomedical ai", "artificial intelligence"],
    "clinical AI": ["clinical ai", "clinical machine learning", "machine learning"],
    "clinical decision support": ["decision support", "cds"],
    "digital medicine": ["digital medicine", "digital health"],
    "EHR/RWD": ["ehr", "electronic health record", "real-world data", "rwd"],
    "oncology": ["oncology", "cancer"],
    "patient stratification": ["patient stratification", "phenotyping"],
    "risk prediction": ["risk prediction", "prediction model"],
    "trial enrichment": ["trial enrichment", "clinical trial"],
}

METHOD_HEAVY_MARKERS = [
    "benchmark",
    "foundation model",
    "optimization theory",
    "statistical theory",
    "simulation study",
]


class OpenAlexConnector(BaseHTTPConnector):
    """Collect and normalize publication evidence from OpenAlex works."""

    connector_name = "openalex"
    base_url = "https://api.openalex.org/"

    def __init__(self, client: httpx.Client | None = None, **kwargs: object) -> None:
        super().__init__(client=client, **kwargs)

    def search_publications(
        self,
        query: SearchQuery,
        limit: int = 10,
        year_from: int | None = None,
        year_to: int | None = None,
    ) -> list[RetrievedPublicationEvidence]:
        """Search OpenAlex works and normalize publication evidence."""
        params: dict[str, object] = {
            "search": query.query_text,
            "per-page": max(1, min(limit, 50)),
            "page": 1,
        }
        filters = []
        if year_from is not None:
            filters.append(f"from_publication_date:{year_from}-01-01")
        if year_to is not None:
            filters.append(f"to_publication_date:{year_to}-12-31")
        if filters:
            params["filter"] = ",".join(filters)
        if self.contact_email:
            params["mailto"] = self.contact_email

        data = self._get_json("works", params)
        raw_results = data.get("results", [])
        if not isinstance(raw_results, list):
            raw_results = []
        records = [
            self._normalize_work(work, query)
            for work in raw_results[:limit]
            if isinstance(work, dict)
        ]
        return records

    def _normalize_work(
        self,
        work: dict[str, Any],
        query: SearchQuery,
    ) -> RetrievedPublicationEvidence:
        title = str(work.get("title") or work.get("display_name") or "").strip()
        year = _safe_int(work.get("publication_year"))
        source_name = _openalex_source_name(work)
        doi = _normalize_doi(work.get("doi"))
        url = str(work.get("id") or work.get("doi") or "").strip() or None
        abstract = _openalex_abstract(work.get("abstract_inverted_index"))
        authors = _openalex_authors(work)
        institutions = _openalex_institutions(work)
        relevance_domains = _infer_relevance_domains(
            " ".join([title, abstract, " ".join(query.relevance_domains)]),
            query.relevance_domains,
        )
        warnings = _relevance_warnings(title, abstract)
        evidence_id = f"openalex:{work.get('id') or doi or title[:40]}"
        evidence = EvidenceItem(
            evidence_id=evidence_id,
            source_type="publication",
            title=title,
            url=url,
            year=year,
            source_name="OpenAlex",
            quoted_or_paraphrased_evidence=abstract[:500] or title,
            relevance_domains=relevance_domains,
            note=(
                f"Retrieved from OpenAlex for query {query.query_id}. "
                f"Institutions: {', '.join(institutions[:5])}"
            ),
            confidence=0.65,
        )
        publication = Publication(
            title=title,
            year=year,
            journal=source_name,
            authors=authors,
            doi=doi,
            url=url,
            abstract=abstract,
            relevance_domains=relevance_domains,
            evidence_items=[evidence],
        )
        return RetrievedPublicationEvidence(
            publication=publication,
            source_connector="openalex",
            originating_query_id=query.query_id,
            originating_query_text=query.query_text,
            matched_unit_name=query.unit_name,
            relevance_domains=relevance_domains,
            retrieval_warnings=warnings,
        )


def _safe_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _normalize_doi(value: object) -> str | None:
    if not value:
        return None
    doi = str(value).strip()
    doi = doi.removeprefix("https://doi.org/")
    doi = doi.removeprefix("http://doi.org/")
    return doi or None


def _openalex_source_name(work: dict[str, Any]) -> str:
    primary = work.get("primary_location")
    if isinstance(primary, dict):
        source = primary.get("source")
        if isinstance(source, dict) and source.get("display_name"):
            return str(source["display_name"])
    host_venue = work.get("host_venue")
    if isinstance(host_venue, dict) and host_venue.get("display_name"):
        return str(host_venue["display_name"])
    return ""


def _openalex_abstract(index: object) -> str:
    if not isinstance(index, dict):
        return ""
    positioned: list[tuple[int, str]] = []
    for token, positions in index.items():
        if not isinstance(positions, list):
            continue
        for position in positions:
            safe_position = _safe_int(position)
            if safe_position is not None:
                positioned.append((safe_position, str(token)))
    return " ".join(token for _, token in sorted(positioned))


def _openalex_authors(work: dict[str, Any]) -> list[str]:
    authors = []
    for authorship in work.get("authorships", []):
        if not isinstance(authorship, dict):
            continue
        author = authorship.get("author")
        if isinstance(author, dict) and author.get("display_name"):
            authors.append(str(author["display_name"]))
    return _dedupe(authors)


def _openalex_institutions(work: dict[str, Any]) -> list[str]:
    institutions = []
    for authorship in work.get("authorships", []):
        if not isinstance(authorship, dict):
            continue
        for institution in authorship.get("institutions", []):
            if isinstance(institution, dict) and institution.get("display_name"):
                institutions.append(str(institution["display_name"]))
    return _dedupe(institutions)


def _infer_relevance_domains(text: str, query_domains: list[str]) -> list[str]:
    lowered = text.casefold()
    inferred = list(query_domains)
    for domain, markers in CLINICAL_RELEVANCE_MARKERS.items():
        if any(marker in lowered for marker in markers):
            inferred.append(domain)
    return _dedupe(inferred)


def _relevance_warnings(title: str, abstract: str) -> list[str]:
    lowered = f"{title} {abstract}".casefold()
    has_method_marker = any(marker in lowered for marker in METHOD_HEAVY_MARKERS)
    has_clinical_marker = any(
        marker in lowered
        for markers in CLINICAL_RELEVANCE_MARKERS.values()
        for marker in markers
    )
    if has_method_marker and not has_clinical_marker:
        return ["Method-heavy publication with limited explicit clinical translation signal."]
    return []


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    deduped = []
    for value in values:
        normalized = value.casefold().strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            deduped.append(value)
    return deduped
