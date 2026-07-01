"""Tests for SQL-UPSERT-CHOICE (§5): every MERGE is flagged for agent judgment.

An agent-kind rule (detect -> agent_review): a crash or a silent no-op would
never fail a run, so these tests pin that the detection actually fires.
"""

from __future__ import annotations

from coop_sql_review.parser import parse_sql
from coop_sql_review.rules.base import RuleContext
from coop_sql_review.rules.sql_upsert_choice import RULE


def run(sql):
    p = parse_sql("t.sql", sql)
    return RULE.detect(RuleContext(RULE, p))


MERGE = """\
MERGE silver.dim_customer AS tgt
USING staging.customer AS src
    ON tgt.CustomerId = src.CustomerId
WHEN MATCHED THEN UPDATE SET tgt.FirstName = src.FirstName
WHEN NOT MATCHED THEN INSERT (CustomerId, FirstName) VALUES (src.CustomerId, src.FirstName);
"""


def test_merge_is_flagged_for_agent_review():
    items = run(MERGE)
    assert len(items) == 1
    item = items[0]
    assert item.rule_id == "SQL-UPSERT-CHOICE"
    assert item.object == "silver.dim_customer"
    assert item.line == 1
    assert item.standard_ref == "§5"
    assert "MERGE" in item.note


def test_delete_plus_insert_load_is_not_flagged():
    # §5's preferred large-table pattern must not be sent to the agent.
    sql = (
        "DELETE FROM gold.fact_sales WHERE LoadDate = @load_date;\n"
        "INSERT INTO gold.fact_sales (SaleId, Amount)\n"
        "SELECT src.SaleId, src.Amount FROM staging.sales AS src;\n"
    )
    assert run(sql) == []


def test_merge_free_file_is_not_flagged():
    assert run("SELECT cust.CustomerId FROM silver.dim_customer cust;") == []


def test_two_merges_yield_two_items():
    sql = MERGE + "GO\n" + MERGE.replace("dim_customer", "dim_product")
    items = run(sql)
    assert [(i.object, i.line) for i in items] == [
        ("silver.dim_customer", 1),
        ("silver.dim_product", 7),
    ]


def test_merge_inside_procedure_body_is_flagged():
    sql = "CREATE PROCEDURE dbo.usp_upsert_customer AS\nBEGIN\n" + MERGE + "END\n"
    items = run(sql)
    assert len(items) == 1
    assert items[0].object == "silver.dim_customer"
    assert items[0].line == 3  # the MERGE line, not the CREATE line
