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


def test_text_report_is_styled_and_plain_when_piped():
    # CliRunner stdout is not a TTY -> auto mode stays plain (no ANSI).
    out = CliRunner().invoke(cli, ["check", FIXTURE]).output
    assert "\033[" not in out
    assert "coop-sql-review" in out and "SUMMARY" in out  # the report banner + panel


def test_text_report_color_flag_forces_ansi():
    out = CliRunner().invoke(cli, ["check", FIXTURE, "--color"]).output
    assert "\033[" in out  # explicit --color wins over the non-interactive default


def test_use_color_decision(monkeypatch):
    from coop_sql_review.cli import _use_color

    monkeypatch.delenv("NO_COLOR", raising=False)
    assert _use_color(True, None) is True  # explicit --color
    assert _use_color(False, None) is False  # explicit --no-color
    assert _use_color(None, "out.txt") is False  # writing to a file -> never color
    monkeypatch.setenv("NO_COLOR", "1")
    assert _use_color(None, None) is False  # NO_COLOR wins in auto mode


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


def test_nonexistent_path_is_called_out_not_silently_clean(tmp_path):
    # A typo'd path must not look identical to a clean scan.
    result = CliRunner().invoke(cli, ["check", str(tmp_path / "nope.sql")])
    assert result.exit_code == 0
    assert "path not found" in result.output
    assert "No .sql files found" not in result.output


def test_unknown_rule_id_in_config_warns(tmp_path):
    cfg = tmp_path / "rules.yml"
    cfg.write_text("rules:\n  SQL-NOPE-NOT-A-RULE:\n    enabled: false\n", encoding="utf-8")
    result = CliRunner().invoke(cli, ["check", FIXTURE, "--config", str(cfg)])
    assert result.exit_code == 0
    assert "unknown rule id 'SQL-NOPE-NOT-A-RULE'" in result.output


def test_json_includes_files_checked():
    out = CliRunner().invoke(cli, ["check", FIXTURE, "--format", "json"]).output
    payload = json.loads(out)
    assert payload["files_checked"] >= 1


def test_inline_ignore_directive_suppresses(tmp_path):
    f = tmp_path / "q.sql"
    f.write_text("-- coop-sql-review:ignore SQL-NO-SELECT-STAR\nSELECT * FROM t;\n", encoding="utf-8")
    out = CliRunner().invoke(cli, ["check", str(f)]).output
    assert "SQL-NO-SELECT-STAR" not in out
    assert "no issues found" in out


def test_baseline_write_then_suppresses(tmp_path):
    f = tmp_path / "q.sql"
    f.write_text("SELECT * FROM t;\n", encoding="utf-8")
    bl = tmp_path / "bl.json"
    written = CliRunner().invoke(cli, ["check", str(f), "--write-baseline", str(bl)])
    assert written.exit_code == 0 and bl.exists()
    out = CliRunner().invoke(cli, ["check", str(f), "--baseline", str(bl)]).output
    assert "SQL-NO-SELECT-STAR" not in out
    assert "no issues found" in out


def test_baseline_lets_new_findings_through(tmp_path):
    a = tmp_path / "a.sql"
    a.write_text("SELECT * FROM t;\n", encoding="utf-8")
    bl = tmp_path / "bl.json"
    CliRunner().invoke(cli, ["check", str(a), "--write-baseline", str(bl)])
    # a NEW finding in a different file is keyed differently -> it surfaces
    b = tmp_path / "b.sql"
    b.write_text("SELECT * FROM u;\n", encoding="utf-8")
    out = CliRunner().invoke(cli, ["check", str(tmp_path), "--baseline", str(bl)]).output
    assert "SQL-NO-SELECT-STAR" in out  # b.sql's finding is new
    assert "b.sql" in out


def test_stale_baseline_entry_warns(tmp_path):
    f = tmp_path / "q.sql"
    f.write_text("SELECT * FROM t;\n", encoding="utf-8")
    bl = tmp_path / "bl.json"
    CliRunner().invoke(cli, ["check", str(f), "--write-baseline", str(bl)])
    f.write_text("SELECT a FROM t;\n", encoding="utf-8")  # fix it -> the baseline entry is now stale
    out = CliRunner().invoke(cli, ["check", str(f), "--baseline", str(bl)]).output
    assert "baseline:" in out and "no longer match" in out


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


