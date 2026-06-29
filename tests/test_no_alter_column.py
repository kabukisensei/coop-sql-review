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


def test_bracketed_table_name_with_space_flagged():
    # REGRESSION: a bracket-delimited T-SQL identifier may contain spaces
    # (e.g. [My Table]). The table-name capture must allow spaces inside
    # brackets, otherwise the pattern stops at the first space and never reaches
    # the ALTER COLUMN, producing a false negative for this error-severity rule.
    findings = run("ALTER TABLE dbo.[My Table] ALTER COLUMN c INT NOT NULL;")
    assert len(findings) == 1
    assert findings[0].object == "dbo.my table"


def test_bracketed_schema_and_table_with_spaces_flagged():
    # REGRESSION: spaces in both bracketed parts must still be captured.
    findings = run("ALTER TABLE [my schema].[My Table] ALTER COLUMN c INT NOT NULL;")
    assert len(findings) == 1
    assert findings[0].object == "my schema.my table"
