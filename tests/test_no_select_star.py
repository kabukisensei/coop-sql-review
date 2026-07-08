"""Tests for SQL-NO-SELECT-STAR (§11)."""

from __future__ import annotations

from coop_sql_review.parser import parse_sql
from coop_sql_review.rules.base import RuleContext
from coop_sql_review.rules.sql_no_select_star import RULE


def run(sql):
    p = parse_sql("t.sql", sql)
    return RULE.check(RuleContext(RULE, p))


def test_select_star_top_level_flagged():
    sql = "SELECT * FROM silver.dim_customer;"
    findings = run(sql)
    assert len(findings) == 1
    assert findings[0].rule_id == "SQL-NO-SELECT-STAR"
    assert findings[0].line == 1


def test_select_star_in_cte_allowed():
    sql = """
    WITH cte_source AS (
        SELECT * FROM bronze.raw_d365_contact
    )
    SELECT CustomerId FROM cte_source;
    """
    assert run(sql) == []


def test_select_star_in_cte_union_allowed():
    sql = """
    WITH cte_combined AS (
        SELECT * FROM bronze.raw_contact_a
        UNION ALL
        SELECT * FROM bronze.raw_contact_b
    )
    SELECT CustomerId FROM cte_combined;
    """
    assert run(sql) == []


def test_select_star_in_derived_table_flagged():
    # A derived-table subquery is production code — §4 calls this the "Bad"
    # pattern (prefer a CTE). Its inner SELECT * IS flagged, unlike a CTE's.
    sql = """
    SELECT sub.CustomerId FROM (
        SELECT * FROM bronze.raw_d365_contact
    ) sub;
    """
    findings = run(sql)
    assert len(findings) == 1
    assert findings[0].rule_id == "SQL-NO-SELECT-STAR"


def test_select_star_in_scalar_subquery_flagged():
    # A scalar subquery in the projection list is production code, not an
    # intermediate narrowing step.
    sql = "SELECT (SELECT * FROM gold.fact_opportunity) AS c FROM silver.dim_customer;"
    assert len(run(sql)) == 1


def test_select_star_in_exists_allowed():
    sql = """
    SELECT cust.CustomerId FROM silver.dim_customer cust
    WHERE EXISTS (
        SELECT * FROM gold.fact_opportunity opp
        WHERE opp.CustomerId = cust.CustomerId
    );
    """
    assert run(sql) == []


def test_select_star_in_insert_flagged():
    sql = "INSERT INTO silver.dim_customer SELECT * FROM bronze.raw_contact;"
    findings = run(sql)
    assert len(findings) == 1
    assert findings[0].line == 1


def test_qualified_star_flagged():
    # SELECT t.* is just as production-unsafe as SELECT *.
    findings = run("SELECT cust.* FROM silver.dim_customer cust;")
    assert len(findings) == 1


def test_count_star_not_flagged():
    # COUNT(*) and other function-argument stars are never projection stars.
    assert run("SELECT COUNT(*) AS n FROM silver.dim_customer;") == []


def test_final_select_star_above_cte_flagged():
    # The CTE's own SELECT * is exempt, but the production final SELECT * is not.
    sql = """
    WITH cte_source AS (
        SELECT * FROM bronze.raw_d365_contact
    )
    SELECT * FROM cte_source;
    """
    findings = run(sql)
    assert len(findings) == 1


def test_select_star_in_procedure_body_attributed_to_proc():
    # A finding inside a CREATE PROCEDURE body must carry the proc as its object, not ""
    # — enclosing_object() unwraps the StoredProcedure wrapper (issue #2). An empty object
    # collapses the suppression fingerprint to (rule_id, message) across the whole estate.
    sql = "CREATE OR ALTER PROCEDURE silver.p AS BEGIN SELECT * FROM bronze.c; END"
    findings = run(sql)
    assert len(findings) == 1
    assert findings[0].object == "silver.p"


def test_two_procs_with_select_star_have_distinct_fingerprints():
    fa = run("CREATE PROCEDURE silver.pa AS BEGIN SELECT * FROM bronze.c; END")
    fb = run("CREATE PROCEDURE silver.pb AS BEGIN SELECT * FROM bronze.c; END")
    assert len(fa) == 1 and len(fb) == 1
    # Distinct objects -> distinct fingerprints, so ignoring one proc's finding does not
    # silently suppress the same finding in every other proc.
    assert fa[0].fingerprint() != fb[0].fingerprint()


def test_select_star_in_derived_table_inside_cte_flagged():
    # issue #4: a derived-table subquery is production code even INSIDE a CTE body — the
    # CTE-own exemption must not leak down to it. (find_ancestor matched a CTE anywhere up
    # the chain; the fix checks the NEAREST boundary, which here is the Subquery.)
    sql = """
    WITH cte_x AS (
        SELECT sub.a FROM (SELECT * FROM silver.t) AS sub
    )
    SELECT a FROM cte_x;
    """
    findings = run(sql)
    assert len(findings) == 1
    assert findings[0].rule_id == "SQL-NO-SELECT-STAR"
    assert findings[0].line == 3  # the derived-table SELECT * line


def test_select_star_in_scalar_subquery_inside_cte_flagged():
    sql = """
    WITH cte_x AS (
        SELECT (SELECT * FROM gold.f) AS c FROM silver.t
    )
    SELECT c FROM cte_x;
    """
    assert len(run(sql)) == 1
