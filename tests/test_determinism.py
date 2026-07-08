"""The offline determinism contract: identical input -> byte-identical JSON."""

from click.testing import CliRunner

from coop_sql_review.cli import cli

FIXTURE = "tests/fixtures/select_star.sql"


def test_json_output_is_byte_identical_across_runs():
    runner = CliRunner()
    first = runner.invoke(cli, ["check", FIXTURE, "--format", "json"])
    second = runner.invoke(cli, ["check", FIXTURE, "--format", "json"])
    assert first.exit_code == 0 and second.exit_code == 0
    assert first.output == second.output


def test_text_output_is_stable():
    runner = CliRunner()
    first = runner.invoke(cli, ["check", FIXTURE])
    second = runner.invoke(cli, ["check", FIXTURE])
    assert first.output == second.output


def test_sarif_output_is_byte_identical_across_runs():
    runner = CliRunner()
    first = runner.invoke(cli, ["check", FIXTURE, "--format", "sarif"])
    second = runner.invoke(cli, ["check", FIXTURE, "--format", "sarif"])
    assert first.exit_code == 0 and second.exit_code == 0
    assert first.output == second.output and first.output.endswith("\n")
