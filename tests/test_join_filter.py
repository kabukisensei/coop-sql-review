"""Tests for SQL-JOIN-FILTER (§8): keep JOIN conditions to key equality."""

from __future__ import annotations

from coop_sql_review.parser import parse_sql
from coop_sql_review.rules.base import RuleContext
from coop_sql_review.rules.sql_join_filter import RULE


def run(sql):
    p = parse_sql("t.sql", sql)
    return (RULE.check if RULE.check else RULE.detect)(RuleContext(RULE, p))


def test_clean_single_key_not_flagged():
    findings = run("SELECT * FROM a JOIN b ON a.id = b.id")
    assert findings == []


def test_clean_multi_key_not_flagged():
    # Multiple AND-ed column=column equalities are still a clean key join.
    findings = run("SELECT * FROM a JOIN b ON a.id = b.id AND a.k = b.k")
    assert findings == []


def test_literal_in_on_flagged():
    findings = run("SELECT * FROM a JOIN b ON a.id = b.id AND b.status = 'Open'")
    assert len(findings) == 1
    assert findings[0].rule_id == "SQL-JOIN-FILTER"
    assert findings[0].severity == "warning"
    assert findings[0].standard_ref == "§8"


def test_function_and_inequality_in_on_flagged():
    # The §8 "Bad" example: a function call + a non-equality comparison.
    sql = (
        "SELECT c.CustomerId FROM silver.dim_customer c\n"
        "LEFT JOIN gold.fact_sales_daily s\n"
        "    ON c.CustomerId = s.CustomerId\n"
        "    AND s.SalesDate >= DATEADD(day, -90, GETDATE())"
    )
    findings = run(sql)
    assert len(findings) == 1
    # The join begins on its own line.
    assert findings[0].line == 2


def test_case_in_on_flagged():
    sql = "SELECT * FROM a JOIN b ON a.id = b.id AND CASE WHEN a.x = 1 THEN 1 ELSE 0 END = 1"
    findings = run(sql)
    assert len(findings) == 1


def test_or_in_on_flagged():
    # §8: OR anywhere in the ON tree is a filter, not key equality.
    findings = run("SELECT * FROM a JOIN b ON a.id = b.id OR a.alt = b.alt")
    assert len(findings) == 1


def test_is_null_in_on_flagged():
    # IS NULL is a filter predicate, not key equality.
    findings = run("SELECT * FROM a JOIN b ON a.id = b.id AND b.deleted_at IS NULL")
    assert len(findings) == 1


def test_is_not_null_in_on_flagged():
    findings = run("SELECT * FROM a JOIN b ON a.id = b.id AND b.deleted_at IS NOT NULL")
    assert len(findings) == 1


def test_coalesce_key_alignment_not_flagged():
    # COALESCE on both keys is idiomatic alignment, not business logic.
    findings = run("SELECT * FROM a JOIN b ON COALESCE(a.id, 0) = COALESCE(b.id, 0)")
    assert findings == []


def test_isnull_key_alignment_not_flagged():
    # ISNULL parses to COALESCE under tsql; still an alignment wrapper.
    findings = run("SELECT * FROM a JOIN b ON ISNULL(a.id, 0) = b.id")
    assert findings == []


def test_cast_key_alignment_not_flagged():
    findings = run("SELECT * FROM a JOIN b ON CAST(a.id AS INT) = b.id")
    assert findings == []


def test_convert_key_alignment_not_flagged():
    findings = run("SELECT * FROM a JOIN b ON CONVERT(INT, a.id) = b.id")
    assert findings == []


def test_collate_key_alignment_not_flagged():
    findings = run("SELECT * FROM a JOIN b ON a.name = b.name COLLATE Latin1_General_CI_AS")
    assert findings == []


def test_business_function_inside_cast_still_flagged():
    # An alignment wrapper enclosing a real function is not benign.
    findings = run("SELECT * FROM a JOIN b ON CAST(YEAR(a.d) AS INT) = b.y")
    assert len(findings) == 1


def test_dateadd_filter_still_flagged():
    # Regression guard: genuine business function + inequality remains flagged.
    sql = "SELECT c.x FROM a c LEFT JOIN s ON c.id = s.id AND s.d >= DATEADD(day, -90, GETDATE())"
    findings = run(sql)
    assert len(findings) == 1


def test_only_dirty_join_flagged_among_many():
    sql = "SELECT * FROM a\nJOIN b ON a.id = b.id\nJOIN c ON a.k = c.k AND c.region = 'NA'"
    findings = run(sql)
    assert len(findings) == 1
    assert findings[0].line == 3
