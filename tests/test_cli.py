"""CLI: advisory exit codes, formats, the strict gate, and the rules command.

These exercise the real discovered rule set (engine + all_rules), so they are
the integration check that every rule module imports and runs cleanly.
"""

import json

from click.testing import CliRunner

from coop_sql_review.cli import cli

FIXTURE = "tests/fixtures/select_star.sql"


def test_check_is_advisory_exit_zero():
    result = CliRunner().invoke(cli, ["check", FIXTURE])
    assert result.exit_code == 0
    assert "SQL-NO-SELECT-STAR" in result.output
    assert "Advisory only" in result.output


def test_check_json_is_valid_contract():
    result = CliRunner().invoke(cli, ["check", FIXTURE, "--format", "json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["tool"] == "coop-sql-review"
    assert payload["standards"]["sha256"]
    assert any(f["rule_id"] == "SQL-NO-SELECT-STAR" for f in payload["findings"])


def test_strict_gate_exits_nonzero():
    result = CliRunner().invoke(cli, ["check", FIXTURE, "--strict", "--min-severity", "warning"])
    assert result.exit_code == 2


def test_min_severity_filters_findings():
    # the fixture only has warnings; raising the floor to error hides them
    result = CliRunner().invoke(cli, ["check", FIXTURE, "--min-severity", "error"])
    assert result.exit_code == 0
    assert "no issues" in result.output


def test_rules_command_lists_rules():
    result = CliRunner().invoke(cli, ["rules"])
    assert result.exit_code == 0
    assert "SQL-NO-SELECT-STAR" in result.output


def test_no_sql_files_message(tmp_path):
    result = CliRunner().invoke(cli, ["check", str(tmp_path)])
    assert result.exit_code == 0
    assert "No .sql files found" in result.output
