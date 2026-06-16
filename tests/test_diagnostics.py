"""Diagnostics: parse problems and rule errors are surfaced, never swallowed."""

import json

from click.testing import CliRunner

from coop_sql_review.cli import cli
from coop_sql_review.diagnostics import PARSE_DEGRADED, PARSE_FAILED
from coop_sql_review.parser import parse_sql


def test_opaque_command_is_reported_as_parse_degraded():
    # ALTER COLUMN ... NOT NULL degrades to an opaque Command in sqlglot
    parsed = parse_sql("x.sql", "ALTER TABLE gold.t ALTER COLUMN c int NOT NULL;")
    cats = {d.category for d in parsed.diagnostics}
    assert PARSE_DEGRADED in cats
    assert all(d.severity == "warning" for d in parsed.diagnostics)


def test_unparseable_batch_is_reported_as_parse_failed():
    parsed = parse_sql("x.sql", "CREATE TABLE ok (a int);\nGO\n)))( totally not sql (((\n")
    cats = {d.category for d in parsed.diagnostics}
    assert PARSE_FAILED in cats
    # the good batch still produced its object
    assert any(o.name == "ok" for o in parsed.objects)


def test_diagnostics_appear_in_json_and_console(tmp_path):
    bad = tmp_path / "bad.sql"
    bad.write_text("ALTER TABLE gold.t ALTER COLUMN c int NOT NULL;\n", encoding="utf-8")
    runner = CliRunner()

    js = runner.invoke(cli, ["check", str(bad), "--format", "json"])
    payload = json.loads(js.output)
    assert "diagnostics" in payload
    assert any(d["category"] == "parse_degraded" for d in payload["diagnostics"])

    txt = runner.invoke(cli, ["check", str(bad)])
    assert "Diagnostics" in txt.output


def test_log_file_is_written(tmp_path):
    bad = tmp_path / "bad.sql"
    bad.write_text("ALTER TABLE gold.t ALTER COLUMN c int NOT NULL;\n", encoding="utf-8")
    log = tmp_path / "diag.log"
    result = CliRunner().invoke(cli, ["check", str(bad), "--log-file", str(log)])
    assert result.exit_code == 0
    assert log.is_file()
    contents = log.read_text(encoding="utf-8")
    assert "diagnostics log" in contents
    assert "parse_degraded" in contents
