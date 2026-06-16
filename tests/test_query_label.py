"""Tests for SQL-QUERY-LABEL (§9)."""

from __future__ import annotations

from coop_sql_review.parser import parse_sql
from coop_sql_review.rules.base import RuleContext
from coop_sql_review.rules.sql_query_label import RULE


def run(sql):
    p = parse_sql("t.sql", sql)
    return (RULE.check if RULE.check else RULE.detect)(RuleContext(RULE, p))


def test_unlabeled_etl_insert_select_flagged():
    findings = run("INSERT INTO gold.t SELECT * FROM s")
    assert len(findings) == 1
    f = findings[0]
    assert f.rule_id == "SQL-QUERY-LABEL"
    assert f.severity == "info"
    assert f.object == "gold.t"
    assert f.line == 1
    assert "OPTION(LABEL" in f.message


def test_labeled_etl_insert_select_not_flagged():
    findings = run("INSERT INTO gold.t SELECT * FROM s OPTION (LABEL='ETL_x')")
    assert findings == []


def test_singleton_insert_values_skipped():
    # Not ETL — owned by SQL-SINGLETON-INSERT, never flagged here.
    findings = run("INSERT INTO gold.t VALUES (1)")
    assert findings == []


def test_non_label_option_still_flagged():
    # An OPTION clause without LABEL is not a query label.
    findings = run("INSERT INTO gold.t SELECT * FROM s OPTION (MAXDOP 1)")
    assert len(findings) == 1
    assert findings[0].object == "gold.t"


def test_label_among_multiple_options_not_flagged():
    findings = run("INSERT INTO gold.t SELECT * FROM s OPTION (LABEL='L', HASH JOIN)")
    assert findings == []


def test_label_case_insensitive_not_flagged():
    findings = run("insert into gold.t select * from s option (label='lc')")
    assert findings == []


def test_union_all_etl_unlabeled_flagged():
    # Set-based ETL via UNION ALL is in scope and must carry a label.
    findings = run("INSERT INTO gold.fact SELECT * FROM a UNION ALL SELECT * FROM b;")
    assert len(findings) == 1
    assert findings[0].object == "gold.fact"


def test_union_all_etl_labeled_not_flagged():
    # OPTION(LABEL) attaches to the rightmost leaf SELECT of the union.
    findings = run("INSERT INTO gold.fact SELECT * FROM a UNION ALL SELECT * FROM b OPTION (LABEL='x');")
    assert findings == []


def test_except_etl_unlabeled_flagged():
    findings = run("INSERT INTO gold.fact SELECT * FROM a EXCEPT SELECT * FROM b;")
    assert len(findings) == 1
    assert findings[0].object == "gold.fact"


def test_intersect_etl_labeled_not_flagged():
    findings = run("INSERT INTO gold.fact SELECT * FROM a INTERSECT SELECT * FROM b OPTION (LABEL='x');")
    assert findings == []


def test_chained_union_labeled_not_flagged():
    # Label on the deepest rightmost leaf of a chained set operation.
    findings = run(
        "INSERT INTO gold.fact SELECT * FROM a UNION ALL SELECT * FROM b "
        "UNION ALL SELECT * FROM c OPTION (LABEL='x');"
    )
    assert findings == []


def test_parenthesized_select_unlabeled_flagged():
    # Parenthesized (Subquery) source is in scope.
    findings = run("INSERT INTO gold.fact (SELECT * FROM s);")
    assert len(findings) == 1
    assert findings[0].object == "gold.fact"


def test_parenthesized_select_labeled_not_flagged():
    # OPTION(LABEL) attaches to the Subquery wrapper itself.
    findings = run("INSERT INTO gold.fact (SELECT * FROM s) OPTION (LABEL='x');")
    assert findings == []
