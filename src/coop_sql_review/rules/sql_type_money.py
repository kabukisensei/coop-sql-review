"""SQL-TYPE-MONEY (§9): prefer ``decimal(19,4)`` over ``money``.

``money`` has surprising rounding behavior and limited precision; an explicit
``decimal(19,4)`` is the recommended Fabric DW alternative. Flag every CREATE
TABLE column declared ``money``.
"""

from __future__ import annotations

from coop_sql_review.rules.base import Rule, RuleContext
from coop_sql_review.finding import Finding


def check(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    for obj in ctx.parsed.objects:
        if obj.kind != "table":
            continue
        for col in obj.columns:
            if col.base_type == "MONEY":
                findings.append(
                    ctx.finding(
                        line=col.line,
                        object=f"{obj.schema}.{obj.name}",
                        message=f"column {col.name} uses money — use decimal(19,4) (§9).",
                    )
                )
    return findings


RULE = Rule(
    id="SQL-TYPE-MONEY",
    title="Prefer decimal(19,4) over money",
    severity="warning",
    category="datatypes",
    standard_ref="§9",
    tier=1,
    check=check,
)
