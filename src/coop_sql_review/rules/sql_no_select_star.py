"""SQL-NO-SELECT-STAR (§11): no ``SELECT *`` in production code.

``SELECT *`` is acceptable inside an intermediate CTE (e.g. a dedup step
that then narrows columns) or an ``EXISTS(SELECT *)`` predicate (where the
projection is discarded), so the rule scopes to *production* selects — any
projection ``*`` whose select has no CTE or EXISTS ancestor. A derived-table
subquery (``FROM (SELECT * ...) sub``) is NOT exempt: §4 treats that as the
"Bad" pattern to prefer a CTE over. ``COUNT(*)`` and other function-argument
stars are never flagged.
"""

from __future__ import annotations

from sqlglot import exp

from coop_sql_review.rules.base import Rule, RuleContext
from coop_sql_review.rules.helpers import enclosing_object, projection_stars
from coop_sql_review.finding import Finding


def check(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    for batch, select in ctx.parsed.find_all(exp.Select):
        # A CTE's own SELECT or an EXISTS(SELECT *) is intermediate by design — allow *
        # there. A derived-table subquery is production code (§4 Bad pattern), so NOT exempt.
        if select.find_ancestor(exp.CTE, exp.Exists) is not None:
            continue
        for star in projection_stars(select):
            findings.append(
                ctx.finding(
                    line=ctx.parsed.node_line(batch, star),
                    object=enclosing_object(star),
                    message="SELECT * in production code — list the columns explicitly (§11).",
                )
            )
    return findings


RULE = Rule(
    id="SQL-NO-SELECT-STAR",
    title="No SELECT * in production code",
    severity="warning",
    category="select-star",
    standard_ref="§11",
    tier=1,
    check=check,
)
