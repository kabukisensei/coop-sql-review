"""Tests for SQL-SINGLETON-INSERT (§9)."""

from __future__ import annotations

from coop_sql_review.parser import parse_sql
from coop_sql_review.rules.base import RuleContext
from coop_sql_review.rules.sql_singleton_insert import RULE, check


def run(sql):
    p = parse_sql("t.sql", sql)
    return RULE.check(RuleContext(RULE, p))


def test_single_row_values_flagged():
    findings = run("INSERT INTO g.t VALUES (1, 'a')")
    assert len(findings) == 1
    f = findings[0]
    assert f.rule_id == "SQL-SINGLETON-INSERT"
    assert f.line == 1
    assert f.object == "g.t"
    assert "1 row(s)" in f.message


def test_insert_select_not_flagged():
    findings = run("INSERT INTO g.t (x) SELECT x FROM s")
    assert findings == []


def test_message_attributes_fabric_rationale():
    # The rule runs on BOTH targets, so the tiny-Parquet-file rationale must be
    # attributed to Fabric DW, not asserted universally (issue #12).
    findings = run("INSERT INTO g.t VALUES (1)")
    assert "on Fabric DW" in findings[0].message


def test_multi_row_values_flagged_with_count():
    findings = run("INSERT INTO g.t (x, y) VALUES (1, 'a'), (2, 'b'), (3, 'c')")
    assert len(findings) == 1
    f = findings[0]
    assert f.rule_id == "SQL-SINGLETON-INSERT"
    assert "3 row(s)" in f.message
    assert f.object == "g.t"


def test_check_callable_directly():
    p = parse_sql("t.sql", "INSERT INTO g.t VALUES (1)")
    findings = check(RuleContext(RULE, p))
    assert len(findings) == 1


# -- temp tables / table variables are not flagged (issue #13) ---------------


def test_temp_table_seeding_not_flagged():
    assert run("INSERT INTO #staging VALUES (1);") == []


def test_global_temp_table_seeding_not_flagged():
    assert run("INSERT INTO ##staging VALUES (1);") == []


def test_table_variable_seeding_not_flagged():
    assert run("INSERT INTO @rows VALUES (1);") == []


def test_temp_table_seeding_inside_proc_body_not_flagged():
    sql = (
        "CREATE OR ALTER PROCEDURE silver.p AS\n"
        "BEGIN\n"
        "    INSERT INTO #staging VALUES (1), (2);\n"
        "    INSERT INTO @lookup VALUES ('a');\n"
        "END\n"
    )
    assert run(sql) == []


def test_persisted_table_still_flagged_with_correct_object():
    findings = run("INSERT INTO silver.dim_x VALUES (1);")
    assert len(findings) == 1
    assert findings[0].object == "silver.dim_x"


# (dml_target's own naming behavior — temp prefixes, alias resolution — is unit
# tested in tests/test_helpers.py.)
