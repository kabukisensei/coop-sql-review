"""SQL-TYPE-NVARCHAR (§9): prefer ``varchar`` over ``nvarchar``.

Fabric DW stores character data as UTF-8, so ``nvarchar`` buys no Unicode
coverage that ``varchar`` lacks while costing storage; flag every CREATE
TABLE column declared ``nvarchar``.
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
            if col.base_type == "NVARCHAR":
                findings.append(
                    ctx.finding(
                        line=col.line,
                        object=f"{obj.schema}.{obj.name}",
                        message=f"column {col.name} uses nvarchar — Fabric DW is UTF-8; use varchar (§9).",
                    )
                )
    return findings


RULE = Rule(
    id="SQL-TYPE-NVARCHAR",
    title="Prefer varchar over nvarchar",
    severity="warning",
    category="datatypes",
    standard_ref="§9",
    tier=1,
    check=check,
)
