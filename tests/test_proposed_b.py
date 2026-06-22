"""Tests for proposed-addition rules:
SQL-TRY-CAST-BRONZE (§D) and SQL-IMPLICIT-CONVERT (§C).
"""

from __future__ import annotations

from coop_sql_review.parser import parse_sql
from coop_sql_review.rules.base import RuleContext
from coop_sql_review.rules.sql_try_cast_bronze import RULE as TRY_CAST_RULE
from coop_sql_review.rules.sql_implicit_convert import RULE as IMPLICIT_RULE


def run(rule, sql):
    p = parse_sql("t.sql", sql)
    return rule.check(RuleContext(rule, p))


# --- SQL-TRY-CAST-BRONZE --------------------------------------------------


def test_try_cast_bronze_positive():
    findings = run(TRY_CAST_RULE, "SELECT CAST(x AS int) FROM bronze.raw_t;")
    assert len(findings) == 1
    f = findings[0]
    assert f.rule_id == "SQL-TRY-CAST-BRONZE"
    assert f.severity == "info"
    assert f.line == 1
    assert "TRY_CAST" in f.message


def test_try_cast_bronze_negative_already_try_cast():
    # TRY_CAST is the recommended form — must not be flagged even on bronze.
    assert run(TRY_CAST_RULE, "SELECT TRY_CAST(x AS int) FROM bronze.raw_t;") == []


def test_try_cast_bronze_negative_non_bronze_source():
    # CAST on a silver/gold source (no bronze table read) — stay silent.
    assert run(TRY_CAST_RULE, "SELECT CAST(x AS int) FROM silver.dim_t;") == []
    assert run(TRY_CAST_RULE, "SELECT CAST(x AS int) FROM gold.fact_t;") == []


def test_try_cast_bronze_only_flags_plain_cast_in_bronze_batch():
    # A batch that reads bronze and has both: only the plain CAST is flagged.
    sql = "SELECT CAST(x AS int), TRY_CAST(y AS int) FROM bronze.raw_t;"
    findings = run(TRY_CAST_RULE, sql)
    assert len(findings) == 1


def test_try_cast_bronze_scoped_per_batch():
    # CAST lives in a non-bronze batch; bronze is only in a separate batch.
    sql = "SELECT CAST(x AS int) FROM silver.dim_t;\nGO\nSELECT id FROM bronze.raw_t;\n"
    assert run(TRY_CAST_RULE, sql) == []


def test_try_cast_bronze_negative_bronze_only_write_target():
    # Regression: bronze is the INSERT *target* (not a read source) and the
    # cast is on a pure literal — must not be flagged.
    assert run(TRY_CAST_RULE, "INSERT INTO bronze.t (id) SELECT CAST(1 AS INT);") == []


def test_try_cast_bronze_positive_cast_column_from_bronze_source():
    # Regression: plain CAST of a column read from bronze — flagged.
    findings = run(TRY_CAST_RULE, "SELECT CAST(x AS int) FROM bronze.raw;")
    assert len(findings) == 1


def test_try_cast_bronze_negative_try_cast_column_from_bronze_source():
    # Regression: TRY_CAST is the recommended form — not flagged.
    assert run(TRY_CAST_RULE, "SELECT TRY_CAST(x AS int) FROM bronze.raw;") == []


def test_try_cast_bronze_negative_literal_cast_with_bronze_source():
    # CAST of a pure literal stays silent even when a bronze table is read.
    assert run(TRY_CAST_RULE, "SELECT CAST(1 AS INT) FROM bronze.raw;") == []


# --- SQL-IMPLICIT-CONVERT -------------------------------------------------


def test_implicit_convert_positive_string_col_vs_number():
    sql = """\
CREATE TABLE g.t (code varchar(10));
GO
SELECT code FROM g.t WHERE code = 5;
"""
    findings = run(IMPLICIT_RULE, sql)
    assert len(findings) == 1
    f = findings[0]
    assert f.rule_id == "SQL-IMPLICIT-CONVERT"
    assert f.severity == "info"
    # The comparison sits in a standalone SELECT (no enclosing CREATE), so the
    # object is the empty convention — that is expected.
    assert f.object == ""
    assert "code" in f.message
    assert "VARCHAR" in f.message


def test_implicit_convert_positive_numeric_col_vs_string():
    sql = """\
CREATE TABLE g.t (amt int);
GO
SELECT amt FROM g.t WHERE amt = '5';
"""
    findings = run(IMPLICIT_RULE, sql)
    assert len(findings) == 1
    assert "INT" in findings[0].message


