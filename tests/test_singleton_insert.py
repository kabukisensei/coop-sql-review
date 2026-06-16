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
