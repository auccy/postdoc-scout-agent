"""Manual candidate review and shortlist tracking."""

import csv
from datetime import UTC, datetime
from pathlib import Path

from postdoc_scout.models import (
    CandidateReview,
    OpeningSignalReport,
    OutreachStatus,
    ReviewStatus,
    ShortlistReport,
)
from postdoc_scout.opening_signals import load_ranked_candidates

TRACKER_FIELDS = [
    "candidate_id",
    "display_name",
    "possible_affiliations",
    "original_priority_label",
    "original_score",
    "review_status",
    "outreach_status",
    "user_notes",
    "last_updated",
    "next_action",
    "contact_url",
    "email",
    "opening_signal_type",
    "opening_signal_strength",
    "opportunity_score_adjustment",
]


def init_review_tracker(
    ranked_file: Path,
    output: Path,
    opening_signals_file: Path | None = None,
) -> list[CandidateReview]:
    """Initialize a manual review tracker CSV from ranked candidates."""
    candidates = load_ranked_candidates(ranked_file)
    opening_by_id = _load_opening_signals(opening_signals_file)
    now = _now()
    reviews = []
    for candidate in candidates:
        opening = opening_by_id.get(candidate.candidate_id, {})
        reviews.append(
            CandidateReview(
                candidate_id=candidate.candidate_id,
                display_name=candidate.display_name,
                possible_affiliations="; ".join(candidate.possible_affiliations),
                original_priority_label=candidate.priority_label,
                original_score=candidate.overall_score,
                review_status="needs_more_review",
                outreach_status="not_contacted",
                user_notes="",
                last_updated=now,
                next_action="Review evidence and verify lab/profile page.",
                contact_url="",
                email="",
                opening_signal_type=opening.get("opening_signal_type", "no_signal_found"),
                opening_signal_strength=opening.get("opening_signal_strength", "none"),
                opportunity_score_adjustment=float(
                    opening.get("opportunity_score_adjustment", 0.0)
                ),
            )
        )
    write_review_tracker(reviews, output)
    return reviews


def update_candidate_review(
    tracker: Path,
    candidate_id: str,
    review_status: ReviewStatus | None = None,
    outreach_status: OutreachStatus | None = None,
    note: str | None = None,
    next_action: str | None = None,
) -> CandidateReview:
    """Update one candidate row in the manual review tracker."""
    reviews = read_review_tracker(tracker)
    for review in reviews:
        if review.candidate_id == candidate_id:
            if review_status is not None:
                review.review_status = review_status
            if outreach_status is not None:
                review.outreach_status = outreach_status
            if note is not None:
                review.user_notes = _merge_note(review.user_notes, note)
            if next_action is not None:
                review.next_action = next_action
            review.last_updated = _now()
            write_review_tracker(reviews, tracker)
            return review
    raise ValueError(f"Candidate ID not found in tracker: {candidate_id}")


def export_shortlist(
    tracker: Path,
    output: Path,
    status: ReviewStatus | None = None,
) -> ShortlistReport:
    """Export shortlisted tracker rows to CSV."""
    reviews = read_review_tracker(tracker)
    selected = [review for review in reviews if status is None or review.review_status == status]
    write_review_tracker(selected, output)
    return ShortlistReport(
        generated_at=_now(),
        tracker_file=str(tracker),
        output_file=str(output),
        status_filter=status,
        candidate_count=len(selected),
        candidates=selected,
    )


def read_review_tracker(path: Path) -> list[CandidateReview]:
    """Read review tracker CSV rows."""
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return [
        CandidateReview(
            **{
                **row,
                "original_score": float(row.get("original_score") or 0.0),
                "opportunity_score_adjustment": float(
                    row.get("opportunity_score_adjustment") or 0.0
                ),
            }
        )
        for row in rows
    ]


def write_review_tracker(reviews: list[CandidateReview], output: Path) -> Path:
    """Write review tracker CSV rows."""
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=TRACKER_FIELDS)
        writer.writeheader()
        for review in reviews:
            writer.writerow(review.model_dump())
    return output


def _load_opening_signals(path: Path | None) -> dict[str, dict[str, object]]:
    if path is None or not path.exists():
        return {}
    report = OpeningSignalReport.model_validate_json(path.read_text(encoding="utf-8"))
    return {
        candidate.candidate_id: {
            "opening_signal_type": candidate.opening_signal_type,
            "opening_signal_strength": candidate.opening_signal_strength,
            "opportunity_score_adjustment": candidate.opportunity_score_adjustment,
        }
        for candidate in report.candidates
    }


def _merge_note(existing: str, note: str) -> str:
    note = note.strip()
    if not note:
        return existing
    if not existing:
        return note
    return f"{existing} | {note}"


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()

