"""Tests for SQL-DATE-FILTER-PARAM (§11)."""

from __future__ import annotations

from coop_sql_review.parser import parse_sql
from coop_sql_review.rules.base import RuleContext
from coop_sql_review.rules.sql_date_filter_param import RULE


def run(sql):
    p = parse_sql("t.sql", sql)
    return (RULE.check if RULE.check else RULE.detect)(RuleContext(RULE, p))


def test_hardcoded_date_literal_flagged():
    findings = run("SELECT 1 FROM Sales WHERE SalesDate >= '2026-01-01'")
    assert len(findings) == 1
    f = findings[0]
    assert f.rule_id == "SQL-DATE-FILTER-PARAM"
    assert f.severity == "info"
    assert f.line == 1
    assert "@process_date" in f.message


def test_parameter_not_flagged():
    assert run("SELECT 1 FROM Sales WHERE SalesDate >= @process_date") == []


def test_non_date_string_not_flagged():
    # A non-date string literal in a predicate must NOT be flagged.
    assert run("SELECT 1 FROM Orders WHERE Status = 'Open'") == []


def test_one_finding_per_literal():
    # A BETWEEN with two date literals flags each one once.
    findings = run("SELECT 1 FROM Sales WHERE SalesDate BETWEEN '2026-01-01' AND '2026-12-31'")
    assert len(findings) == 2


def test_date_literal_outside_where_not_flagged():
    # Only WHERE-clause literals are in scope.
    assert run("SELECT CAST('2026-01-01' AS DATE) AS d FROM Sales") == []


def test_free_text_containing_date_not_flagged():
    # re.fullmatch: a string that merely contains a date is not a date literal.
    assert run("SELECT 1 FROM t WHERE Comment = '2026-06-04 customer called'") == []


def test_invalid_hyphenated_code_not_flagged():
    # Impossible 'dates' (hyphenated codes) must not match the validated pattern.
    assert run("SELECT 1 FROM t WHERE PartNo = '9999-88-77'") == []


def test_subquery_date_literal_reported_once():
    # A literal in a nested WHERE is reported exactly once, not per enclosing WHERE.
    findings = run("SELECT 1 FROM t WHERE id IN (SELECT id FROM t2 WHERE d = '2026-06-04')")
    assert len(findings) == 1


def test_parameter_predicate_not_flagged():
    assert run("SELECT 1 FROM t WHERE d = @p") == []
