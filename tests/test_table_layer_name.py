"""Tests for SQL-TABLE-LAYER-NAME (§1)."""

from __future__ import annotations

from coop_sql_review.parser import parse_sql
from coop_sql_review.rules.base import RuleContext
from coop_sql_review.rules.sql_table_layer_name import RULE
from coop_sql_review.sql_model import ParsedFile, SqlObject


def run(sql):
    p = parse_sql("t.sql", sql)
    return (RULE.check if RULE.check else RULE.detect)(RuleContext(RULE, p))


def test_flags_table_outside_medallion_schema():
    findings = run("CREATE TABLE dbo.foo (id INT);")
    assert len(findings) == 1
    assert findings[0].object == "dbo.foo"
    assert "medallion-layer" in findings[0].message
    assert findings[0].message.startswith("table dbo.foo")


def test_allows_table_in_silver():
    findings = run("CREATE TABLE silver.dim_customer (id INT);")
    assert findings == []


def test_view_in_gold_not_flagged():
    findings = run("CREATE VIEW gold.v_sales AS SELECT 1 AS x;")
    assert findings == []


def test_view_outside_medallion_schema_flagged_as_view():
    findings = run("CREATE VIEW reporting.v_sales AS SELECT 1 AS x;")
    assert len(findings) == 1
    assert findings[0].message.startswith("view reporting.v_sales")


def test_temp_object_skipped():
    # A temp object is not a medallion table and must not be flagged.
    # sqlglot strips the '#' from real CREATE TABLE #t DDL, so the rule keys
    # off SqlObject.is_temp rather than a literal prefix on the name.
    obj = SqlObject(kind="table", schema="dbo", name="staging", display_name="staging", line=1, is_temp=True)
    parsed = ParsedFile(path="t.sql", text="", masked="", dialect="tsql", objects=[obj])
    findings = check_objects(parsed)
    assert findings == []


def test_local_temp_table_ddl_not_flagged():
    # Regression: sqlglot parses '#staging' as 'dbo.staging' (strips '#'), so
    # the old literal-prefix guard let it through as a false positive.
    findings = run("CREATE TABLE #staging (id int);")
    assert findings == []


def test_global_temp_table_ddl_not_flagged():
    # Regression: '##g' loses both the '#' prefix and the temporary= flag from
    # sqlglot; is_temp must still detect it via the rendered DDL prefix.
    findings = run("CREATE TABLE ##g (id int);")
    assert findings == []


def test_dbo_table_ddl_still_flagged():
    # Guard against over-broad temp detection: a plain dbo table is not temp.
    findings = run("CREATE TABLE dbo.foo (id int);")
    assert len(findings) == 1
    assert findings[0].object == "dbo.foo"


def test_silver_table_ddl_not_flagged():
    findings = run("CREATE TABLE silver.dim (id int);")
    assert findings == []


def check_objects(parsed):
    return RULE.check(RuleContext(RULE, parsed))
