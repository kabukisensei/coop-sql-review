"""Tests for the §A/§E/§F proposed-addition rules:
SQL-SARGABILITY, SQL-ORDER-BY-IN-VIEW, SQL-DISTINCT-SMELL.
"""

from __future__ import annotations

from coop_sql_review.parser import parse_sql
from coop_sql_review.rules.base import RuleContext
from coop_sql_review.rules.sql_distinct_smell import RULE as DISTINCT_RULE
from coop_sql_review.rules.sql_order_by_in_view import RULE as ORDER_RULE
from coop_sql_review.rules.sql_sargability import RULE as SARG_RULE


def _run(rule, sql):
    parsed = parse_sql("t.sql", sql)
    fn = rule.check if rule.check else rule.detect
    return fn(RuleContext(rule, parsed))


# -- SQL-SARGABILITY (§A) ---------------------------------------------------


def test_sargability_flags_function_on_filtered_column():
    # POSITIVE: YEAR(col) = 2026 wraps the column in a function.
    findings = _run(SARG_RULE, "SELECT a FROM t WHERE YEAR(SalesDate) = 2026")
    assert len(findings) == 1
    assert findings[0].rule_id == "SQL-SARGABILITY"


def test_sargability_allows_bare_column_range():
    # NEGATIVE: bare column compared to a range literal is SARGable.
    findings = _run(SARG_RULE, "SELECT a FROM t WHERE SalesDate >= '2026-01-01'")
    assert findings == []


def test_sargability_flags_function_in_join_on():
    # EDGE: function-on-column inside a JOIN ON predicate is flagged too.
    findings = _run(SARG_RULE, "SELECT 1 FROM a JOIN b ON a.id = YEAR(b.dt)")
    assert len(findings) == 1


def test_sargability_ignores_function_without_column():
    # EDGE: a function whose arguments are only literals takes no column.
    findings = _run(SARG_RULE, "SELECT a FROM t WHERE DATEPART(year, 2026) = col")
    assert findings == []


def test_sargability_ignores_case_expression():
    # REGRESSION (FP): exp.Case is an exp.Func subclass but is not a
    # column-wrapping function — a CASE expression compared to a literal is fine.
    findings = _run(
        SARG_RULE,
        "SELECT a FROM t WHERE CASE WHEN region = 'US' THEN tax ELSE 0 END = 5",
    )
    assert findings == []


def test_sargability_exists_subquery_no_duplicate():
    # REGRESSION (dup): the outer WHERE's find_all recurses into the EXISTS
    # subquery's WHERE, surfacing the same comparison twice — report it once.
    findings = _run(
        SARG_RULE,
        "SELECT 1 FROM x WHERE EXISTS (SELECT 1 FROM t WHERE YEAR(t.d) = 2026)",
    )
    assert len(findings) == 1


def test_sargability_bare_column_range_not_flagged():
    # REGRESSION: a bare column compared to a range is SARGable -> 0 findings.
    findings = _run(SARG_RULE, "SELECT a FROM t WHERE SalesDate >= '2026-01-01'")
    assert findings == []


def test_sargability_function_on_column_still_flagged():
    # REGRESSION: the genuine non-SARGable predicate is still flagged exactly once.
    findings = _run(SARG_RULE, "SELECT a FROM t WHERE YEAR(SalesDate) = 2026")
    assert len(findings) == 1


def test_sargability_flags_function_in_in_membership():
    # POSITIVE (§A): func(col) IN (...) is as non-SARGable as func(col) = x.
    findings = _run(SARG_RULE, "SELECT a FROM t WHERE YEAR(d) IN (2024, 2025)")
    assert len(findings) == 1
    assert findings[0].rule_id == "SQL-SARGABILITY"


def test_sargability_flags_function_in_between():
    # POSITIVE (§A): func(col) BETWEEN a AND b wraps the column too.
    findings = _run(SARG_RULE, "SELECT a FROM t WHERE YEAR(d) BETWEEN 2024 AND 2025")
    assert len(findings) == 1


def test_sargability_flags_function_with_neq():
    # POSITIVE (§A): <> is a comparison like any other.
    findings = _run(SARG_RULE, "SELECT a FROM t WHERE YEAR(d) <> 2024")
    assert len(findings) == 1


def test_sargability_flags_arithmetic_on_column_side():
    # POSITIVE (§A names `col + x` verbatim): arithmetic wrapping the filtered column.
    add = _run(SARG_RULE, "SELECT a FROM t WHERE qty + 1 > 100")
    mul = _run(SARG_RULE, "SELECT a FROM t WHERE amount * 1.1 >= 50")
    assert len(add) == 1
    assert len(mul) == 1


def test_sargability_bare_column_in_membership_not_flagged():
    # NEGATIVE: a bare column tested for membership is SARGable.
    assert _run(SARG_RULE, "SELECT a FROM t WHERE region IN ('US', 'CA')") == []


def test_sargability_bare_column_in_subquery_not_flagged():
    # NEGATIVE: col IN (SELECT ...) keeps the filtered column bare; only the
    # membership's `this` side matters, never the subquery's own projection.
    assert _run(SARG_RULE, "SELECT a FROM t WHERE id IN (SELECT id FROM u)") == []


