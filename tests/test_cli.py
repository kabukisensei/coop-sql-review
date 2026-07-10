"""CLI: advisory exit codes, formats, the strict gate, and the rules command.

These exercise the real discovered rule set (engine + all_rules), so they are
the integration check that every rule module imports and runs cleanly.
"""

import json
from pathlib import Path

from click.testing import CliRunner

from coop_sql_review.cli import cli, discover_sql_files

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


def test_strict_help_documents_all_three_gate_conditions():
    # issue #18: a CI author reading --help must be able to predict every exit-2
    # condition — findings, error-severity diagnostics, and zero files checked.
    out = CliRunner().invoke(cli, ["check", "--help"]).output
    idx = out.rindex("--strict")  # the option row (the docstring mentions the flag earlier)
    strict_help = out[idx : idx + 400]
    assert "finding" in strict_help
    assert "error-severity diagnostic" in strict_help
    assert "syntax error" in strict_help
    assert "no files were checked" in strict_help


def test_config_file_is_read_exactly_once_per_run(tmp_path, monkeypatch):
    # issue #18: rules.yml used to be parsed twice (rule config, then a second
    # yaml.safe_load just for `target:`). The single load must serve both.
    f = tmp_path / "t.sql"
    f.write_text("CREATE TABLE s.t (amt SMALLMONEY);\n", encoding="utf-8")
    cfg = tmp_path / "rules.yml"
    cfg.write_text("target: azure-sql\nrules: {}\n", encoding="utf-8")
    reads: list[Path] = []
    original = Path.read_text

    def counting_read_text(self, *args, **kwargs):
        if self.name == "rules.yml":
            reads.append(self)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counting_read_text)
    result = CliRunner().invoke(cli, ["check", str(f), "--config", str(cfg)])
    assert result.exit_code == 0
    assert "SQL-TYPE-MONEY" not in result.output  # the target: key WAS honored...
    assert len(reads) == 1  # ...from the same single read as the rule config


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
    # a NEW logical issue (different object -> different fingerprint) surfaces
    b = tmp_path / "b.sql"
    b.write_text("CREATE VIEW gold.v AS SELECT * FROM u;\n", encoding="utf-8")
    out = CliRunner().invoke(cli, ["check", str(tmp_path), "--baseline", str(bl)]).output
    assert "SQL-NO-SELECT-STAR" in out  # b.sql's finding is new
    assert "b.sql" in out


def test_baseline_suppresses_same_qualified_object_in_another_file(tmp_path):
    # Fingerprints are path-free: the SAME rule + NON-EMPTY object + message in a second
    # file IS the same logical issue, so the baseline suppresses both (by design). Both
    # files define silver.p, so each SELECT * carries object="silver.p".
    # (Object-LESS findings do NOT collapse — see test_suppressions.py; issue #3.)
    body = "CREATE OR ALTER PROCEDURE silver.p AS BEGIN SELECT * FROM t; END\n"
    a = tmp_path / "a.sql"
    a.write_text(body, encoding="utf-8")
    bl = tmp_path / "bl.json"
    CliRunner().invoke(cli, ["check", str(a), "--write-baseline", str(bl)])
    b = tmp_path / "b.sql"
    b.write_text(body, encoding="utf-8")
    out = CliRunner().invoke(cli, ["check", str(tmp_path), "--baseline", str(bl)]).output
    assert "SQL-NO-SELECT-STAR" not in out
    assert "no issues" in out


def test_baseline_does_not_hide_object_less_finding_in_a_new_file(tmp_path):
    # issue #3: a bare SELECT * has object="". Baselining a.sql must NOT suppress the same
    # finding newly introduced in b.sql — the fingerprint now carries the basename, so
    # b.sql's finding is surfaced (the ratchet's whole point).
    a = tmp_path / "a.sql"
    a.write_text("SELECT * FROM t;\n", encoding="utf-8")
    bl = tmp_path / "bl.json"
    CliRunner().invoke(cli, ["check", str(a), "--write-baseline", str(bl)])
    b = tmp_path / "b.sql"
    b.write_text("SELECT * FROM t;\n", encoding="utf-8")
    out = CliRunner().invoke(cli, ["check", str(tmp_path), "--baseline", str(bl)]).output
    assert "SQL-NO-SELECT-STAR" in out  # b.sql's finding is reported, not silently hidden
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


