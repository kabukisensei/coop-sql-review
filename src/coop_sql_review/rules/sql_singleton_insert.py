"""SQL-SINGLETON-INSERT (§9): avoid ``INSERT ... VALUES`` at scale.

In Microsoft Fabric DW each ``INSERT ... VALUES`` batch lands a tiny Parquet
file; many of them fragment storage and hurt scans. Prefer set-based loads —
``INSERT ... SELECT``, ``CTAS``, or ``COPY INTO``.

Detection looks at the insert's DIRECT source (``insert.expression``): only a
top-level :class:`exp.Values` is flagged. ``INSERT ... SELECT`` is never
flagged even when the SELECT reads a table-value constructor (``... FROM
(VALUES ...) AS v``) — descending into the SELECT subtree would wrongly flag
those legitimate set-based loads.
"""

from __future__ import annotations

from sqlglot import exp

from coop_sql_review.rules.base import Rule, RuleContext
from coop_sql_review.rules.helpers import dml_target
from coop_sql_review.finding import Finding


def check(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    for batch, insert in ctx.parsed.find_all(exp.Insert):
        source = insert.expression
        if not isinstance(source, exp.Values):
            continue  # INSERT ... SELECT / CTAS-style loads are fine
        rows = len(source.expressions)  # one entry per VALUES row
        findings.append(
            ctx.finding(
                line=ctx.parsed.node_line(batch, insert),
                object=dml_target(insert),
                message=(
                    f"INSERT ... VALUES ({rows} row(s)) — on Fabric DW each VALUES "
                    "batch lands a tiny Parquet file; prefer INSERT...SELECT or CTAS (§9)."
                ),
            )
        )
    return findings


RULE = Rule(
    id="SQL-SINGLETON-INSERT",
    title="Avoid singleton INSERT ... VALUES",
    severity="warning",
    category="inserts",
    standard_ref="§9",
    tier=1,
    check=check,
)
