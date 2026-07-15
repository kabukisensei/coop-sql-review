"""`check --diff-against FILE`: the run-to-run delta, built on core's delta engine.

Requires coop-review-core >= 0.6.0 (the `delta` module); run bare only after the
venv is refreshed to it, else shadow the local core on PYTHONPATH (see AGENTS.md).
"""

from click.testing import CliRunner

from coop_sql_review.cli import cli


def _json_report(runner, sql_path, out_path):
    r = runner.invoke(cli, ["check", str(sql_path), "--format", "json", "-o", str(out_path)])
    assert r.exit_code == 0, r.output
    return out_path


def test_diff_against_identical_run_is_all_persisting(tmp_path):
    sql = tmp_path / "q.sql"
    sql.write_text("SELECT * FROM dbo.orders;\n")  # one SQL-NO-SELECT-STAR finding
    old = _json_report(CliRunner(), sql, tmp_path / "old.json")
    r = CliRunner().invoke(cli, ["check", str(sql), "--diff-against", str(old)])
    assert r.exit_code == 0
    assert "0 new, 0 fixed, 1 unchanged" in r.output
    assert "summary delta:" in r.output


def test_diff_against_reports_new_and_fixed(tmp_path):
    a = tmp_path / "a.sql"
    a.write_text("SELECT * FROM dbo.t;\n")
    old = _json_report(CliRunner(), a, tmp_path / "old.json")
    # A different file basename gives the object-less SELECT * finding a different
    # fingerprint, so the old one reads as fixed and the new one as new.
    b = tmp_path / "b.sql"
    b.write_text("SELECT * FROM dbo.t;\n")
    r = CliRunner().invoke(cli, ["check", str(b), "--diff-against", str(old)])
    assert r.exit_code == 0
    assert "1 new, 1 fixed" in r.output
    assert "NEW (1)" in r.output and "FIXED (1)" in r.output


def test_diff_against_is_advisory_and_does_not_change_exit_code(tmp_path):
    # A finding present + --strict exits 2 as usual; --diff-against never alters that,
    # and with no --strict a run with findings still exits 0.
    sql = tmp_path / "q.sql"
    sql.write_text("SELECT * FROM dbo.orders;\n")
    old = _json_report(CliRunner(), sql, tmp_path / "old.json")
    r = CliRunner().invoke(cli, ["check", str(sql), "--diff-against", str(old)])
    assert r.exit_code == 0  # advisory, no --strict


def test_diff_against_wrong_tool_is_usage_error(tmp_path):
    sql = tmp_path / "q.sql"
    sql.write_text("SELECT 1;\n")
    dax = tmp_path / "dax.json"
    dax.write_text('{"tool": "coop-dax-review", "findings": [], "summary": {}}')
    r = CliRunner().invoke(cli, ["check", str(sql), "--diff-against", str(dax)])
    assert r.exit_code == 2
    assert "different tools" in r.output


def test_diff_against_missing_file_is_usage_error(tmp_path):
    sql = tmp_path / "q.sql"
    sql.write_text("SELECT 1;\n")
    r = CliRunner().invoke(cli, ["check", str(sql), "--diff-against", str(tmp_path / "nope.json")])
    assert r.exit_code == 2
    assert "--diff-against" in r.output


def test_diff_against_invalid_json_is_usage_error(tmp_path):
    sql = tmp_path / "q.sql"
    sql.write_text("SELECT 1;\n")
    bad = tmp_path / "bad.json"
    bad.write_text("not json{")
    r = CliRunner().invoke(cli, ["check", str(sql), "--diff-against", str(bad)])
    assert r.exit_code == 2
    assert "not valid JSON" in r.output
