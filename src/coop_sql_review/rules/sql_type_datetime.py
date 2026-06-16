"""SQL-TYPE-DATETIME (§9): prefer ``datetime2`` over ``datetime``.

``datetime`` is the legacy type; Fabric DW prefers ``datetime2`` for its wider
range and configurable precision. Matches the ``DATETIME`` keyword only —
``datetime2`` (base_type ``DATETIME2``) is explicitly left alone.
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
            if col.base_type == "DATETIME":
                findings.append(
                    ctx.finding(
                        line=col.line,
                        object=f"{obj.schema}.{obj.name}",
                        message=f"column {col.name} uses datetime — use datetime2 (§9).",
                    )
                )
    return findings


RULE = Rule(
    id="SQL-TYPE-DATETIME",
    title="Prefer datetime2 over datetime",
    severity="warning",
    category="datatypes",
    standard_ref="§9",
    tier=1,
    check=check,
)
