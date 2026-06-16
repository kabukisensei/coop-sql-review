"""Tests for SQL-ALIAS-DESCRIPTIVE (§2): descriptive table aliases."""

from __future__ import annotations

from coop_sql_review.parser import parse_sql
from coop_sql_review.rules.base import RuleContext
from coop_sql_review.rules.sql_alias_descriptive import RULE, check


def run(sql):
    p = parse_sql("t.sql", sql)
    return RULE.check(RuleContext(RULE, p))


def test_single_letter_alias_flagged():
    findings = run("SELECT col FROM silver.dim_customer a")
    assert len(findings) == 1
    assert findings[0].rule_id == "SQL-ALIAS-DESCRIPTIVE"
    assert findings[0].line == 1
    assert "a" in findings[0].message


def test_descriptive_alias_not_flagged():
    assert run("SELECT col FROM silver.dim_customer cust") == []


def test_no_alias_not_flagged():
    assert run("SELECT col FROM silver.dim_customer") == []


def test_two_char_alias_flagged():
    # Tricky edge: a two-char alias is still too short (< 3).
    findings = run("SELECT col FROM silver.dim_customer dc")
    assert len(findings) == 1
    assert findings[0].rule_id == "SQL-ALIAS-DESCRIPTIVE"
    assert "dc" in findings[0].message


def test_check_callable_directly_matches_rule():
    p = parse_sql("t.sql", "SELECT col FROM silver.dim_customer a")
    assert len(check(RuleContext(RULE, p))) == 1
