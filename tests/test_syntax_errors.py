"""Real T-SQL syntax errors surface as SYNTAX_ERROR diagnostics.

Before v0.6.0 two classes of genuinely invalid T-SQL passed `check` with zero
parse diagnostics, then failed Fabric's import ("Incorrect syntax near 'END'").
sqlglot at IGNORE level silently *recovers* both; parsing at RAISE catches them
with exact line/col. These pin that the signal is no longer discarded — while
valid-but-unsupported syntax (ALTER COLUMN ... NOT NULL) stays a warning-level
PARSE_DEGRADED, never reclassified.
"""

import json

from click.testing import CliRunner

from coop_sql_review.cli import cli
from coop_sql_review.diagnostics import PARSE_DEGRADED, SYNTAX_ERROR
from coop_sql_review.parser import parse_sql

# The real 2026-07-06 incident was a mangled WITH inside a *stored procedure*
# (a silver-layer KPI load proc). It recovers to an opaque Command at IGNORE — exactly
# like the estate's VALID procs — but sqlglot flags it with the definitive
# "column does not support CTE", which is what keeps it a syntax error.
INCIDENT_PROC = """CREATE PROCEDURE [silver].[usp_load_fact_kpis] AS
BEGIN
SET NOCOUNT ON;
;WITH HierarchyDedup AS
(
    SELECT * FROM
(
    SELECT a, ROW_NUMBER() OVER (PARTITION BY a ORDER BY b) AS rn
    FROM dim.T
)
) sub
WHERE rn = 1

INSERT INTO f (a) SELECT a FROM HierarchyDedup
END
"""

# --- the two real 2026-07-06 escapes, minimized (verbatim from the plan §1) ---

CASE_ELSE_END = "\nSELECT SUM(CASE WHEN d <= '2026-01-01' THEN amt ELSE END) AS x FROM t\n"

MANGLED_WITH = """;WITH HierarchyDedup AS
(
    SELECT * FROM
(
    SELECT a, ROW_NUMBER() OVER (PARTITION BY a ORDER BY b) AS rn
    FROM dim.T
)
) sub
WHERE rn = 1

INSERT INTO f (a) SELECT a FROM HierarchyDedup
"""

# A CTE body whose closing `) sub / WHERE rn = 1` fragments were spliced onto a
# sibling CTE (three enum CTEs; the dangling WHERE landed after `) sub`).
MANGLED_THREE_CTE = """;WITH cte_a AS
(
    SELECT id, ROW_NUMBER() OVER (PARTITION BY id ORDER BY dt) AS rn
    FROM dim.A
) sub
WHERE rn = 1
, cte_b AS
(
    SELECT id FROM dim.B
),
cte_c AS
(
    SELECT id FROM dim.C
)
SELECT * FROM cte_a
"""

# THEN with no value before the next WHEN.
THEN_NO_VALUE = "SELECT CASE WHEN a=1 THEN WHEN a=2 THEN 3 END AS x FROM t\n"


def _syntax_diags(parsed):
    return [d for d in parsed.diagnostics if d.category == SYNTAX_ERROR]


def _check_json(args):
    result = CliRunner().invoke(cli, ["check", *args, "--format", "json"])
    return result, json.loads(result.output)


# --- regression fixtures: each must yield >=1 SYNTAX_ERROR at the expected line ---


def test_case_else_end_is_a_syntax_error():
    diags = _syntax_diags(parse_sql("case1.sql", CASE_ELSE_END))
    assert len(diags) >= 1
    assert diags[0].severity == "error"
    assert diags[0].line == 2  # the SELECT line (leading blank shifts it to 2)
    assert "Expected END after CASE" in diags[0].message
    assert "col " in diags[0].message  # column is reported


def test_mangled_with_chain_is_a_syntax_error():
    diags = _syntax_diags(parse_sql("case2.sql", MANGLED_WITH))
    assert diags, "the dangling WHERE outside the CTE must be caught"
    assert all(d.severity == "error" for d in diags)
    assert diags[0].line == 9  # `WHERE rn = 1` dangling outside the CTE paren


def test_mangled_three_cte_is_a_syntax_error():
    diags = _syntax_diags(parse_sql("case3.sql", MANGLED_THREE_CTE))
    assert diags
    assert diags[0].line == 6  # `) sub / WHERE rn = 1` spliced onto the sibling CTE


def test_then_with_no_value_is_a_syntax_error():
    diags = _syntax_diags(parse_sql("then.sql", THEN_NO_VALUE))
    assert len(diags) >= 1
    assert diags[0].line == 1


