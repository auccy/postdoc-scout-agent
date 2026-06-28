from typer.testing import CliRunner

from postdoc_scout.cli import app
from postdoc_scout.institution_mapper import (
    InstitutionTier,
    MappingMode,
    list_parent_institutions,
    map_institution_ecosystem,
)
from postdoc_scout.models import EvidenceItem, Publication, SupervisorCandidate
from postdoc_scout.scoring import (
    assign_priority_label,
    calculate_weighted_score,
    detect_method_heavy_profile,
    numeric_score_to_stars,
    score_candidate,
)
from postdoc_scout.seed_map_validation import validate_seed_map, validate_seed_payloads


def test_scout_command_smoke() -> None:
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "scout",
            "--institution",
            "Harvard Medical School",
            "--mode",
            "broad",
            "--limit",
            "20",
        ],
    )

    assert result.exit_code == 0
    assert "Harvard Medical School" in result.output
    assert "not_started_placeholder" in result.output


def test_candidate_models_can_be_created() -> None:
    evidence = EvidenceItem(
        evidence_id="ev_001",
        source_type="publication",
        title="Clinical AI paper",
        source_name="Mock source",
        quoted_or_paraphrased_evidence="Clinical AI and EHR/RWD evidence.",
        relevance_domains=["clinical AI", "EHR/RWD"],
        confidence=0.9,
        note="Mock note.",
    )
    publication = Publication(
        title="Clinical AI paper",
        year=2025,
        journal="Mock Journal",
        authors=["A", "B"],
        candidate_author_position="senior",
        relevance_domains=["clinical AI", "EHR/RWD"],
        evidence_items=[evidence],
    )
    candidate = SupervisorCandidate(
        name="Dr. Test",
        domains=["clinical AI", "EHR/RWD"],
        publications=[publication],
    )

    assert candidate.publications[0].evidence_items[0].evidence_id == "ev_001"


def test_weighted_score_calculation_and_traceability() -> None:
    candidate = SupervisorCandidate(
        name="Dr. Trace",
        domains=["digital medicine", "clinical AI", "EHR/RWD", "oncology"],
        profile_urls=["https://example.org/trace"],
        publications=[
            Publication(
                title="Digital oncology EHR study",
                year=2025,
                journal="Mock Journal",
                authors=["Dr. Trace"],
                candidate_author_position="senior",
                relevance_domains=["digital medicine", "clinical AI", "EHR/RWD", "oncology"],
                is_high_impact_journal=True,
                evidence_items=[
                    EvidenceItem(
                        evidence_id="trace_pub_001",
                        source_type="publication",
                        title="Digital oncology EHR study",
                        source_name="Mock publication metadata",
                        quoted_or_paraphrased_evidence="Digital oncology EHR evidence.",
                        relevance_domains=[
                            "digital medicine",
                            "clinical AI",
                            "EHR/RWD",
                            "oncology",
                        ],
                        confidence=0.9,
                        note="Mock note.",
                    )
                ],
            )
        ],
    )

    report = score_candidate(candidate)
    dimension_total = calculate_weighted_score(report.score_breakdown.dimensions)
    evidence_ids = {
        evidence_id
        for dimension in report.score_breakdown.dimensions
        for evidence_id in dimension.supporting_evidence_ids
    }

    assert dimension_total >= report.score_breakdown.overall_score
    assert "trace_pub_001" in evidence_ids


def test_star_conversion_and_priority_labels() -> None:
    assert numeric_score_to_stars(4.6) == "★★★★★"
    assert numeric_score_to_stars(2.4) == "★★☆☆☆"
    assert assign_priority_label(4.6) == "A+"
    assert assign_priority_label(4.2) == "A"
    assert assign_priority_label(3.8) == "A-"
    assert assign_priority_label(3.2) == "B"
    assert assign_priority_label(2.5) == "C"
    assert assign_priority_label(2.49) == "D"


def test_method_heavy_penalty_detection() -> None:
    candidate = SupervisorCandidate(
        name="Dr. Method",
        domains=["statistical theory", "foundation model architecture"],
        publications=[
            Publication(
                title="Benchmark-only foundation model architecture study",
                year=2025,
                journal="Mock Theory",
                authors=["Dr. Method"],
                candidate_author_position="senior",
                relevance_domains=["statistical theory", "foundation model architecture"],
                abstract="Benchmark-only simulation-only optimization theory.",
            )
        ],
    )

    penalty_applied, penalty, warnings = detect_method_heavy_profile(candidate)
    report = score_candidate(candidate)

    assert penalty_applied
    assert penalty > 0
    assert warnings
    assert report.score_breakdown.method_heavy_penalty_applied


def test_harvard_broad_mode_returns_expected_units() -> None:
    ecosystem = map_institution_ecosystem("Harvard University", MappingMode.BROAD)
    unit_names = {unit.name for unit in ecosystem.units}

    assert "Harvard Medical School" in unit_names
    assert "Harvard T.H. Chan School of Public Health" in unit_names
    assert "Massachusetts General Hospital" in unit_names
    assert "Brigham and Women's Hospital" in unit_names
    assert "Dana-Farber Cancer Institute" in unit_names
    assert "Broad Institute of MIT and Harvard" in unit_names


