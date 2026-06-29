"""Tests for SQL-SILVER-PASCALCASE (§1): silver/gold output columns PascalCase."""

from __future__ import annotations

from coop_sql_review.parser import parse_sql
from coop_sql_review.rules.base import RuleContext
from coop_sql_review.rules.sql_silver_pascalcase import RULE


def run(sql):
    p = parse_sql("t.sql", sql)
    return (RULE.check if RULE.check else RULE.detect)(RuleContext(RULE, p))


def test_non_pascal_alias_flagged():
    findings = run("CREATE VIEW silver.v AS SELECT a AS customer_id FROM t")
    assert len(findings) == 1
    assert findings[0].rule_id == "SQL-SILVER-PASCALCASE"
    assert findings[0].object == "silver.v"
    assert "customer_id" in findings[0].message


def test_pascal_alias_not_flagged():
    assert run("CREATE VIEW silver.v AS SELECT a AS CustomerId FROM t") == []


def test_bronze_view_not_flagged():
    # Bronze preserves raw source names — never flag, even snake_case aliases.
    assert run("CREATE VIEW bronze.v AS SELECT a AS customer_id FROM t") == []


def test_ctas_in_gold_flagged():
    findings = run("CREATE TABLE gold.dim AS SELECT a AS some_col FROM s")
    assert len(findings) == 1
    assert findings[0].object == "gold.dim"


def test_bare_column_and_star_not_flagged():
    # No explicit alias asserts an output name, so neither is judged.
    assert run("CREATE VIEW silver.v AS SELECT contactid, t.* FROM t") == []


def test_inner_cte_alias_not_flagged():
    # Only the top-level output projection is the object's output; aliases
    # inside an intermediate CTE are not flagged, only the outer one.
    findings = run(
        "CREATE VIEW silver.v AS "
        "WITH cte_clean AS (SELECT a AS tmp_name FROM t) "
        "SELECT tmp_name AS CustomerName FROM cte_clean"
    )
    assert findings == []


def test_plain_table_create_not_flagged():
    # A non-CTAS CREATE TABLE has no output projection to judge.
    assert run("CREATE TABLE silver.dim (customer_id INT)") == []


def test_union_left_select_alias_flagged():
    # A set-operation defining query: the leftmost SELECT names the outputs,
    # so its non-PascalCase alias must still be flagged.
    findings = run(
        "CREATE VIEW silver.v AS "
        "SELECT contactid AS bad_name FROM bronze.a "
        "UNION ALL SELECT contactid AS x FROM bronze.b;"
    )
    assert len(findings) == 1
    assert findings[0].object == "silver.v"
    assert "bad_name" in findings[0].message


def test_union_pascal_left_aliases_not_flagged():
    # A UNION view whose left aliases are all PascalCase is not flagged.
    assert (
        run(
            "CREATE VIEW silver.v AS "
            "SELECT contactid AS ContactId FROM bronze.a "
            "UNION ALL SELECT contactid AS x FROM bronze.b;"
        )
        == []
    )


def test_except_left_select_alias_flagged():
    findings = run("CREATE VIEW silver.v AS SELECT a AS bad_e FROM t1 EXCEPT SELECT b AS x FROM t2;")
    assert len(findings) == 1
    assert "bad_e" in findings[0].message


def test_nested_union_descends_to_leftmost_select():
    # (A UNION B) UNION C: the leftmost SELECT (A) supplies output names.
    findings = run(
        "CREATE VIEW silver.v AS "
        "SELECT a AS bad_one FROM t1 "
        "UNION SELECT b AS GoodTwo FROM t2 "
        "UNION SELECT c AS GoodThree FROM t3;"
    )
    assert len(findings) == 1
    assert "bad_one" in findings[0].message


def test_view_with_explicit_column_list_flagged():
    # REGRESSION: a CREATE VIEW with an explicit column list parses with
    # create.this being an exp.Schema wrapping the Table (like CREATE TABLE).
    # The parser must unwrap the Schema so the view object is registered and the
    # rule can fire on its non-PascalCase output alias.
    findings = run("CREATE VIEW silver.Foo (Col1, Col2) AS SELECT a AS bad_name, b FROM t")
    assert len(findings) == 1
    assert findings[0].object == "silver.foo"
    assert "bad_name" in findings[0].message


def test_ctas_with_union_body_flagged():
    # REGRESSION: a CTAS whose defining query is a set operation parses with
    # create.expression being an exp.Union, not exp.Select. is_ctas must still be
    # True so the object enters targets and the leftmost-SELECT descent fires.
    findings = run("CREATE TABLE gold.Summary AS SELECT a AS bad_name FROM x UNION ALL SELECT b FROM y;")
    assert len(findings) == 1
    assert findings[0].object == "gold.summary"
    assert "bad_name" in findings[0].message
