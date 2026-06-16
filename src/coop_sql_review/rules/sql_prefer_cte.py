"""SQL-PREFER-CTE (§4): prefer named CTEs over derived-table subqueries.

§4 favors ``WITH cte_... AS (...)`` over inline ``FROM (SELECT ...) sub`` for
readability in pipelines. The rule flags only *derived-table* subqueries — an
``exp.Subquery`` sitting directly in a ``FROM`` or ``JOIN`` *and* wrapping an
actual query (``exp.Query`` — Select/Union/etc.) — and deliberately leaves
*scalar* subqueries (in ``SELECT``/``WHERE`` comparisons) alone, since those are
not derived tables and don't have a clean CTE rewrite. Parenthesized table refs
and join groups (e.g. ``FROM (gold.a) a`` or ``JOIN (a JOIN b ON ...)``) also
parse as ``exp.Subquery`` but wrap an ``exp.Table``/``exp.Join``, not a query,
so they are not flagged.
"""

from __future__ import annotations

from sqlglot import exp

from coop_sql_review.rules.base import Rule, RuleContext
from coop_sql_review.rules.helpers import enclosing_object
from coop_sql_review.finding import Finding


def check(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    for batch, sub in ctx.parsed.find_all(exp.Subquery):
        # Only derived tables — a subquery whose parent is FROM or JOIN and
        # which wraps an actual query (not a parenthesized table ref / join
        # group, whose ``.this`` is an exp.Table / exp.Join).
        if isinstance(sub.parent, (exp.From, exp.Join)) and isinstance(sub.this, exp.Query):
            findings.append(
                ctx.finding(
                    line=ctx.parsed.node_line(batch, sub),
                    object=enclosing_object(sub),
                    message=(
                        "derived-table subquery in FROM — prefer a named CTE (cte_...) for readability (§4)."
                    ),
                )
            )
    return findings


RULE = Rule(
    id="SQL-PREFER-CTE",
    title="Prefer CTEs over derived-table subqueries",
    severity="info",
    category="ctes",
    standard_ref="§4",
    tier=2,
    check=check,
)