def test_sargability_bare_column_between_not_flagged():
    # NEGATIVE: a bare column ranged with BETWEEN is the §A "Prefer" pattern.
    assert _run(SARG_RULE, "SELECT a FROM t WHERE d BETWEEN @lo AND @hi") == []


def test_sargability_value_side_arithmetic_not_flagged():
    # NEGATIVE: the computation sits on the VALUE side; the filtered column (x)
    # stays bare, so the predicate is still SARGable on x.
    assert _run(SARG_RULE, "SELECT a FROM t WHERE x > qty + 1") == []


def test_sargability_literal_arithmetic_not_flagged():
    # NEGATIVE: arithmetic over literals wraps no column at all.
    assert _run(SARG_RULE, "SELECT a FROM t WHERE x > 100 + 1") == []


# -- SQL-SARGABILITY x SQL-JOIN-FILTER alignment tolerance (issue #15) -------


def test_sargability_coalesce_alignment_join_not_flagged():
    # NEGATIVE: SQL-JOIN-FILTER documents COALESCE-on-both-keys as idiomatic
    # alignment; this rule must not demand a rewrite of the same predicate.
    sql = "SELECT 1 FROM silver.a AS a JOIN silver.b AS b ON COALESCE(a.id, 0) = COALESCE(b.id, 0)"
    assert _run(SARG_RULE, sql) == []


def test_sargability_nested_alignment_wrapper_join_not_flagged():
    # NEGATIVE: nested wrappers (CAST around COALESCE) are still pure alignment.
    sql = "SELECT 1 FROM a JOIN b ON CAST(COALESCE(a.id, 0) AS INT) = b.id"
    assert _run(SARG_RULE, sql) == []


def test_sargability_where_coalesce_still_flagged_with_filter_message():
    # POSITIVE: the tolerance is join-only — a COALESCE in WHERE still fires,
    # with the WHERE-oriented message.
    findings = _run(SARG_RULE, "SELECT a FROM t WHERE COALESCE(col, 0) = 1")
    assert len(findings) == 1
    assert "filter the bare column" in findings[0].message


def test_sargability_join_business_function_gets_join_message():
    # POSITIVE: a genuine function on a join key still fires, but with the
    # join-oriented message — never the WHERE "filter the bare column with a
    # range" advice, which makes no sense for a join key.
    findings = _run(SARG_RULE, "SELECT 1 FROM a JOIN b ON YEAR(a.d) = b.y")
    assert len(findings) == 1
    assert "join" in findings[0].message
    assert "filter the bare column" not in findings[0].message


def test_sargability_alignment_wrapping_business_function_still_flagged():
    # POSITIVE: a wrapper enclosing a real function is not benign alignment —
    # consistent with SQL-JOIN-FILTER, which also flags this shape.
    findings = _run(SARG_RULE, "SELECT 1 FROM a JOIN b ON CAST(YEAR(a.d) AS INT) = b.y")
    assert len(findings) == 1


def test_sargability_flag_alignment_joins_param_reenables():
    # The strict statistics story is available via params (documented in RULES.md).
    from dataclasses import replace

    sql = "SELECT 1 FROM a JOIN b ON COALESCE(a.id, 0) = COALESCE(b.id, 0)"
    strict = replace(SARG_RULE, params={"flag_alignment_joins": True})
    findings = _run(strict, sql)
    assert len(findings) == 1
    assert "join" in findings[0].message


def test_sargability_where_inside_join_subquery_is_a_where_site():
    # EDGE: a WHERE nested inside a subquery in an ON clause is a WHERE site —
    # it keeps the WHERE message and no alignment tolerance applies.
    sql = "SELECT 1 FROM a JOIN b ON a.id = (SELECT MAX(x.id) FROM x WHERE YEAR(x.d) = 2024)"
    findings = _run(SARG_RULE, sql)
    assert len(findings) == 1
    assert "filter the bare column" in findings[0].message


def test_sargability_alignment_join_inside_where_subquery_not_flagged():
    # EDGE: an alignment join nested inside an EXISTS subquery is still a JOIN
    # site (the outer WHERE scan reaches it first) — the tolerance must hold.
    sql = "SELECT a.x FROM a WHERE EXISTS (SELECT 1 FROM b JOIN c ON COALESCE(b.id, 0) = COALESCE(c.id, 0))"
    assert _run(SARG_RULE, sql) == []


# -- SQL-ORDER-BY-IN-VIEW (§E) ----------------------------------------------


def test_order_by_in_view_flags_view_body():
    # POSITIVE: ORDER BY in a CREATE VIEW body with no TOP.
    findings = _run(ORDER_RULE, "CREATE VIEW v AS SELECT a FROM t ORDER BY a")
    assert len(findings) == 1
    assert findings[0].rule_id == "SQL-ORDER-BY-IN-VIEW"


