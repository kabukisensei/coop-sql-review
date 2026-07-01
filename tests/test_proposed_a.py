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
