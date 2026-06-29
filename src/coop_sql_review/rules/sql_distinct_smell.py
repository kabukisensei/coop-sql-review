"""SQL-DISTINCT-SMELL (§F): SELECT DISTINCT can mask a fan-out join bug.

§F (proposed additions): ``DISTINCT`` is often reached for to collapse rows
duplicated by an unintended one-to-many ("fan-out") join, papering over the
real bug instead of fixing the join. It is not always wrong, so this is an
``info`` smell: one finding per ``SELECT DISTINCT`` for a second look. Only a
real statement-level ``SELECT DISTINCT`` (``select.args["distinct"]``) is
flagged; an aggregate-internal ``DISTINCT`` (e.g. ``COUNT(DISTINCT x)``) is a
different construct and is left alone.
"""

from __future__ import annotations

from sqlglot import exp

from coop_sql_review.finding import Finding
from coop_sql_review.rules.base import Rule, RuleContext
from coop_sql_review.rules.helpers import enclosing_object


def check(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    for batch, select in ctx.parsed.find_all(exp.Select):
        distinct = select.args.get("distinct")
        if not distinct:
            continue
        findings.append(
            ctx.finding(
                line=ctx.parsed.node_line(batch, select),
                object=enclosing_object(select),
                message=(
                    "SELECT DISTINCT can mask a fan-out join bug — verify it is necessary "
                    "rather than papering over duplicates (§F)."
                ),
            )
        )
    return findings


RULE = Rule(
    id="SQL-DISTINCT-SMELL",
    title="SELECT DISTINCT may mask a fan-out join bug",
    severity="info",
    category="smell",
    standard_ref="§F",
    tier=3,
    check=check,
)