def test_order_by_in_cte_and_subquery():
    # EDGE: also flagged inside a CTE and inside a derived-table subquery.
    cte = _run(ORDER_RULE, "WITH x AS (SELECT a FROM t ORDER BY a) SELECT b FROM x")
    sub = _run(ORDER_RULE, "SELECT z FROM (SELECT a FROM t ORDER BY a) d")
    assert len(cte) == 1
    assert len(sub) == 1


def test_order_by_top_level_allowed():
    # NEGATIVE: a top-level result-set ORDER BY is allowed.
    findings = _run(ORDER_RULE, "SELECT a FROM t ORDER BY a")
    assert findings == []


def test_order_by_with_top_allowed():
    # NEGATIVE/EDGE: ORDER BY paired with TOP in a view is valid.
    findings = _run(ORDER_RULE, "CREATE VIEW v AS SELECT TOP 10 a FROM t ORDER BY a")
    assert findings == []


def test_order_by_window_function_in_cte_not_flagged():
    # REGRESSION (FP): OVER (ORDER BY ...) is a meaningful window ordering, not a
    # result-set ORDER BY — even inside a CTE it must not be flagged.
    findings = _run(
        ORDER_RULE,
        "WITH c AS (SELECT ROW_NUMBER() OVER (ORDER BY a) rn FROM t) SELECT * FROM c",
    )
    assert findings == []


def test_order_by_within_group_aggregate_not_flagged():
    # REGRESSION (FP): WITHIN GROUP (ORDER BY ...) ordered aggregates are
    # meaningful (STRING_AGG -> GroupConcat, PERCENTILE_CONT -> WithinGroup).
    string_agg = _run(
        ORDER_RULE,
        "CREATE VIEW v AS SELECT STRING_AGG(a, ',') WITHIN GROUP (ORDER BY a) FROM t",
    )
    percentile = _run(
        ORDER_RULE,
        "CREATE VIEW v AS SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY a) OVER () FROM t",
    )
    assert string_agg == []
    assert percentile == []


def test_order_by_real_view_body_still_flagged():
    # REGRESSION: a genuine result-set ORDER BY in a view body is still flagged.
    findings = _run(ORDER_RULE, "CREATE VIEW gold.v AS SELECT a FROM t ORDER BY a")
    assert len(findings) == 1


def test_order_by_top_level_with_top_not_flagged():
    # REGRESSION: top-level SELECT TOP n ... ORDER BY is a real ordered result.
    findings = _run(ORDER_RULE, "SELECT TOP 10 a FROM t ORDER BY a")
    assert findings == []


# -- SQL-DISTINCT-SMELL (§F) ------------------------------------------------


def test_distinct_smell_flags_select_distinct():
    # POSITIVE: SELECT DISTINCT.
    findings = _run(DISTINCT_RULE, "SELECT DISTINCT a FROM t")
    assert len(findings) == 1
    assert findings[0].rule_id == "SQL-DISTINCT-SMELL"
    assert findings[0].severity == "info"


def test_distinct_smell_ignores_plain_select():
    # NEGATIVE: a plain SELECT is not flagged.
    findings = _run(DISTINCT_RULE, "SELECT a FROM t")
    assert findings == []


def test_distinct_smell_ignores_aggregate_internal_distinct():
    # REGRESSION (FP): COUNT(DISTINCT x) is an aggregate-internal DISTINCT, not a
    # statement-level SELECT DISTINCT — it must not be flagged.
    findings = _run(DISTINCT_RULE, "SELECT COUNT(DISTINCT a) FROM t")
    assert findings == []


def test_distinct_smell_real_select_distinct_still_flagged():
    # REGRESSION: a genuine SELECT DISTINCT is still flagged exactly once.
    findings = _run(DISTINCT_RULE, "SELECT DISTINCT a FROM t")
    assert len(findings) == 1


def test_distinct_smell_line_points_at_select_not_batch_start():
    # REGRESSION: the empty exp.Distinct node has no line-bearing leaf, so
    # anchoring on it falls back to the batch start line. Anchor on the SELECT
    # (which has line-bearing leaves) so the line points at the DISTINCT itself.
    findings = _run(DISTINCT_RULE, "\n\nSELECT DISTINCT a, b FROM t")
    assert len(findings) == 1
    assert findings[0].line == 3


def test_order_by_with_offset_allowed():
    # REGRESSION (FP): ORDER BY ... OFFSET is honored by T-SQL inside a
    # view/derived table (like TOP and FETCH) — paging subqueries must not be
    # flagged; "remove the ORDER BY" would even be a syntax error with OFFSET.
    offset_only = _run(ORDER_RULE, "SELECT * FROM (SELECT c FROM silver.t ORDER BY c OFFSET 10 ROWS) AS x")
    assert offset_only == []


def test_order_by_with_offset_fetch_allowed():
    # OFFSET ... FETCH parses into the `limit` arg and was already tolerated —
    # pin it so the two paging spellings stay consistent.
    sql = "SELECT * FROM (SELECT c FROM silver.t ORDER BY c OFFSET 10 ROWS FETCH NEXT 5 ROWS ONLY) AS x"
    assert _run(ORDER_RULE, sql) == []
