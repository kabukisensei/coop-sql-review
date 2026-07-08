"""Tests for SQL-NARROWING-CAST (§I proposed): silent-truncation casts."""

from __future__ import annotations

from coop_sql_review.parser import parse_sql
from coop_sql_review.rules.base import RuleContext
from coop_sql_review.rules.sql_narrowing_cast import RULE

DECL = "CREATE TABLE bronze.raw_customer (CustomerName VARCHAR(200), Notes NVARCHAR(MAX));\n"


def run(sql):
    p = parse_sql("t.sql", sql)
    return RULE.check(RuleContext(RULE, p))


def test_narrowing_varchar_flagged_with_sizes_and_column():
    findings = run(DECL + "SELECT CAST(c.CustomerName AS VARCHAR(50)) FROM bronze.raw_customer c;")
    assert len(findings) == 1
    f = findings[0]
    assert f.rule_id == "SQL-NARROWING-CAST"
    assert f.line == 2  # the cast's line
    assert "CustomerName" in f.message
    assert "200" in f.message and "50" in f.message
    assert "truncat" in f.message.lower()


def test_try_cast_narrowing_flagged():
    findings = run(DECL + "SELECT TRY_CAST(c.CustomerName AS VARCHAR(50)) FROM bronze.raw_customer c;")
    assert len(findings) == 1
    assert "TRY_CAST" in findings[0].message  # calls out that TRY_CAST truncates too


def test_convert_narrowing_flagged():
    assert len(run(DECL + "SELECT CONVERT(VARCHAR(50), c.CustomerName) FROM bronze.raw_customer c;")) == 1


def test_max_source_to_sized_flagged():
    # varchar(max) source cast to a sized target is a narrowing (MAX treated as wider).
    assert len(run(DECL + "SELECT CAST(c.Notes AS NVARCHAR(8000)) FROM bronze.raw_customer c;")) == 1


def test_not_flagged_cases():
    for sql in [
        "SELECT CAST(c.CustomerName AS VARCHAR(200)) FROM bronze.raw_customer c;",  # equal width
        "SELECT CAST(c.CustomerName AS VARCHAR(300)) FROM bronze.raw_customer c;",  # wider
        "SELECT CAST(c.CustomerName AS VARCHAR(MAX)) FROM bronze.raw_customer c;",  # to MAX
        "SELECT CAST('abcdef' AS VARCHAR(2));",  # literal, not a column
        "SELECT CAST(x.Other AS VARCHAR(5)) FROM other x;",  # unknown column
        "SELECT CAST(c.CustomerName AS INT) FROM bronze.raw_customer c;",  # non-sized target
    ]:
        assert run(DECL + sql) == [], sql


def test_conflicting_bare_name_declarations_dropped():
    # The same bare name declared with different sizes across tables is ambiguous -> dropped.
    sql = (
        "CREATE TABLE a (N VARCHAR(200));\n"
        "CREATE TABLE b (N VARCHAR(10));\n"
        "SELECT CAST(x.N AS VARCHAR(5)) FROM a x;\n"
    )
    assert run(sql) == []


def test_allow_max_to_sized_param_relaxes_max_case():
    from dataclasses import replace

    relaxed = replace(RULE, params={"allow_max_to_sized": True})
    p = parse_sql("t.sql", DECL + "SELECT CAST(c.Notes AS NVARCHAR(8000)) FROM bronze.raw_customer c;")
    assert relaxed.check(RuleContext(relaxed, p)) == []  # MAX->sized relaxed
    # but a plain narrowing is still flagged under the relaxed param
    p2 = parse_sql("t.sql", DECL + "SELECT CAST(c.CustomerName AS VARCHAR(50)) FROM bronze.raw_customer c;")
    assert len(relaxed.check(RuleContext(relaxed, p2))) == 1


def test_rule_applies_to_both_targets():
    from coop_sql_review.rules.base import ALL_TARGETS

    assert RULE.targets == ALL_TARGETS  # truncation is a data-loss bug on Fabric DW AND Azure SQL
