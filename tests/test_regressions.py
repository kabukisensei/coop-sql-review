"""Regression tests for defects the adversarial verifiers caught + fixed.

Each test pins a specific real-world case that an earlier implementation got
wrong, so the fix can't silently regress.
"""

from coop_sql_review.parser import parse_sql
from coop_sql_review.rules.base import RuleContext
from coop_sql_review.rules.sql_no_alter_column import RULE as ALTER_RULE
from coop_sql_review.rules.sql_singleton_insert import RULE as INSERT_RULE


def _run(rule, sql):
    parsed = parse_sql("t.sql", sql)
    return rule.check(RuleContext(rule, parsed))


# --- SQL-NO-ALTER-COLUMN: the common form degrades to exp.Command in sqlglot,
#     so an AST-only check missed it. The text-based check must catch it. ---


def test_alter_column_with_nullability_is_flagged():
    findings = _run(ALTER_RULE, "ALTER TABLE gold.fact ALTER COLUMN Revenue decimal(19,4) NOT NULL;")
    assert len(findings) == 1
    assert findings[0].severity == "error"
    assert findings[0].object == "gold.fact"


def test_alter_column_plain_is_flagged():
    findings = _run(ALTER_RULE, "ALTER TABLE gold.t ALTER COLUMN c int;")
    assert len(findings) == 1


def test_alter_add_and_drop_column_not_flagged():
    assert _run(ALTER_RULE, "ALTER TABLE gold.t ADD col int;") == []
    assert _run(ALTER_RULE, "ALTER TABLE gold.t DROP COLUMN c;") == []


def test_alter_column_in_comment_or_string_not_flagged():
    assert _run(ALTER_RULE, "-- ALTER TABLE gold.t ALTER COLUMN c int\nSELECT 1;") == []
    assert _run(ALTER_RULE, "SELECT 'ALTER TABLE gold.t ALTER COLUMN c int' AS note;") == []


# --- SQL-SINGLETON-INSERT: a VALUES table-constructor inside INSERT...SELECT
#     must NOT be flagged; only a direct INSERT...VALUES is. ---


def test_insert_select_from_values_constructor_not_flagged():
    sql = "INSERT INTO gold.t (a, b) SELECT v.a, v.b FROM (VALUES (1,2),(3,4),(5,6)) AS v(a,b);"
    assert _run(INSERT_RULE, sql) == []


def test_insert_select_joining_values_lookup_not_flagged():
    sql = "INSERT INTO gold.t (a) SELECT s.a FROM staging s JOIN (VALUES (1),(2)) AS allowed(x) ON s.a = allowed.x;"
    assert _run(INSERT_RULE, sql) == []


def test_direct_insert_values_is_flagged_with_row_count():
    findings = _run(INSERT_RULE, "INSERT INTO gold.t (x, y) VALUES (1,'a'),(2,'b'),(3,'c');")
    assert len(findings) == 1
    assert "3 row(s)" in findings[0].message
    assert findings[0].object == "gold.t"
