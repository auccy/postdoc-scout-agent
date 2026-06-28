"""Core placeholder scouting workflow."""

from enum import Enum

from pydantic import BaseModel, Field


class ScoutMode(str, Enum):
    """Supported search modes for the scouting workflow."""

    BROAD = "broad"
    FOCUSED = "focused"


class ScoutRequest(BaseModel):
    """Inputs for a supervisor scouting run."""

    institution: str = Field(min_length=1)
    mode: ScoutMode = ScoutMode.BROAD
    limit: int = Field(default=20, ge=1, le=100)


class ScoutSummary(BaseModel):
    """Placeholder scouting result returned by the MVP skeleton."""

    institution: str
    mode: ScoutMode
    limit: int
    status: str
    focus_areas: list[str]


DEFAULT_FOCUS_AREAS = [
    "digital medicine",
    "clinical AI",
    "AD/ADRD",
    "oncology",
    "EHR-based prediction",
    "real-world data",
    "clinical decision support",
    "translational biomedical AI",
]


def run_placeholder_scout(request: ScoutRequest) -> ScoutSummary:
    """Return a deterministic placeholder summary for CLI smoke testing."""
    return ScoutSummary(
        institution=request.institution,
        mode=request.mode,
        limit=request.limit,
        status="not_started_placeholder",
        focus_areas=DEFAULT_FOCUS_AREAS,
    )
