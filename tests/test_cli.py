from typer.testing import CliRunner

from postdoc_scout.cli import app


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