def test_filter_upstream_off_by_default_and_collapsed_when_enabled(tmp_path):
    # issue #17: the rule ships off by default (it drowned the agent channel);
    # opted back in via rules.yml it emits ONE collapsed item per object.
    f = tmp_path / "p.sql"
    f.write_text(
        "CREATE OR ALTER PROCEDURE silver.p AS\n"
        "BEGIN\n"
        "    SELECT a.x FROM a JOIN b ON a.id = b.id WHERE a.f = 1;\n"
        "    SELECT c.y FROM c JOIN d ON c.id = d.id WHERE c.g = 2;\n"
        "END\n",
        encoding="utf-8",
    )
    payload = json.loads(CliRunner().invoke(cli, ["check", str(f), "--format", "json"]).output)
    assert all(a["rule_id"] != "SQL-FILTER-UPSTREAM" for a in payload["agent_review"])
    cfg = tmp_path / "rules.yml"
    cfg.write_text("rules:\n  SQL-FILTER-UPSTREAM:\n    enabled: true\n", encoding="utf-8")
    payload = json.loads(
        CliRunner().invoke(cli, ["check", str(f), "--format", "json", "--config", str(cfg)]).output
    )
    items = [a for a in payload["agent_review"] if a["rule_id"] == "SQL-FILTER-UPSTREAM"]
    assert len(items) == 1
    assert "2 join+WHERE queries" in items[0]["note"]


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
    # The path is announced on STDERR (stdout stays clean for piped reads) even
    # though the run is non-interactive — an agent reads the file we name.
    # Asserting on result.stderr (not the merged result.output) guards the
    # stdout/stderr contract: a dropped err=True would fail here.
    assert "HTML report written to" in result.stderr
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
    from coop_review_core import cliutils

    from coop_sql_review import cli as climod

    # Pretend we are interactive so the only thing keeping the browser shut is --no-open.
    # _should_open_report is core's should_open_report, which consults core's own
    # stdio_interactive — patch it there (climod._stdio_interactive is the same function,
    # but core's internal call resolves in the core module).
    monkeypatch.setattr(cliutils, "stdio_interactive", lambda: True)
    assert climod._should_open_report("html", False) is False
    assert climod._should_open_report("html", None) is True  # auto opens when interactive
    # The open behavior is HTML-only: a non-HTML format never opens, even with
    # an explicit --open (matches the flag's "open an HTML report" help text).
    assert climod._should_open_report("text", True) is False
    assert climod._should_open_report("markdown", True) is False


def test_upgrade_shows_command_without_applying(monkeypatch):
    from coop_sql_review import upgrade as upmod

    plan = upmod.UpgradePlan(
        package_name="coop-sql-review",
        install_method="pipx",
        checkout=None,
        tool_installed="0.1.0",
        tool_note="latest release is 0.2.0",
    )
    monkeypatch.setattr(upmod, "build_plan", lambda *a, **k: plan)
    # If anything tried to apply, it would call subprocess; make that explode.
    monkeypatch.setattr(
        upmod, "apply_plan", lambda *a, **k: (_ for _ in ()).throw(AssertionError("applied!"))
    )
    result = CliRunner().invoke(cli, ["upgrade"])
    assert result.exit_code == 0
    assert "pipx upgrade coop-sql-review" in result.output
    # core 0.4.0's unified closing message (cliutils.run_upgrade)
    assert "This tool does not update itself. To update, exit coop-sql-review and run:" in result.output


def test_markdown_format(tmp_path):
    f = tmp_path / "t.sql"
    f.write_text("SELECT * FROM x;\n", encoding="utf-8")
    out = CliRunner().invoke(cli, ["check", str(f), "--format", "markdown"]).output
    assert out.startswith("# coop-sql-review report")
    assert "## Findings" in out
    assert "SQL-NO-SELECT-STAR" in out


def test_html_format(tmp_path):
    # --format html always writes a file (here via -o); never a stdout dump.
    f = tmp_path / "t.sql"
    f.write_text("SELECT * FROM x;\n", encoding="utf-8")
    report = tmp_path / "r.html"
    result = CliRunner().invoke(cli, ["check", str(f), "--format", "html", "-o", str(report)])
    assert result.exit_code == 0
    out = report.read_text(encoding="utf-8")
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


def test_html_and_md_extra_reports_compose_with_text(tmp_path):
    # --html/--md are EXTRA sinks: the main text report still prints to the console,
    # AND both files are written.
    html = tmp_path / "r.html"
    md = tmp_path / "r.md"
    result = CliRunner().invoke(cli, ["check", FIXTURE, "--html", str(html), "--md", str(md)])
    assert result.exit_code == 0
    assert html.read_text(encoding="utf-8").startswith("<!DOCTYPE html>")
    assert md.read_text(encoding="utf-8").startswith("# coop-sql-review report")
    # the main text report still went to the screen
    assert "SQL-NO-SELECT-STAR" in result.output


def test_config_ignore_suppresses_finding(tmp_path):
    payload = json.loads(CliRunner().invoke(cli, ["check", FIXTURE, "--format", "json"]).output)
    fp = payload["findings"][0]["fingerprint"]
    cfg = tmp_path / "rules.yml"
    cfg.write_text(f"ignore:\n  - fingerprint: {fp}\n", encoding="utf-8")
    out = CliRunner().invoke(cli, ["check", FIXTURE, "--config", str(cfg)]).output
    assert "SQL-NO-SELECT-STAR" not in out
    assert "no issues found" in out


