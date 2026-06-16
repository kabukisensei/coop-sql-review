"""Tests for SQL-NO-ALTER-COLUMN (§9)."""

from __future__ import annotations

from coop_sql_review.parser import parse_sql
from coop_sql_review.rules.base import RuleContext
from coop_sql_review.rules.sql_no_alter_column import RULE, check  # noqa: F401


def run(sql):
    p = parse_sql("t.sql", sql)
    return RULE.check(RuleContext(RULE, p))


def test_alter_column_flagged():
    findings = run("ALTER TABLE dbo.customer ALTER COLUMN name varchar(100);")
    assert len(findings) == 1
    finding = findings[0]
    assert finding.rule_id == "SQL-NO-ALTER-COLUMN"
    assert finding.severity == "error"
    assert finding.object == "dbo.customer"
    assert finding.line == 1


def test_add_column_not_flagged():
    findings = run("ALTER TABLE dbo.customer ADD age int;")
    assert findings == []


def test_alter_column_on_later_line():
    sql = """CREATE TABLE dbo.customer (id int);
GO
ALTER TABLE dbo.customer
    ALTER COLUMN name nvarchar(50);
"""
    findings = run(sql)
    assert len(findings) == 1
    # The ALTER statement begins on file line 3 (after CREATE + GO).
    assert findings[0].line == 3
    assert findings[0].object == "dbo.customer"


def test_unqualified_table_defaults_schema():
    findings = run("ALTER TABLE customer ALTER COLUMN name varchar(50);")
    assert len(findings) == 1
    assert findings[0].object == "dbo.customer"
