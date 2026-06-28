from typer.testing import CliRunner

from postdoc_scout.cli import app
from postdoc_scout.institution_mapper import MappingMode, map_institution_ecosystem


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
    assert "public health" in domains


def test_unknown_institution_returns_structured_empty_result() -> None:
    ecosystem = map_institution_ecosystem("Unknown Example Institute", MappingMode.BROAD)

    assert ecosystem.institution.name == "Unknown Example Institute"
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