def test_stale_ignore_entry_warns(tmp_path):
    cfg = tmp_path / "rules.yml"
    cfg.write_text("ignore:\n  - fingerprint: deadbeefdead\n", encoding="utf-8")
    out = CliRunner().invoke(cli, ["check", FIXTURE, "--config", str(cfg)]).output
    assert "ignore:" in out and "no longer" in out


def test_save_ignores_writes_then_silences(tmp_path, monkeypatch):
    from coop_sql_review import cli as climod
    from coop_sql_review.standards import RuleConfig

    class _FakeCheckbox:
        def __init__(self, *a, **k):
            # capture the finding values offered as choices, so .ask() can return them all
            self._values = [c for c in k.get("choices", [])]

        def ask(self):  # simulate the user checking every offered finding
            return self._values

    import questionary

    monkeypatch.setattr(questionary, "checkbox", lambda *a, **k: _FakeCheckbox(*a, **k))
    monkeypatch.setattr(questionary, "Choice", lambda **k: k.get("value"))
    monkeypatch.setattr(climod, "_stdio_interactive", lambda: True)

    cfg = tmp_path / "rules.yml"
    first = CliRunner().invoke(cli, ["check", FIXTURE, "--config", str(cfg), "--save-ignores"])
    assert first.exit_code == 0
    assert cfg.is_file()
    assert RuleConfig.load(cfg).ignored_fingerprints  # a fingerprint was recorded

    out = CliRunner().invoke(cli, ["check", FIXTURE, "--config", str(cfg)]).output
    assert "SQL-NO-SELECT-STAR" not in out  # now silenced on the re-run


def test_save_ignores_no_terminal_writes_nothing(tmp_path, monkeypatch):
    from coop_sql_review import cli as climod

    monkeypatch.setattr(climod, "_stdio_interactive", lambda: False)
    cfg = tmp_path / "rules.yml"
    result = CliRunner().invoke(cli, ["check", FIXTURE, "--config", str(cfg), "--save-ignores"])
    assert result.exit_code == 0
    assert "needs an interactive terminal" in result.output
    assert not cfg.exists()  # nothing written off-TTY


def test_cwd_rules_yml_is_auto_discovered(tmp_path, monkeypatch):
    # A rules.yml in the working directory is picked up with no --config flag.
    monkeypatch.chdir(tmp_path)
    (tmp_path / "q.sql").write_text("SELECT * FROM t;\n", encoding="utf-8")
    payload = json.loads(CliRunner().invoke(cli, ["check", "q.sql", "--format", "json"]).output)
    fp = payload["findings"][0]["fingerprint"]
    (tmp_path / "rules.yml").write_text(f"ignore:\n  - fingerprint: {fp}\n", encoding="utf-8")
    out = CliRunner().invoke(cli, ["check", "q.sql"]).output  # no --config
    assert "SQL-NO-SELECT-STAR" not in out  # auto-discovered ignore silenced it


# --- rules.yml load problems: friendly one-line errors (exit 2), never a traceback ---


def test_config_invalid_yaml_is_friendly_error(tmp_path):
    cfg = tmp_path / "rules.yml"
    cfg.write_text("rules: [unclosed\n", encoding="utf-8")
    result = CliRunner().invoke(cli, ["check", FIXTURE, "--config", str(cfg)])
    assert result.exit_code == 2
    assert "could not load config" in result.output and "rules.yml" in result.output
    assert "Traceback" not in result.output


def test_config_tab_in_yaml_is_friendly_error(tmp_path):
    cfg = tmp_path / "rules.yml"
    cfg.write_text("rules:\n\tSQL-NO-SELECT-STAR: {}\n", encoding="utf-8")
    result = CliRunner().invoke(cli, ["check", FIXTURE, "--config", str(cfg)])
    assert result.exit_code == 2
    assert "could not load config" in result.output
    # the one-line contract: a YAML error's multi-line context is flattened
    assert "\n" not in result.output.strip().split("Error: ", 1)[-1]


def test_config_non_mapping_root_is_friendly_error(tmp_path):
    cfg = tmp_path / "rules.yml"
    cfg.write_text("- just\n- a list\n", encoding="utf-8")
    result = CliRunner().invoke(cli, ["check", FIXTURE, "--config", str(cfg)])
    assert result.exit_code == 2
    assert "could not load config" in result.output and "mapping" in result.output


def test_config_rules_as_list_is_friendly_error(tmp_path):
    cfg = tmp_path / "rules.yml"
    cfg.write_text("rules:\n  - SQL-NO-SELECT-STAR\n", encoding="utf-8")
    result = CliRunner().invoke(cli, ["check", FIXTURE, "--config", str(cfg)])
    assert result.exit_code == 2
    assert "rules:" in result.output and "mapping" in result.output


