"""Tests for SQL-INSERT-ALIAS-MATCH (§3)."""

from __future__ import annotations

from coop_sql_review.parser import parse_sql
from coop_sql_review.rules.base import RuleContext
from coop_sql_review.rules.sql_insert_alias_match import RULE


def run(sql):
    p = parse_sql("t.sql", sql)
    return (RULE.check if RULE.check else RULE.detect)(RuleContext(RULE, p))


def test_flags_unaliased_projection():
    # B has no AS alias -> flagged; A is fine.
    findings = run("INSERT INTO t (A, B) SELECT x AS A, y FROM s")
    assert len(findings) == 1
    f = findings[0]
    assert "INSERT column 'B'" in f.message
    assert f.object == "dbo.t"


def test_flags_mismatched_alias():
    # alias name does not match the target column.
    findings = run("INSERT INTO t (A, B) SELECT x AS A, y AS WrongName FROM s")
    assert len(findings) == 1
    assert "INSERT column 'B'" in findings[0].message


def test_clean_when_all_aliases_match():
    findings = run("INSERT INTO t (A, B) SELECT x AS A, y AS B FROM s")
    assert findings == []


def test_alias_match_is_case_insensitive():
    findings = run("INSERT INTO t (A, B) SELECT x AS a, y AS b FROM s")
    assert findings == []


def test_skips_values_source():
    findings = run("INSERT INTO t (A, B) VALUES (1, 2)")
    assert findings == []


def test_skips_union_source():
    # UNION is a set-operation source, not a plain SELECT -> not checked.
    findings = run("INSERT INTO t (A, B) SELECT x AS A, y FROM s UNION SELECT 1, 2")
    assert findings == []


def test_skips_insert_without_column_list():
    # No explicit column list -> can't align, skip.
    findings = run("INSERT INTO t SELECT x, y FROM s")
    assert findings == []
