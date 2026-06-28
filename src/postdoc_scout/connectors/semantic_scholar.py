"""Semantic Scholar author/profile enrichment connector."""

import os
import re
from typing import Any

import httpx

from postdoc_scout.connectors.base import BaseHTTPConnector
from postdoc_scout.models import AuthorProfileEvidence


class SemanticScholarConnector(BaseHTTPConnector):
    """Search Semantic Scholar author profiles for preliminary profile evidence."""

    connector_name = "semantic_scholar"
    base_url = "https://api.semanticscholar.org/graph/v1/"

    def __init__(
        self,
        client: httpx.Client | None = None,
        api_key: str | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(
            client=client,
            api_key=api_key or os.getenv("SEMANTIC_SCHOLAR_API_KEY"),
            **kwargs,
        )
        if self.api_key:
            self.client.headers.update({"x-api-key": self.api_key})

    def search_author_profiles(
        self,
        candidate_name: str,
        affiliations: list[str] | None = None,
        limit: int = 5,
    ) -> list[AuthorProfileEvidence]:
        """Search and normalize author profile candidates."""
        params = {
            "query": candidate_name,
            "limit": max(1, min(limit, 10)),
            "fields": "name,affiliations,paperCount,citationCount,hIndex,fieldsOfStudy,url",
        }
        data = self._get_json("author/search", params)
        raw_profiles = data.get("data", [])
        if not isinstance(raw_profiles, list):
            return []
        normalized = [
            _normalize_author_profile(
                profile,
                candidate_name,
                affiliations or [],
                len(raw_profiles),
            )
            for profile in raw_profiles[:limit]
            if isinstance(profile, dict)
        ]
        return normalized


def _normalize_author_profile(
    profile: dict[str, Any],
    candidate_name: str,
    affiliations: list[str],
    raw_match_count: int,
) -> AuthorProfileEvidence:
    name = str(profile.get("name") or "")
    author_id = str(profile.get("authorId") or profile.get("author_id") or "")
    profile_affiliations = [
        str(value)
        for value in profile.get("affiliations", [])
        if isinstance(value, str) and value.strip()
    ]
    fields = [
        str(value)
        for value in profile.get("fieldsOfStudy", [])
        if isinstance(value, str) and value.strip()
    ]
    warnings = []
    name_match = _normalize(name) == _normalize(candidate_name)
    affiliation_match = bool(
        {
            _normalize(value)
            for value in affiliations
            if _normalize(value)
        }
        & {
            _normalize(value)
            for value in profile_affiliations
            if _normalize(value)
        }
    )
    confidence = 0.35
    matched_by = "name_search"
    if name_match:
        confidence += 0.25
        matched_by = "exact_normalized_name"
    if affiliation_match:
        confidence += 0.25
        matched_by = f"{matched_by}+affiliation_overlap"
    if raw_match_count > 1:
        warnings.append("Multiple Semantic Scholar profiles matched this name; verify identity.")
        confidence -= 0.1
    if not profile_affiliations:
        warnings.append("Semantic Scholar profile has no affiliation metadata.")
    return AuthorProfileEvidence(
        source="semantic_scholar",
        profile_url=str(profile.get("url") or f"https://www.semanticscholar.org/author/{author_id}"),
        author_id=author_id or None,
        name=name,
        affiliations=profile_affiliations,
        paper_count=_safe_int(profile.get("paperCount")),
        citation_count=_safe_int(profile.get("citationCount")),
        h_index=_safe_int(profile.get("hIndex")),
        fields_of_study=fields,
        matched_by=matched_by,
        confidence=_clamp(confidence),
        warnings=warnings,
    )


def _normalize(value: str) -> str:
    normalized = value.casefold().replace("&", " and ")
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return " ".join(normalized.split())


def _safe_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, round(value, 3)))