def test_config_unknown_severity_is_friendly_error(tmp_path):
    cfg = tmp_path / "rules.yml"
    cfg.write_text("rules:\n  SQL-NO-SELECT-STAR:\n    severity: critical\n", encoding="utf-8")
    result = CliRunner().invoke(cli, ["check", FIXTURE, "--config", str(cfg)])
    assert result.exit_code == 2
    assert "invalid severity 'critical'" in result.output
    assert "Traceback" not in result.output


def test_config_non_utf8_is_friendly_error(tmp_path):
    cfg = tmp_path / "rules.yml"
    cfg.write_bytes("rules:\n  SQL-NO-SELECT-STAR:\n    enabled: false\n".encode("utf-16-le"))
    result = CliRunner().invoke(cli, ["check", FIXTURE, "--config", str(cfg)])
    assert result.exit_code == 2
    assert "could not load config" in result.output and "UTF-8" in result.output


def test_autodiscovered_bad_config_is_friendly_error_too(tmp_path, monkeypatch):
    # A stray rules.yml in the cwd (no --config flag) gets the same treatment.
    monkeypatch.chdir(tmp_path)
    (tmp_path / "rules.yml").write_text("rules: [unclosed\n", encoding="utf-8")
    (tmp_path / "q.sql").write_text("SELECT a FROM t;\n", encoding="utf-8")
    result = CliRunner().invoke(cli, ["check", "q.sql"])
    assert result.exit_code == 2
    assert "could not load config" in result.output


# --- an EXPLICIT --config path that doesn't exist is an error; discovery stays lenient ---


def test_explicit_config_path_missing_is_error(tmp_path):
    result = CliRunner().invoke(cli, ["check", FIXTURE, "--config", str(tmp_path / "nope.yml")])
    assert result.exit_code == 2
    assert "config file not found" in result.output


def test_config_autodiscovery_absence_is_silent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # no rules.yml here or beside the standards
    (tmp_path / "q.sql").write_text("SELECT a FROM t;\n", encoding="utf-8")
    result = CliRunner().invoke(cli, ["check", "q.sql"])
    assert result.exit_code == 0
    assert "config" not in result.output.lower()


# --- unified config discovery (core 0.4.0 / coop-review-core#12): env var,
#     tool-named config file, git-style parent walk-up, rules.yml deprecation ---

_DISABLE_STAR_RULE = "rules:\n  SQL-NO-SELECT-STAR:\n    enabled: false\n"


def test_env_var_config_is_honored(tmp_path, monkeypatch):
    f = tmp_path / "q.sql"
    f.write_text("SELECT * FROM t;\n", encoding="utf-8")
    cfg = tmp_path / "team-config.yml"
    cfg.write_text(_DISABLE_STAR_RULE, encoding="utf-8")
    monkeypatch.setenv("COOP_SQL_REVIEW_CONFIG", str(cfg))
    out = CliRunner().invoke(cli, ["check", str(f)]).output
    assert "SQL-NO-SELECT-STAR" not in out  # the env-named config disabled the rule


def test_env_var_config_missing_is_usage_error(tmp_path, monkeypatch):
    monkeypatch.setenv("COOP_SQL_REVIEW_CONFIG", str(tmp_path / "nope.yml"))
    result = CliRunner().invoke(cli, ["check", FIXTURE])
    assert result.exit_code == 2  # a misconfiguration, never a silent fallback
    assert "COOP_SQL_REVIEW_CONFIG" in result.output and "not found" in result.output


def test_explicit_config_beats_env_var(tmp_path, monkeypatch):
    f = tmp_path / "q.sql"
    f.write_text("SELECT * FROM t;\n", encoding="utf-8")
    env_cfg = tmp_path / "env.yml"
    env_cfg.write_text(_DISABLE_STAR_RULE, encoding="utf-8")
    flag_cfg = tmp_path / "flag.yml"
    flag_cfg.write_text("rules: {}\n", encoding="utf-8")
    monkeypatch.setenv("COOP_SQL_REVIEW_CONFIG", str(env_cfg))
    out = CliRunner().invoke(cli, ["check", str(f), "--config", str(flag_cfg)]).output
    assert "SQL-NO-SELECT-STAR" in out  # --config won, so the rule stayed enabled


def test_tool_named_config_preferred_and_shadow_note_on_stderr(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "q.sql").write_text("SELECT * FROM t;\n", encoding="utf-8")
    (tmp_path / "coop-sql-review.yml").write_text(_DISABLE_STAR_RULE, encoding="utf-8")
    (tmp_path / "rules.yml").write_text("rules: {}\n", encoding="utf-8")
    result = CliRunner().invoke(cli, ["check", "q.sql"])
    assert result.exit_code == 0
    assert "SQL-NO-SELECT-STAR" not in result.stdout  # the tool-named file won
    assert "shadowed" in result.stderr  # the note is a stderr one-liner
    assert "SQL-NO-SELECT-STAR" not in result.stderr


