"""Tests for SQL-CTAS-EXPLICIT-CAST (§9)."""

from __future__ import annotations

from coop_sql_review.parser import parse_sql
from coop_sql_review.rules.base import RuleContext
from coop_sql_review.rules.sql_ctas_explicit_cast import RULE


def run(sql):
    p = parse_sql("t.sql", sql)
    return (RULE.check if RULE.check else RULE.detect)(RuleContext(RULE, p))


def test_flags_unwrapped_aggregate():
    findings = run("CREATE TABLE gold.s AS SELECT SUM(x) AS Total FROM t")
    assert len(findings) == 1
    assert "Total" in findings[0].message
    assert findings[0].object == "gold.s"


# --- regression: only OUTPUT projections are aggregates worth pinning;
#     aggregates in WHERE/IN/scalar subqueries or derived tables are NOT
#     output columns and must not be flagged. ---


def test_aggregate_in_where_subquery_not_flagged():
    assert run("CREATE TABLE gold.s AS SELECT t.id FROM t WHERE t.x > (SELECT AVG(y) FROM u)") == []


def test_aggregate_in_in_subquery_not_flagged():
    assert run("CREATE TABLE gold.s AS SELECT id FROM t WHERE id IN (SELECT MAX(k) FROM u)") == []


def test_pinned_output_over_scalar_subquery_aggregate_not_flagged():
    assert run("CREATE TABLE gold.s AS SELECT CAST((SELECT SUM(a) FROM u) AS int) AS T FROM t") == []


def test_aggregate_in_derived_table_not_flagged():
    assert run("CREATE TABLE gold.s AS SELECT CAST(z.s AS int) AS T FROM (SELECT SUM(a) AS s FROM u) z") == []


def test_union_ctas_flags_only_unpinned_arm():
    findings = run(
        "CREATE TABLE gold.s AS SELECT CAST(SUM(a) AS int) AS T FROM x UNION ALL SELECT SUM(b) AS T FROM y"
    )
    assert len(findings) == 1  # only the second arm's bare SUM(b)


def test_does_not_flag_cast_wrapped_aggregate():
    assert run("CREATE TABLE gold.s AS SELECT CAST(SUM(x) AS decimal(19,4)) AS Total FROM t") == []


def test_try_cast_also_counts_as_wrapped():
    assert run("CREATE TABLE gold.s AS SELECT TRY_CAST(SUM(x) AS decimal(19,4)) AS Total FROM t") == []


def test_ignores_non_aggregate_projections():
    assert run("CREATE TABLE gold.s AS SELECT c1, c2 FROM t") == []


def test_ignores_plain_create_table():
    assert run("CREATE TABLE gold.s (a int, b int)") == []


def test_cast_inside_aggregate_is_still_flagged():
    # The CAST controls the input type, not the aggregate's materialized
    # output type — so the output remains unpinned and must be flagged.
    findings = run("CREATE TABLE gold.s AS SELECT SUM(CAST(x AS int)) AS Total FROM t")
    assert len(findings) == 1
    assert "Total" in findings[0].message


def test_only_unwrapped_projections_in_a_mix_are_flagged():
    findings = run(
        "CREATE TABLE gold.s AS SELECT CAST(SUM(a) AS int) AS A, AVG(b) AS B, c1, MAX(c) FROM t GROUP BY c1"
    )
    names = sorted(f.message for f in findings)
    assert len(findings) == 2
    assert any("'B'" in m for m in names)
    assert any("MAX(c)" in m for m in names)


def test_coalesce_wrapping_cast_is_not_flagged():
    # COALESCE is type-transparent; the inner CAST still pins the type.
    assert run("CREATE TABLE gold.s AS SELECT COALESCE(CAST(SUM(a) AS int),0) AS T FROM x") == []


def test_isnull_wrapping_cast_is_not_flagged():
    assert run("CREATE TABLE gold.s AS SELECT ISNULL(CAST(SUM(a) AS int),0) AS T FROM x") == []


def test_convert_pins_type_like_cast():
    # CONVERT(type, agg) pins the materialized type just like CAST.
    assert run("CREATE TABLE gold.s AS SELECT CONVERT(decimal(19,4),SUM(x)) AS T FROM x") == []


def test_windowed_aggregate_is_out_of_scope():
    # SUM(..) OVER(..) is a per-row window function, not the grouped CTAS aggregate.
    assert run("CREATE TABLE gold.s AS SELECT SUM(x) OVER(PARTITION BY g) AS R FROM t") == []


def test_set_operation_ctas_flags_unpinned_arm():
    # Each UNION arm is checked; the second arm's SUM(b) is unpinned.
    findings = run(
        "CREATE TABLE gold.s AS SELECT CAST(SUM(a) AS int) AS T FROM x UNION ALL SELECT SUM(b) AS T FROM y"
    )
    assert len(findings) == 1
    assert "'T'" in findings[0].message
    assert findings[0].object == "gold.s"


def test_unaliased_count_star_uses_expression_for_name():
    # An unaliased COUNT(*) must not be named '*' in the message.
    findings = run("CREATE TABLE gold.s AS SELECT COUNT(*) FROM t")
    assert len(findings) == 1
    assert "'*'" not in findings[0].message
    assert "COUNT(*)" in findings[0].message
