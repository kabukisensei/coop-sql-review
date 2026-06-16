"""Tests for SQL-CTE-PREFIX (§1): CTEs use the ``cte_`` prefix."""

from __future__ import annotations

from coop_sql_review.parser import parse_sql
from coop_sql_review.rules.base import RuleContext
from coop_sql_review.rules.sql_cte_prefix import RULE


def run(sql):
    p = parse_sql("t.sql", sql)
    return RULE.check(RuleContext(RULE, p))


def test_well_prefixed_cte_not_flagged():
    findings = run("WITH cte_src AS (SELECT 1) SELECT * FROM cte_src")
    assert findings == []


def test_unprefixed_cte_flagged():
    findings = run("WITH staging AS (SELECT 1) SELECT * FROM staging")
    assert len(findings) == 1
    assert findings[0].rule_id == "SQL-CTE-PREFIX"
    assert findings[0].line == 1
    assert "staging" in findings[0].message


def test_multiple_ctes_only_unprefixed_flagged():
    sql = "WITH cte_src AS (SELECT 1),\nstaging AS (SELECT 2)\nSELECT * FROM cte_src JOIN staging ON 1 = 1"
    findings = run(sql)
    assert len(findings) == 1
    assert "staging" in findings[0].message
    # The non-prefixed CTE sits on the second line.
    assert findings[0].line == 2


def test_bracketed_name_normalized():
    # Bracket-quoting must not hide the prefix check.
    findings = run("WITH [Staging] AS (SELECT 1) SELECT * FROM Staging")
    assert len(findings) == 1
    assert "Staging" in findings[0].message