def test_rules_yml_discovery_emits_deprecation_note_on_stderr(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "q.sql").write_text("SELECT a FROM t;\n", encoding="utf-8")
    (tmp_path / "rules.yml").write_text("rules: {}\n", encoding="utf-8")
    result = CliRunner().invoke(cli, ["check", "q.sql"])
    assert result.exit_code == 0  # rules.yml keeps working...
    assert "deprecated shared name" in result.stderr  # ...with a rename nudge
    assert "coop-sql-review.yml" in result.stderr
    assert "deprecated" not in result.stdout  # never pollutes the report stream


def test_config_discovered_in_a_parent_directory(tmp_path, monkeypatch):
    (tmp_path / "coop-sql-review.yml").write_text(_DISABLE_STAR_RULE, encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "q.sql").write_text("SELECT * FROM t;\n", encoding="utf-8")
    monkeypatch.chdir(sub)  # git-style walk-up finds the parent's config
    out = CliRunner().invoke(cli, ["check", "q.sql"]).output
    assert "SQL-NO-SELECT-STAR" not in out


def test_walk_up_never_crosses_a_git_root(tmp_path, monkeypatch):
    # A config OUTSIDE the repository must never silently apply.
    (tmp_path / "rules.yml").write_text(_DISABLE_STAR_RULE, encoding="utf-8")
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    sub = repo / "sql"
    sub.mkdir()
    (sub / "q.sql").write_text("SELECT * FROM t;\n", encoding="utf-8")
    monkeypatch.chdir(sub)
    out = CliRunner().invoke(cli, ["check", "q.sql"]).output
    assert "SQL-NO-SELECT-STAR" in out  # the outside-the-repo config did NOT apply


# --- --write-baseline to a bad path: friendly error, not a traceback ---


def test_write_baseline_to_missing_dir_is_friendly_error(tmp_path):
    f = tmp_path / "q.sql"
    f.write_text("SELECT * FROM t;\n", encoding="utf-8")
    target = tmp_path / "no-such-dir" / "base.json"
    result = CliRunner().invoke(cli, ["check", str(f), "--write-baseline", str(target)])
    assert result.exit_code == 1
    assert "could not write baseline" in result.output
    assert "Traceback" not in result.output


# --- zero .sql files: the machine contract still renders; --strict fails ---


