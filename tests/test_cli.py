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


def test_header_and_layer_rules_off_by_default(tmp_path):
    # A non-medallion table with no header would trip both rules if enabled.
    f = tmp_path / "t.sql"
    f.write_text("CREATE TABLE dbo.foo (a int);\n", encoding="utf-8")
    out = CliRunner().invoke(cli, ["check", str(f)]).output
    assert "SQL-HEADER-COMMENT" not in out
    assert "SQL-TABLE-LAYER-NAME" not in out


def test_layer_rule_can_be_opted_in_via_config(tmp_path):
    f = tmp_path / "t.sql"
    f.write_text("CREATE TABLE dbo.foo (a int);\n", encoding="utf-8")
    cfg = tmp_path / "rules.yml"
    cfg.write_text("rules:\n  SQL-TABLE-LAYER-NAME:\n    enabled: true\n", encoding="utf-8")
    out = CliRunner().invoke(cli, ["check", str(f), "--config", str(cfg)]).output
    assert "SQL-TABLE-LAYER-NAME" in out


def test_output_writes_report_to_file(tmp_path):
    f = tmp_path / "t.sql"
    f.write_text("SELECT * FROM x;\n", encoding="utf-8")
    report = tmp_path / "report.txt"
    result = CliRunner().invoke(cli, ["check", str(f), "-o", str(report)])
    assert result.exit_code == 0
    assert "SQL-NO-SELECT-STAR" not in result.output  # went to the file, not the screen
    assert "SQL-NO-SELECT-STAR" in report.read_text(encoding="utf-8")


def test_markdown_format(tmp_path):
    f = tmp_path / "t.sql"
    f.write_text("SELECT * FROM x;\n", encoding="utf-8")
    out = CliRunner().invoke(cli, ["check", str(f), "--format", "markdown"]).output
    assert out.startswith("# coop-sql-review report")
    assert "## Findings" in out
    assert "SQL-NO-SELECT-STAR" in out


def test_html_format(tmp_path):
    f = tmp_path / "t.sql"
    f.write_text("SELECT * FROM x;\n", encoding="utf-8")
    out = CliRunner().invoke(cli, ["check", str(f), "--format", "html"]).output
    assert out.startswith("<!DOCTYPE html>")
    assert "<style>" in out and "</html>" in out
    assert "SQL-NO-SELECT-STAR" in out


def test_rules_command_marks_off_by_default():
    out = CliRunner().invoke(cli, ["rules"]).output
    # the two noisy rules ship but are marked off
    for line in out.splitlines():
        if "SQL-HEADER-COMMENT" in line or "SQL-TABLE-LAYER-NAME" in line:
            assert "off by default" in line