def test_implicit_convert_negative_matched_types():
    sql = """\
CREATE TABLE g.t (code varchar(10));
GO
SELECT code FROM g.t WHERE code = '5';
"""
    assert run(IMPLICIT_RULE, sql) == []


def test_implicit_convert_negative_unknown_column_type():
    # No CREATE in the file → column type unknown → must not flag.
    assert run(IMPLICIT_RULE, "SELECT code FROM g.t WHERE code = 5;") == []


def test_implicit_convert_reversed_operand_order():
    sql = """\
CREATE TABLE g.t (code varchar(10));
GO
SELECT code FROM g.t WHERE 5 = code;
"""
    findings = run(IMPLICIT_RULE, sql)
    assert len(findings) == 1
    assert "code" in findings[0].message


def test_implicit_convert_ignores_null_comparison():
    sql = """\
CREATE TABLE g.t (code varchar(10));
GO
SELECT code FROM g.t WHERE code = NULL;
"""
    assert run(IMPLICIT_RULE, sql) == []


def test_implicit_convert_negative_update_set_assignment():
    # Regression: UPDATE SET assignment is not a predicate — not flagged.
    sql = """\
CREATE TABLE silver.cust (id INT, code VARCHAR(10));
GO
UPDATE silver.cust SET code=5 WHERE id=1;
"""
    assert run(IMPLICIT_RULE, sql) == []


def test_implicit_convert_negative_select_list_boolean():
    # Regression: SELECT-list boolean expression is not a predicate.
    sql = """\
CREATE TABLE silver.cust (id INT, code VARCHAR(10));
GO
SELECT (code=5) AS flag FROM silver.cust;
"""
    assert run(IMPLICIT_RULE, sql) == []


def test_implicit_convert_positive_where_still_flagged():
    # Regression: a genuine WHERE predicate is still flagged.
    sql = """\
CREATE TABLE silver.cust (id INT, code VARCHAR(10));
GO
SELECT code FROM silver.cust WHERE code = 5;
"""
    findings = run(IMPLICIT_RULE, sql)
    assert len(findings) == 1
    assert "code" in findings[0].message


def test_implicit_convert_positive_join_on_predicate():
    # JOIN ON is a predicate context — flagged.
    sql = """\
CREATE TABLE silver.cust (id INT, code VARCHAR(10));
GO
SELECT c.id FROM silver.cust c JOIN silver.o o ON c.code = 5;
"""
    findings = run(IMPLICIT_RULE, sql)
    assert len(findings) == 1


def test_implicit_convert_range_comparisons():
    # Test range operators GT, GTE, LT, LTE, NEQ
    sql = """\
CREATE TABLE silver.cust (id INT, code VARCHAR(10));
GO
SELECT code FROM silver.cust WHERE code > 5;
SELECT code FROM silver.cust WHERE code <= 5;
SELECT id FROM silver.cust WHERE id <> '5';
"""
    findings = run(IMPLICIT_RULE, sql)
    assert len(findings) == 3


def test_implicit_convert_having_predicate():
    # HAVING is a post-aggregation predicate — a mismatched comparison there
    # forces the same implicit conversion as in WHERE.
    sql = """\
CREATE TABLE silver.cust (id INT, code VARCHAR(10));
GO
SELECT code FROM silver.cust GROUP BY code HAVING code > 5;
"""
    findings = run(IMPLICIT_RULE, sql)
    assert len(findings) == 1


def test_implicit_convert_merge_on_predicate():
    # A MERGE ON match predicate is flagged; the WHEN-MATCHED SET assignment is not.
    sql = """\
CREATE TABLE silver.cust (id INT, code VARCHAR(10));
GO
MERGE silver.cust AS tgt USING silver.src AS s ON tgt.code = 5
WHEN MATCHED THEN UPDATE SET tgt.id = 1;
"""
    findings = run(IMPLICIT_RULE, sql)
    assert len(findings) == 1


def test_implicit_convert_negative_date_range_sargable():
    # §A's preferred SARGable pattern: a date column vs a string literal must
    # NOT be flagged (date types are in neither the string nor numeric set).
    sql = """\
CREATE TABLE gold.fact (SalesDate DATE, amt INT);
GO
SELECT amt FROM gold.fact WHERE SalesDate >= '2026-01-01';
"""
    assert run(IMPLICIT_RULE, sql) == []