def test_zero_files_still_emits_the_json_contract(tmp_path):
    result = CliRunner().invoke(cli, ["check", str(tmp_path), "--format", "json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["files_checked"] == 0
    assert payload["verdict"]["clean"] is True
    assert any(d["category"] == "scan_empty" for d in payload["diagnostics"])
    assert "No .sql files found" in result.stderr


def test_zero_files_missing_path_is_machine_visible(tmp_path):
    missing = tmp_path / "no-such-dir"
    result = CliRunner().invoke(cli, ["check", str(missing), "--format", "json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["files_checked"] == 0
    diags = [d for d in payload["diagnostics"] if d["category"] == "scan_empty"]
    assert len(diags) == 1
    assert "path not found" in diags[0]["message"]
    assert missing.as_posix() in diags[0]["file"]


def test_strict_fails_on_zero_files(tmp_path):
    # A typo'd path must not pass a --strict CI gate as silently clean.
    empty = CliRunner().invoke(cli, ["check", str(tmp_path), "--strict"])
    assert empty.exit_code == 2
    typo = CliRunner().invoke(cli, ["check", str(tmp_path / "nope"), "--strict"])
    assert typo.exit_code == 2


def test_zero_files_report_still_reaches_output_sink(tmp_path):
    out = tmp_path / "r.json"
    result = CliRunner().invoke(cli, ["check", str(tmp_path), "--format", "json", "-o", str(out)])
    assert result.exit_code == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["files_checked"] == 0


# --- --format html always writes a file (default name when -o is omitted) ---


def test_html_format_without_output_writes_default_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "t.sql").write_text("SELECT * FROM x;\n", encoding="utf-8")
    result = CliRunner().invoke(cli, ["check", "t.sql", "--format", "html"])
    assert result.exit_code == 0
    target = tmp_path / "coop-sql-review-report.html"
    assert target.is_file()
    assert target.read_text(encoding="utf-8").startswith("<!DOCTYPE html>")
    assert "<!DOCTYPE html>" not in result.stdout  # no raw HTML dump to the screen
    assert "HTML report written to" in result.stderr
    assert target.resolve().as_posix() in result.stderr


def test_html_default_file_open_gating(tmp_path, monkeypatch):
    from coop_sql_review import cli as climod

    calls = []
    monkeypatch.setattr(climod, "_open_report", lambda path: calls.append(path))
    monkeypatch.chdir(tmp_path)
    (tmp_path / "t.sql").write_text("SELECT * FROM x;\n", encoding="utf-8")
    CliRunner().invoke(cli, ["check", "t.sql", "--format", "html"])
    assert calls == []  # non-interactive auto -> never opens a browser
    CliRunner().invoke(cli, ["check", "t.sql", "--format", "html", "--open"])
    assert calls == [(tmp_path / "coop-sql-review-report.html").resolve()]


# --- discover_sql_files: the funnel for every check run (silently scanning
#     fewer files would look identical to a clean estate) ---


def test_discover_finds_uppercase_extension(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.sql").write_text("SELECT 1;\n", encoding="utf-8")
    (tmp_path / "sub" / "B.SQL").write_text("SELECT 1;\n", encoding="utf-8")
    found = discover_sql_files((str(tmp_path),))
    assert sorted(p.name for p in found) == ["B.SQL", "a.sql"]


def test_discover_skips_hidden_directories(tmp_path):
    for hidden in (".git", ".hidden"):
        deep = tmp_path / hidden / "deep"
        deep.mkdir(parents=True)
        (deep / "x.sql").write_text("SELECT 1;\n", encoding="utf-8")
    (tmp_path / "keep.sql").write_text("SELECT 1;\n", encoding="utf-8")
    found = discover_sql_files((str(tmp_path),))
    assert [p.name for p in found] == ["keep.sql"]


def test_discover_dedups_overlapping_roots(tmp_path):
    # The same file reached via a dir, a nested dir, AND an explicit file path
    # is counted exactly once.
    sub = tmp_path / "sub"
    sub.mkdir()
    f = sub / "a.sql"
    f.write_text("SELECT 1;\n", encoding="utf-8")
    found = discover_sql_files((str(tmp_path), str(sub), str(f)))
    assert len(found) == 1
    assert found[0].name == "a.sql"


def test_discover_takes_explicit_file_as_is(tmp_path):
    # A file passed explicitly is used even without a .sql extension.
    f = tmp_path / "script.txt"
    f.write_text("SELECT 1;\n", encoding="utf-8")
    assert discover_sql_files((str(f),)) == [f]


def test_discover_order_is_deterministic(tmp_path):
    for name in ("b.sql", "a.sql", "c.sql"):
        (tmp_path / name).write_text("SELECT 1;\n", encoding="utf-8")
    found = discover_sql_files((str(tmp_path),))
    assert [p.name for p in found] == ["a.sql", "b.sql", "c.sql"]


# --- fingerprints are cwd-independent: baselines and rules.yml ignores keep
#     matching when the tool runs from a different folder (or machine) ---


def test_fingerprint_identical_across_cwds(tmp_path, monkeypatch):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "q.sql").write_text("SELECT * FROM t;\n", encoding="utf-8")
    monkeypatch.chdir(proj)  # display path: q.sql
    inside = json.loads(CliRunner().invoke(cli, ["check", ".", "--format", "json"]).output)
    monkeypatch.chdir(tmp_path)  # display path: proj/q.sql
    outside = json.loads(CliRunner().invoke(cli, ["check", "proj", "--format", "json"]).output)
    assert inside["findings"][0]["file"] != outside["findings"][0]["file"]  # paths DID differ
    assert inside["findings"][0]["fingerprint"] == outside["findings"][0]["fingerprint"]


def test_baseline_written_from_one_cwd_suppresses_from_another(tmp_path, monkeypatch):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "q.sql").write_text("SELECT * FROM t;\n", encoding="utf-8")
    bl = tmp_path / "bl.json"
    monkeypatch.chdir(proj)
    CliRunner().invoke(cli, ["check", ".", "--write-baseline", str(bl)])
    monkeypatch.chdir(tmp_path)  # a scheduled task / CI step with another working dir
    payload = json.loads(
        CliRunner().invoke(cli, ["check", "proj", "--baseline", str(bl), "--format", "json"]).output
    )
    assert payload["findings"] == []
    assert not any(d["category"] == "baseline_stale" for d in payload["diagnostics"])


# --- the suppression pipeline covers agent_review items exactly like findings ---

_MERGE_SQL = "MERGE silver.t AS x USING silver.s AS s ON x.id = s.id\nWHEN MATCHED THEN UPDATE SET x.a = 1;\n"


def test_inline_ignore_suppresses_agent_review_item(tmp_path):
    f = tmp_path / "m.sql"
    f.write_text("-- coop-sql-review:ignore SQL-UPSERT-CHOICE\n" + _MERGE_SQL, encoding="utf-8")
    payload = json.loads(CliRunner().invoke(cli, ["check", str(f), "--format", "json"]).output)
    assert all(a["rule_id"] != "SQL-UPSERT-CHOICE" for a in payload["agent_review"])


def test_inline_ignore_other_rule_keeps_agent_review_item(tmp_path):
    # Guard: the directive is rule-targeted, not a blanket agent-review mute.
    f = tmp_path / "m.sql"
    f.write_text("-- coop-sql-review:ignore SQL-NO-SELECT-STAR\n" + _MERGE_SQL, encoding="utf-8")
    payload = json.loads(CliRunner().invoke(cli, ["check", str(f), "--format", "json"]).output)
    assert any(a["rule_id"] == "SQL-UPSERT-CHOICE" for a in payload["agent_review"])


def test_baseline_suppresses_agent_review_item(tmp_path):
    f = tmp_path / "m.sql"
    f.write_text(_MERGE_SQL, encoding="utf-8")
    bl = tmp_path / "bl.json"
    CliRunner().invoke(cli, ["check", str(f), "--write-baseline", str(bl)])
    payload = json.loads(
        CliRunner().invoke(cli, ["check", str(f), "--baseline", str(bl), "--format", "json"]).output
    )
    assert payload["agent_review"] == []
    # A baseline entry matching only an agent item is NOT stale.
    assert not any(d["category"] == "baseline_stale" for d in payload["diagnostics"])


def test_config_ignore_suppresses_agent_review_item_and_is_not_stale(tmp_path):
    f = tmp_path / "m.sql"
    f.write_text(_MERGE_SQL, encoding="utf-8")
    payload = json.loads(CliRunner().invoke(cli, ["check", str(f), "--format", "json"]).output)
    fps = [a["fingerprint"] for a in payload["agent_review"] if a["rule_id"] == "SQL-UPSERT-CHOICE"]
    assert fps  # the MERGE was detected before suppression
    cfg = tmp_path / "rules.yml"
    cfg.write_text(f"ignore:\n  - fingerprint: {fps[0]}\n", encoding="utf-8")
    payload2 = json.loads(
        CliRunner().invoke(cli, ["check", str(f), "--config", str(cfg), "--format", "json"]).output
    )
    assert all(a["rule_id"] != "SQL-UPSERT-CHOICE" for a in payload2["agent_review"])
    # ignore_stale semantics: an ignore matching only an agent item is NOT stale.
    assert not any(d["category"] == "ignore_stale" for d in payload2["diagnostics"])


def test_config_write_path_follows_read_config_and_guards_bundled_dir(tmp_path):
    # issue #7: --save-ignores must write to the config the run READ from, not a new
    # ./rules.yml that would shadow it — and never inside the installed package.
    from coop_sql_review import cli as climod

    assert climod._config_write_path("x/rules.yml", tmp_path / "whatever.yml") == Path("x/rules.yml")
    existing = tmp_path / "rules.yml"
    existing.write_text("rules: {}\n", encoding="utf-8")
    assert climod._config_write_path(None, existing) == existing  # read-config outside pkg -> write back
    assert climod._config_write_path(None, tmp_path / "nope.yml") == Path.cwd() / "rules.yml"  # none -> cwd
    inside_pkg = Path(climod.__file__).resolve()  # a real file INSIDE the package
    assert climod._config_write_path(None, inside_pkg) == Path.cwd() / "rules.yml"  # bundled dir guarded


def test_save_ignores_writes_back_to_read_config_not_a_shadowing_cwd_file(tmp_path, monkeypatch):
    # Team layout: standards + rules.yml beside it; cwd is elsewhere with NO ./rules.yml.
    from coop_sql_review import cli as climod

    std = tmp_path / "standards.md"
    std.write_text("# standards\n", encoding="utf-8")
    team_cfg = tmp_path / "rules.yml"  # default_config_path(std) resolves here
    team_cfg.write_text("rules:\n  SQL-NO-SELECT-STAR:\n    severity: info\n", encoding="utf-8")
    sqlf = tmp_path / "q.sql"
    sqlf.write_text("SELECT * FROM t;\n", encoding="utf-8")
    other = tmp_path / "elsewhere"
    other.mkdir()
    monkeypatch.chdir(other)  # so a ./rules.yml is NOT discovered
    # Pretend interactive and auto-select every finding the picker would offer.
    monkeypatch.setattr(climod, "_stdio_interactive", lambda: True)
    monkeypatch.setattr(climod, "_pick_findings_to_ignore", lambda findings: list(findings))

    res = CliRunner().invoke(cli, ["check", str(sqlf), "--standards", str(std), "--save-ignores"])
    assert res.exit_code == 0
    assert not (other / "rules.yml").exists()  # NOT a new shadowing cwd file
    text = team_cfg.read_text(encoding="utf-8")
    assert "ignore" in text  # add_ignores appended the ignore list...
    assert "severity: info" in text  # ...preserving the pre-existing override
    # A subsequent run reads the team config and honors BOTH: the finding is now silenced.
    out2 = CliRunner().invoke(cli, ["check", str(sqlf), "--standards", str(std)]).output
    assert "SQL-NO-SELECT-STAR" not in out2


def test_target_azure_sql_skips_fabric_only_type_rules(tmp_path):
    # Azure serverless SQL supports smallmoney/xml, so --target azure-sql skips the
    # Fabric-DW-only type rules; the default (fabric-dw) flags them.
    f = tmp_path / "t.sql"
    f.write_text("CREATE TABLE s.t (amt SMALLMONEY, doc XML);\n", encoding="utf-8")
    default_out = CliRunner().invoke(cli, ["check", str(f)]).output
    assert "SQL-TYPE-MONEY" in default_out and "SQL-TYPE-UNSUPPORTED" in default_out
    azure_out = CliRunner().invoke(cli, ["check", str(f), "--target", "azure-sql"]).output
    assert "SQL-TYPE-MONEY" not in azure_out and "SQL-TYPE-UNSUPPORTED" not in azure_out


def test_target_azure_sql_skips_ctas_derived_type_findings(tmp_path):
    # issue #20: CTAS-synthesized columns feed the same Fabric-only type rules,
    # so they too vanish under --target azure-sql.
    f = tmp_path / "t.sql"
    f.write_text(
        "CREATE TABLE silver.t AS SELECT CAST(a AS money) AS Amount FROM s.x;\n",
        encoding="utf-8",
    )
    default_out = CliRunner().invoke(cli, ["check", str(f)]).output
    assert "SQL-TYPE-MONEY" in default_out
    azure_out = CliRunner().invoke(cli, ["check", str(f), "--target", "azure-sql"]).output
    assert "SQL-TYPE-MONEY" not in azure_out


def test_target_azure_sql_skips_alter_column_and_query_label(tmp_path):
    # ALTER COLUMN is plain GA T-SQL on Azure SQL, and OPTION(LABEL=...) is a
    # Fabric/Synapse-only hint — so --target azure-sql skips SQL-NO-ALTER-COLUMN
    # and SQL-QUERY-LABEL entirely (issue #12). The config enables the off-by-default
    # SQL-QUERY-LABEL, proving the enable override is honored under fabric-dw but the
    # target filter still wins under azure-sql (filter runs after apply_config).
    f = tmp_path / "t.sql"
    f.write_text(
        "ALTER TABLE silver.t ALTER COLUMN c INT NOT NULL;\nINSERT INTO gold.t SELECT a FROM silver.s;\n",
        encoding="utf-8",
    )
    cfg = tmp_path / "rules.yml"
    cfg.write_text("rules:\n  SQL-QUERY-LABEL:\n    enabled: true\n", encoding="utf-8")
    fabric_out = CliRunner().invoke(cli, ["check", str(f), "--config", str(cfg)]).output
    assert "SQL-NO-ALTER-COLUMN" in fabric_out and "SQL-QUERY-LABEL" in fabric_out
    azure_out = (
        CliRunner().invoke(cli, ["check", str(f), "--config", str(cfg), "--target", "azure-sql"]).output
    )
    assert "SQL-NO-ALTER-COLUMN" not in azure_out and "SQL-QUERY-LABEL" not in azure_out


def test_rules_json_targets_for_fabric_gated_rules():
    # The issue-#12 gating is visible in the machine rules listing.
    res = CliRunner().invoke(cli, ["rules", "--format", "json"])
    payload = json.loads(res.output)
    for rule_id in ("SQL-NO-ALTER-COLUMN", "SQL-QUERY-LABEL"):
        rule = next(r for r in payload if r["id"] == rule_id)
        assert rule["targets"] == ["fabric-dw"], rule_id


def test_target_from_rules_yml_is_honored(tmp_path):
    f = tmp_path / "t.sql"
    f.write_text("CREATE TABLE s.t (amt SMALLMONEY);\n", encoding="utf-8")
    cfg = tmp_path / "rules.yml"
    cfg.write_text("target: azure-sql\n", encoding="utf-8")
    out = CliRunner().invoke(cli, ["check", str(f), "--config", str(cfg)]).output
    assert "SQL-TYPE-MONEY" not in out  # rules.yml target: azure-sql skipped the rule


def test_invalid_target_in_rules_yml_is_usage_error(tmp_path):
    f = tmp_path / "t.sql"
    f.write_text("SELECT 1;\n", encoding="utf-8")
    cfg = tmp_path / "rules.yml"
    cfg.write_text("target: sqlite\nrules: {}\n", encoding="utf-8")
    res = CliRunner().invoke(cli, ["check", str(f), "--config", str(cfg)])
    assert res.exit_code == 2
    assert "invalid" in res.output.lower() and "target" in res.output.lower()


def test_rules_json_includes_targets():
    res = CliRunner().invoke(cli, ["rules", "--format", "json"])
    payload = json.loads(res.output)
    unsupported = next(r for r in payload if r["id"] == "SQL-TYPE-UNSUPPORTED")
    assert unsupported["targets"] == ["fabric-dw"]
    # A universal rule lists both targets.
    star = next(r for r in payload if r["id"] == "SQL-NO-SELECT-STAR")
    assert set(star["targets"]) == {"fabric-dw", "azure-sql"}