def test_output_announces_resolved_path(tmp_path):
    f = tmp_path / "t.sql"
    f.write_text("SELECT * FROM x;\n", encoding="utf-8")
    report = tmp_path / "review.html"
    result = CliRunner().invoke(cli, ["check", str(f), "-o", str(report), "--format", "html"])
    assert result.exit_code == 0
    # The path is announced on STDERR (stdout stays the byte-identical report
    # artifact) even though the run is non-interactive — an agent reads the
    # file we name. Asserting on result.stderr (not the merged result.output)
    # guards the stdout/stderr contract: a dropped err=True would fail here.
    assert "Report written to" in result.stderr
    assert report.resolve().as_posix() in result.stderr


def test_html_not_auto_opened_when_not_a_tty(tmp_path, monkeypatch):
    from coop_sql_review import cli as climod

    calls = []
    monkeypatch.setattr(climod, "_open_report", lambda path: calls.append(path))
    f = tmp_path / "t.sql"
    f.write_text("SELECT * FROM x;\n", encoding="utf-8")
    report = tmp_path / "review.html"
    # CliRunner is non-interactive, so default (auto) must NOT open a browser.
    CliRunner().invoke(cli, ["check", str(f), "-o", str(report), "--format", "html"])
    assert calls == []


def test_open_flag_forces_open(tmp_path, monkeypatch):
    from coop_sql_review import cli as climod

    calls = []
    monkeypatch.setattr(climod, "_open_report", lambda path: calls.append(path))
    f = tmp_path / "t.sql"
    f.write_text("SELECT * FROM x;\n", encoding="utf-8")
    report = tmp_path / "review.html"
    CliRunner().invoke(cli, ["check", str(f), "-o", str(report), "--format", "html", "--open"])
    assert calls == [report.resolve()]


def test_no_open_flag_suppresses_even_when_interactive(monkeypatch):
    from coop_sql_review import cli as climod

    # Pretend we are interactive so the only thing keeping the browser shut is --no-open.
    monkeypatch.setattr(climod, "_stdio_interactive", lambda: True)
    assert climod._should_open_report("html", False) is False
    assert climod._should_open_report("html", None) is True  # auto opens when interactive
    # The open behavior is HTML-only: a non-HTML format never opens, even with
    # an explicit --open (matches the flag's "open an HTML report" help text).
    assert climod._should_open_report("text", True) is False
    assert climod._should_open_report("markdown", True) is False


def test_upgrade_shows_command_without_applying(monkeypatch):
    from coop_sql_review import upgrade as upmod

    plan = upmod.UpgradePlan("pipx", None, "0.1.0", "latest release is 0.2.0", pip_spec=None)
    monkeypatch.setattr(upmod, "build_plan", lambda *a, **k: plan)
    # If anything tried to apply, it would call subprocess; make that explode.
    monkeypatch.setattr(
        upmod, "apply_plan", lambda *a, **k: (_ for _ in ()).throw(AssertionError("applied!"))
    )
    result = CliRunner().invoke(cli, ["upgrade"])
    assert result.exit_code == 0
    assert "pipx upgrade coop-sql-review" in result.output
    assert "open a new terminal" in result.output


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


def test_interactive_picker_falls_back_without_subdirs(tmp_path):
    from coop_sql_review.cli import _interactive_pick_paths

    (tmp_path / "a.sql").write_text("SELECT 1;\n", encoding="utf-8")
    # No subfolders -> picker returns None so the caller uses the default path.
    assert _interactive_pick_paths(tmp_path) is None


def test_interactive_picker_all_selected_returns_root(tmp_path, monkeypatch):
    from coop_sql_review import cli as climod

    (tmp_path / "silver").mkdir()
    (tmp_path / "gold").mkdir()

    class _FakeCheckbox:
        def __init__(self, *a, **k):
            pass

        def ask(self):  # simulate the user keeping everything checked
            return [tmp_path / "gold", tmp_path / "silver"]

    import questionary

    monkeypatch.setattr(questionary, "checkbox", lambda *a, **k: _FakeCheckbox())
    monkeypatch.setattr(questionary, "Choice", lambda **k: k.get("value"))
    assert climod._interactive_pick_paths(tmp_path) == [tmp_path]  # all -> scan root


def test_rules_command_marks_off_by_default():
    out = CliRunner().invoke(cli, ["rules"]).output
    # the two noisy rules ship but are marked off
    for line in out.splitlines():
        if "SQL-HEADER-COMMENT" in line or "SQL-TABLE-LAYER-NAME" in line:
            assert "off by default" in line
