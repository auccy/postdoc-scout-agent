"""NIH RePORTER funding evidence connector."""

from typing import Any

import httpx

from postdoc_scout.connectors.base import BaseHTTPConnector
from postdoc_scout.models import FundingEvidence


class NIHReporterConnector(BaseHTTPConnector):
    """Search NIH RePORTER projects for preliminary funding evidence."""

    connector_name = "nih_reporter"
    base_url = "https://api.reporter.nih.gov/v2/"

    def __init__(self, client: httpx.Client | None = None, **kwargs: object) -> None:
        super().__init__(client=client, **kwargs)

    def search_projects(
        self,
        candidate_name: str,
        organizations: list[str] | None = None,
        year_from: int | None = None,
        year_to: int | None = None,
        limit: int = 10,
    ) -> list[FundingEvidence]:
        """Search NIH projects by PI name and optional organization hints."""
        criteria: dict[str, Any] = {"pi_names": [{"any_name": candidate_name}]}
        if organizations:
            criteria["org_names"] = organizations[:3]
        if year_from is not None or year_to is not None:
            start_year = year_from or 1980
            end_year = year_to or year_from or 1980
            criteria["fiscal_years"] = list(range(start_year, end_year + 1))
        payload = {
            "criteria": criteria,
            "include_fields": [
                "ProjectTitle",
                "ProjectNum",
                "FiscalYear",
                "PrincipalInvestigators",
                "Organization",
                "AgencyICAdmin",
                "ProjectDetailUrl",
                "AbstractText",
            ],
            "offset": 0,
            "limit": max(1, min(limit, 50)),
        }
        data = self._post_json("projects/search", payload)
        raw_projects = data.get("results", [])
        if not isinstance(raw_projects, list):
            return []
        return [
            _normalize_project(project, candidate_name)
            for project in raw_projects[:limit]
            if isinstance(project, dict)
        ]


def _normalize_project(project: dict[str, Any], candidate_name: str) -> FundingEvidence:
    project_number = str(project.get("project_num") or project.get("projectNum") or "")
    title = str(project.get("project_title") or project.get("projectTitle") or "")
    fiscal_year = _safe_int(project.get("fiscal_year") or project.get("fiscalYear"))
    organization = project.get("organization") or {}
    org_name = ""
    if isinstance(organization, dict):
        org_name = str(organization.get("org_name") or organization.get("orgName") or "")
    funder = str(project.get("agency_ic_admin") or project.get("agencyICAdmin") or "NIH")
    pi_names = _pi_names(project.get("principal_investigators"))
    normalized_candidate = _normalized_name(candidate_name)
    role = "PI" if normalized_candidate in {_normalized_name(name) for name in pi_names} else ""
    abstract = str(project.get("abstract_text") or project.get("abstractText") or "")
    domains = _domains_from_text(f"{title} {abstract}")
    return FundingEvidence(
        title=title,
        funder=funder or "NIH",
        project_number=project_number or None,
        fiscal_years=[fiscal_year] if fiscal_year is not None else [],
        role=role,
        organization=org_name,
        url=str(project.get("project_detail_url") or project.get("projectDetailUrl") or ""),
        relevance_domains=domains,
        evidence_id=f"nih_reporter:{project_number or title[:40]}",
        confidence=0.75 if role else 0.55,
        notes="Preliminary NIH RePORTER funding evidence; verify PI and institution.",
    )


def _pi_names(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    names = []
    for item in value:
        if isinstance(item, dict):
            full_name = item.get("full_name") or item.get("fullName")
            if full_name:
                names.append(str(full_name))
    return names


def _safe_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _normalized_name(value: str) -> str:
    return " ".join(value.casefold().replace(",", " ").split())


def _domains_from_text(text: str) -> list[str]:
    lowered = text.casefold()
    mappings = {
        "AD/ADRD": ["alzheimer", "dementia", "ad/adrd"],
        "clinical AI": ["clinical ai", "machine learning", "prediction"],
        "clinical decision support": ["decision support"],
        "digital medicine": ["digital medicine", "digital health"],
        "EHR/RWD": ["ehr", "electronic health record", "real-world data"],
        "oncology": ["oncology", "cancer"],
        "patient stratification": ["patient stratification", "stratification"],
        "progression modeling": ["progression", "longitudinal"],
    }
    return [
        domain
        for domain, markers in mappings.items()
        if any(marker in lowered for marker in markers)
    ]