def test_syntax_error_message_is_ascii_and_single_line():
    for text in (CASE_ELSE_END, MANGLED_WITH, MANGLED_THREE_CTE, THEN_NO_VALUE):
        for diag in _syntax_diags(parse_sql("x.sql", text)):
            assert diag.message.isascii()  # no ANSI underline / snippet context
            assert "\n" not in diag.message


# --- partial analysis survives: a broken batch never blinds a valid sibling ---


def test_valid_batch_still_parses_alongside_a_broken_one():
    sql = (
        "SELECT SUM(CASE WHEN d <= '2026-01-01' THEN amt ELSE END) AS x FROM t\n"
        "GO\n"
        "CREATE TABLE silver.dim_thing (Id bigint NOT NULL, Amount money NOT NULL)\n"
    )
    parsed = parse_sql("mixed.sql", sql)
    assert _syntax_diags(parsed)  # the broken batch is reported
    # ...and the valid batch's object is still extracted
    assert any(o.schema == "silver" and o.name == "dim_thing" for o in parsed.objects)


def test_recovery_still_produces_findings_for_the_valid_batch(tmp_path):
    # The valid batch's SELECT * must still fire SQL-NO-SELECT-STAR even though a
    # sibling batch is unparseable.
    f = tmp_path / "mixed.sql"
    f.write_text(
        "SELECT SUM(CASE WHEN d <= '2026-01-01' THEN amt ELSE END) AS x FROM t\n"
        "GO\n"
        "CREATE VIEW gold.v AS SELECT * FROM dbo.t\n",
        encoding="utf-8",
    )
    _result, payload = _check_json([str(f)])
    assert any(x["rule_id"] == "SQL-NO-SELECT-STAR" for x in payload["findings"])
    assert any(d["category"] == SYNTAX_ERROR for d in payload["diagnostics"])


# --- acceptance #1: the real incident (mangled CTE inside a stored proc) is caught ---


def test_incident_mangled_cte_in_proc_is_a_syntax_error():
    diags = _syntax_diags(parse_sql("usp_load_fact_kpis.sql", INCIDENT_PROC))
    assert diags, "the mangled-CTE-in-a-proc incident shape must be caught as a syntax error"
    assert all(d.severity == "error" for d in diags)
    # the dangling `WHERE rn = 1` outside the CTE paren, at its file line
    assert diags[0].line == 12


# --- acceptance #2 boundary: known sqlglot gaps on VALID T-SQL degrade, they do
#     NOT become syntax errors (the estate's three gap constructs). ---


def test_compound_assignment_is_a_gap_not_a_syntax_error():
    # `SET @v += x` is valid T-SQL sqlglot's tsql dialect can't parse.
    parsed = parse_sql("copydata.sql", "CREATE PROCEDURE p AS BEGIN DECLARE @i INT = 0; SET @i += 1; END")
    cats = {d.category for d in parsed.diagnostics}
    assert SYNTAX_ERROR not in cats
    assert PARSE_DEGRADED in cats


def test_clustered_primary_key_is_a_gap_not_a_syntax_error():
    # `PRIMARY KEY CLUSTERED (col ASC)` is valid T-SQL DDL sqlglot mis-parses.
    sql = "CREATE TABLE mart.t (Id INT NOT NULL, PRIMARY KEY CLUSTERED (Id ASC))"
    parsed = parse_sql("connections.sql", sql)
    cats = {d.category for d in parsed.diagnostics}
    assert SYNTAX_ERROR not in cats
    assert PARSE_DEGRADED in cats


def test_unclosed_paren_without_clustered_stays_a_syntax_error():
    # The clustered-index gap must not swallow a genuine `Expecting )` elsewhere.
    diags = _syntax_diags(parse_sql("broken.sql", "SELECT a FROM (SELECT b FROM t\n"))
    assert diags


# --- no regression: valid-but-unsupported syntax stays a warning, not an error ---


def test_alter_column_not_null_stays_parse_degraded_not_syntax_error():
    parsed = parse_sql("alter.sql", "ALTER TABLE gold.t ALTER COLUMN c int NOT NULL;")
    cats = {d.category for d in parsed.diagnostics}
    assert PARSE_DEGRADED in cats
    assert SYNTAX_ERROR not in cats  # a Command degradation is NOT invalid syntax
    assert all(d.severity == "warning" for d in parsed.diagnostics)


# --- the rules.yml `syntax_errors` knob + inline `ignore syntax` ---


def _write_config(tmp_path, body):
    cfg = tmp_path / "rules.yml"
    cfg.write_text(body, encoding="utf-8")
    return cfg


