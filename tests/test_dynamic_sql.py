"""Dynamic SQL is never a silent blind spot (issue #19).

`mask_noncode` blanks string-literal content and the AST sees `EXEC('...')` as
an opaque argument, so statements built in strings are invisible to every rule.
The invariant (AGENTS.md, error handling) is that such a coverage gap must
surface: the parser emits one `dynamic_sql` warning diagnostic per
dynamic-execution site, tunable via the rules.yml `dynamic_sql: error|warning|off`
knob (same shape as `syntax_errors`).
"""

from __future__ import annotations

import json

from click.testing import CliRunner

from coop_sql_review.cli import cli
from coop_sql_review.diagnostics import DYNAMIC_SQL, SYNTAX_ERROR
from coop_sql_review.parser import parse_sql


def _dynamic(sql: str):
    return [d for d in parse_sql("t.sql", sql).diagnostics if d.category == DYNAMIC_SQL]


def test_exec_string_literal_is_surfaced_with_file_and_line():
    # The issue's sample: previously ZERO findings and ZERO diagnostics.
    diags = _dynamic("SELECT 1;\nEXEC('ALTER TABLE silver.dim_x ALTER COLUMN c varchar(500)');\n")
    assert len(diags) == 1
    assert diags[0].file == "t.sql"
    assert diags[0].line == 2
    assert diags[0].severity == "warning"
    assert "not analyzed" in diags[0].message
    assert diags[0].message.isascii()


def test_exec_variable_is_surfaced():
    assert len(_dynamic("EXEC(@sql);")) == 1


def test_execute_long_form_is_surfaced():
    assert len(_dynamic("EXECUTE (@sql);")) == 1


def test_sp_executesql_is_surfaced_once():
    # `EXEC sp_executesql N'...'` must yield ONE diagnostic (the EXEC has no
    # paren, so only the sp_executesql pattern matches).
    diags = _dynamic("EXEC sp_executesql N'SELECT * FROM t', N'@p int', @p = 1;")
    assert len(diags) == 1


def test_bare_sp_executesql_is_surfaced():
    # sp_executesql also works without a leading EXEC.
    assert len(_dynamic("sp_executesql @sql;")) == 1


def test_procedure_invocation_is_not_flagged():
    # Non-dynamic EXEC (a proc call) has no paren after the keyword.
    assert _dynamic("EXEC silver.usp_load_dim @process_date = '2026-01-01';") == []
    assert _dynamic("EXEC @rc = silver.usp_load_dim;") == []


def test_mentions_in_comments_and_strings_are_not_flagged():
    # The scan runs over the masked text, so prose can't trip it.
    assert _dynamic("-- never EXEC('...') here\nSELECT 1;") == []
    assert _dynamic("SELECT 'call sp_executesql later' AS note;") == []


def test_concatenated_exec_is_parse_degraded_not_syntax_error():
    # `EXEC('...' + @var)` is valid T-SQL sqlglot can't parse ("Expecting )"),
    # and used to be misreported as a genuine syntax_error (which would trip
    # --strict on working estate SQL). It is a grammar gap + a dynamic site.
    parsed = parse_sql("t.sql", "EXECUTE('SELECT 1 FROM x WHERE a = 1' + @more);")
    categories = [d.category for d in parsed.diagnostics]
    assert SYNTAX_ERROR not in categories
    assert "parse_degraded" in categories
    assert DYNAMIC_SQL in categories


# --- CLI: knob + report surfaces ---------------------------------------------


def _write(tmp_path, sql):
    f = tmp_path / "d.sql"
    f.write_text(sql, encoding="utf-8")
    return f


def test_dynamic_sql_appears_in_console_json_and_log(tmp_path):
    f = _write(tmp_path, "EXEC(@sql);\n")
    log = tmp_path / "diag.log"
    res = CliRunner().invoke(cli, ["check", str(f), "--log-file", str(log)])
    assert res.exit_code == 0
    assert "dynamic_sql" in res.output  # console diagnostics section
    payload = json.loads(CliRunner().invoke(cli, ["check", str(f), "--format", "json"]).output)
    dyn = [d for d in payload["diagnostics"] if d["category"] == DYNAMIC_SQL]
    assert len(dyn) == 1 and dyn[0]["severity"] == "warning"
    assert json.dumps(payload).isascii()  # machine output stays ASCII
    assert "dynamic_sql" in log.read_text(encoding="utf-8")


def test_dynamic_sql_off_knob_drops_the_diagnostic(tmp_path):
    f = _write(tmp_path, "EXEC(@sql);\n")
    cfg = tmp_path / "rules.yml"
    cfg.write_text("dynamic_sql: off\n", encoding="utf-8")
    out = CliRunner().invoke(cli, ["check", str(f), "--config", str(cfg), "--format", "json"]).output
    payload = json.loads(out)
    assert all(d["category"] != DYNAMIC_SQL for d in payload["diagnostics"])


def test_dynamic_sql_error_knob_promotes_and_gates_strict(tmp_path):
    f = _write(tmp_path, "EXEC(@sql);\n")
    cfg = tmp_path / "rules.yml"
    cfg.write_text("dynamic_sql: error\n", encoding="utf-8")
    payload = json.loads(
        CliRunner().invoke(cli, ["check", str(f), "--config", str(cfg), "--format", "json"]).output
    )
    dyn = [d for d in payload["diagnostics"] if d["category"] == DYNAMIC_SQL]
    assert dyn and all(d["severity"] == "error" for d in dyn)
    # error-severity diagnostics trip the --strict gate
    res = CliRunner().invoke(cli, ["check", str(f), "--config", str(cfg), "--strict"])
    assert res.exit_code == 2


def test_dynamic_sql_invalid_knob_is_a_usage_error(tmp_path):
    f = _write(tmp_path, "SELECT 1;\n")
    cfg = tmp_path / "rules.yml"
    cfg.write_text("dynamic_sql: loud\n", encoding="utf-8")
    res = CliRunner().invoke(cli, ["check", str(f), "--config", str(cfg)])
    assert res.exit_code == 2
    assert "dynamic_sql" in res.output


def test_dynamic_sql_default_does_not_trip_strict(tmp_path):
    # Default severity is warning — advisory; --strict must not fail on it
    # (it gates on findings and ERROR-severity diagnostics only).
    f = _write(tmp_path, "EXEC(@sql);\n")
    res = CliRunner().invoke(cli, ["check", str(f), "--strict"])
    assert res.exit_code == 0