def test_us_seed_map_loads_at_least_50_parent_institutions() -> None:
    institutions = list_parent_institutions(country="us", tier=InstitutionTier.ALL)

    assert len(institutions) >= 50


def test_us_seed_map_validation_passes_current_files() -> None:
    result = validate_seed_map(country="us")

    assert result.valid
    assert result.errors == []
    assert result.coverage.total_parent_institutions >= 100
    assert result.coverage.total_units >= 250


def test_md_anderson_is_parent_institution() -> None:
    ecosystem = map_institution_ecosystem("MD Anderson Cancer Center", MappingMode.BROAD)

    assert ecosystem.institution.name == "MD Anderson Cancer Center"
    assert ecosystem.institution.parent_type == "cancer_center"
    assert any(unit.name == "MD Anderson Cancer Center" for unit in ecosystem.units)


def test_memorial_sloan_kettering_is_parent_institution() -> None:
    ecosystem = map_institution_ecosystem("Memorial Sloan Kettering Cancer Center")

    assert ecosystem.institution.name == "Memorial Sloan Kettering Cancer Center"
    assert ecosystem.institution.parent_type == "cancer_center"


def test_rockefeller_is_independent_parent_institution() -> None:
    ecosystem = map_institution_ecosystem("Rockefeller", MappingMode.BROAD)

    assert ecosystem.institution.name == "Rockefeller University"
    assert ecosystem.institution.parent_type == "independent_research_institute"
    assert any(unit.name == "Rockefeller University" for unit in ecosystem.units)


def test_validation_reports_are_generated(tmp_path) -> None:
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "validate-seed-map",
            "--country",
            "us",
            "--output-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0
    assert (tmp_path / "us_seed_map_validation.json").exists()
    assert (tmp_path / "us_seed_map_coverage.md").exists()


def test_unknown_fields_are_warnings_not_errors() -> None:
    payloads = {
        "test.yml": {
            "institutions": [
                {
                    "canonical_name": "Example University",
                    "aliases": [],
                    "parent_type": "university",
                    "city": "Example City",
                    "state": "EX",
                    "priority_tier": "C",
                    "relevance_domains": ["clinical AI"],
                    "notes": "Synthetic test entry.",
                    "verification_status": "curated_seed_needs_verification",
                    "unexpected_parent_field": "kept as warning",
                    "units": [
                        {
                            "name": "Example Medical School",
                            "unit_type": "medical_school",
                            "relationship_to_parent": "needs_verification",
                            "relevance_domains": ["clinical AI"],
                            "priority": "low",
                            "notes": "Synthetic test unit.",
                            "source_urls": [],
                            "verification_status": "curated_seed_needs_verification",
                            "unexpected_unit_field": "kept as warning",
                        }
                    ],
                }
            ]
        }
    }

    result = validate_seed_payloads(payloads)

    assert result.valid
    assert result.errors == []
    assert len(result.warnings) == 2


def test_narrow_mode_prioritizes_neurodegeneration_units() -> None:
    ecosystem = map_institution_ecosystem("Harvard", MappingMode.NARROW)
    top_domains = set().union(*(unit.relevance_domains for unit in ecosystem.units[:3]))

    assert {"AD/ADRD", "aging", "neurodegeneration", "neuroscience"} & top_domains


def test_broad_mode_includes_translational_domains() -> None:
    ecosystem = map_institution_ecosystem("Harvard University", MappingMode.BROAD)
    domains = set().union(*(unit.relevance_domains for unit in ecosystem.units))

    assert "oncology" in domains
    assert "clinical AI" in domains
    assert "EHR/RWD" in domains
    assert "digital medicine" in domains
    assert "public health" in domains


def test_unknown_institution_returns_structured_empty_result() -> None:
    ecosystem = map_institution_ecosystem("Unknown Example Institute", MappingMode.BROAD)

    assert ecosystem.institution.name == "Unknown Example Institute"
    assert ecosystem.institution.confidence == 0.1
    assert ecosystem.units == []
    assert ecosystem.limitations


def test_map_institution_cli_smoke(tmp_path) -> None:
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "map-institution",
            "--institution",
            "Harvard University",
            "--mode",
            "broad",
            "--output-dir",
            str(tmp_path),
            "--format",
            "both",
        ],
    )

    assert result.exit_code == 0
    assert "Harvard University" in result.output
    assert (tmp_path / "harvard_university_ecosystem.json").exists()
    assert (tmp_path / "harvard_university_ecosystem.md").exists()


def test_list_institutions_cli_smoke() -> None:
    runner = CliRunner()
    tier_a_names = {
        str(entry.get("canonical_name") or entry.get("name"))
        for entry in list_parent_institutions(country="us", tier=InstitutionTier.A)
    }

    result = runner.invoke(
        app,
        [
            "list-institutions",
            "--country",
            "us",
            "--tier",
            "A",
        ],
    )

    assert result.exit_code == 0
    assert "Harvard University" in result.output
    assert "MD Anderson Cancer Center" in tier_a_names


def test_score_mock_candidates_cli(tmp_path) -> None:
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "score-mock-candidates",
            "--input",
            "examples/mock_candidates.yml",
            "--output-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0
    assert "Dr. Maya Chen" in result.output
    assert "Dr. Victor Stone" in result.output
    assert (tmp_path / "mock_candidate_scores.json").exists()
    assert (tmp_path / "mock_candidate_scores.md").exists()