def test_knob_warning_demotes_but_keeps_the_diagnostic(tmp_path):
    f = tmp_path / "b.sql"
    f.write_text(CASE_ELSE_END, encoding="utf-8")
    cfg = _write_config(tmp_path, "syntax_errors: warning\n")
    _result, payload = _check_json([str(f), "--config", str(cfg)])
    diags = [d for d in payload["diagnostics"] if d["category"] == SYNTAX_ERROR]
    assert len(diags) == 1
    assert diags[0]["severity"] == "warning"  # visible, but demoted


def test_knob_off_removes_the_diagnostic(tmp_path):
    f = tmp_path / "b.sql"
    f.write_text(CASE_ELSE_END, encoding="utf-8")
    cfg = _write_config(tmp_path, "syntax_errors: off\n")
    _result, payload = _check_json([str(f), "--config", str(cfg)])
    assert not [d for d in payload["diagnostics"] if d["category"] == SYNTAX_ERROR]


def test_invalid_knob_value_is_a_friendly_usage_error(tmp_path):
    f = tmp_path / "b.sql"
    f.write_text(CASE_ELSE_END, encoding="utf-8")
    cfg = _write_config(tmp_path, "syntax_errors: loud\n")
    result = CliRunner().invoke(cli, ["check", str(f), "--config", str(cfg)])
    assert result.exit_code == 2
    assert "syntax_errors" in result.output
    assert "Traceback" not in result.output


def test_inline_ignore_syntax_suppresses_exactly_one(tmp_path):
    # Two independent broken batches; the ignore directly above the second one
    # silences only it, so exactly one syntax error remains.
    f = tmp_path / "two.sql"
    f.write_text(
        "SELECT SUM(CASE WHEN d <= '2026-01-01' THEN amt ELSE END) AS x FROM t\n"
        "GO\n"
        "-- coop-sql-review:ignore syntax\n"
        "SELECT SUM(CASE WHEN e <= '2026-01-01' THEN amt ELSE END) AS y FROM u\n",
        encoding="utf-8",
    )
    _result, payload = _check_json([str(f)])
    diags = [d for d in payload["diagnostics"] if d["category"] == SYNTAX_ERROR]
    assert len(diags) == 1
    assert diags[0]["line"] == 1  # only the un-ignored batch remains


def test_inline_ignore_of_a_rule_id_does_not_silence_a_syntax_error(tmp_path):
    # A rule-scoped ignore must NOT swallow a syntax error on the same line.
    f = tmp_path / "one.sql"
    f.write_text(
        "-- coop-sql-review:ignore SQL-NO-SELECT-STAR\n"
        "SELECT SUM(CASE WHEN d <= '2026-01-01' THEN amt ELSE END) AS x FROM t\n",
        encoding="utf-8",
    )
    _result, payload = _check_json([str(f)])
    assert [d for d in payload["diagnostics"] if d["category"] == SYNTAX_ERROR]


# --- strict gating + the machine verdict ---


def test_strict_exits_two_on_a_syntax_error(tmp_path):
    f = tmp_path / "b.sql"
    f.write_text(CASE_ELSE_END, encoding="utf-8")
    strict = CliRunner().invoke(cli, ["check", str(f), "--strict"])
    assert strict.exit_code == 2
    advisory = CliRunner().invoke(cli, ["check", str(f)])
    assert advisory.exit_code == 0  # default stays advisory


def test_strict_passes_when_syntax_errors_are_downgraded(tmp_path):
    # `syntax_errors: warning` -> no error-severity diagnostic -> strict passes.
    # CASE_ELSE_END has a syntax error but yields no rule findings, so it isolates
    # the diagnostic axis from the finding axis of the strict gate.
    f = tmp_path / "b.sql"
    f.write_text(CASE_ELSE_END, encoding="utf-8")
    cfg = _write_config(tmp_path, "syntax_errors: warning\n")
    downgraded = CliRunner().invoke(cli, ["check", str(f), "--config", str(cfg), "--strict"])
    assert downgraded.exit_code == 0
    # and with the default (error) knob the same file fails the gate
    strict = CliRunner().invoke(cli, ["check", str(f), "--strict"])
    assert strict.exit_code == 2


def test_verdict_reflects_a_syntax_error_even_with_no_findings(tmp_path):
    # A syntax error with no rule findings — the verdict must still be "not clean"
    # so the agent never reads it as a clean pass.
    f = tmp_path / "b.sql"
    f.write_text(CASE_ELSE_END, encoding="utf-8")
    _result, payload = _check_json([str(f)])
    assert payload["findings"] == []
    assert payload["verdict"]["clean"] is False
    assert payload["verdict"]["highest_severity"] == "error"
