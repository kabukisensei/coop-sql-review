"""Tests for SQL-PREFER-CTE (§4): prefer CTEs over derived-table subqueries."""

from __future__ import annotations

from coop_sql_review.parser import parse_sql
from coop_sql_review.rules.base import RuleContext
from coop_sql_review.rules.sql_prefer_cte import RULE


def run(sql):
    p = parse_sql("t.sql", sql)
    return RULE.check(RuleContext(RULE, p))


def test_derived_table_in_from_flagged():
    findings = run("SELECT * FROM (SELECT a FROM t) sub")
    assert len(findings) == 1
    assert findings[0].rule_id == "SQL-PREFER-CTE"
    assert findings[0].severity == "info"
    assert "CTE" in findings[0].message


def test_derived_table_in_join_flagged():
    findings = run("SELECT a FROM t1 JOIN (SELECT b FROM t2) j ON t1.a = j.b")
    assert len(findings) == 1
    assert findings[0].rule_id == "SQL-PREFER-CTE"


def test_cte_query_not_flagged():
    # A CTE-based query has no derived-table subquery to flag.
    findings = run("WITH cte_x AS (SELECT a FROM t) SELECT a FROM cte_x")
    assert findings == []


def test_scalar_subquery_in_where_not_flagged():
    # A scalar subquery inside a WHERE comparison is not a derived table.
    findings = run("SELECT a FROM t WHERE a = (SELECT MAX(b) FROM t)")
    assert findings == []


def test_parenthesized_table_ref_not_flagged():
    # A parenthesized table reference parses as exp.Subquery wrapping an
    # exp.Table, not a query — it is not a derived-table subquery.
    findings = run("SELECT * FROM (gold.a) a")
    assert findings == []


def test_parenthesized_join_group_not_flagged():
    # A parenthesized join group parses as exp.Subquery wrapping an exp.Join,
    # not a query — it is not a derived-table subquery.
    findings = run("SELECT * FROM gold.a a JOIN (gold.b b JOIN gold.c c ON b.id = c.id) ON a.id = b.id")
    assert findings == []
