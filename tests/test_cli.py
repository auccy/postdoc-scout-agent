from typer.testing import CliRunner

from postdoc_scout.cli import app
from postdoc_scout.institution_mapper import (
    InstitutionTier,
    MappingMode,
    list_parent_institutions,
    map_institution_ecosystem,
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
