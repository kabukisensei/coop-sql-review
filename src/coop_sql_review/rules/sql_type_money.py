"""SQL-TYPE-MONEY (§9): prefer ``decimal(19,4)`` over ``money``/``smallmoney``.

Fabric DW does not support ``money`` or ``smallmoney`` for tables; an explicit
``decimal(19,4)`` is the recommended alternative (it can't store the monetary
unit, per MS guidance). Flag every CREATE TABLE column declared with either.
Fabric-DW-only — Azure SQL supports these, so this rule is skipped under
``--target azure-sql``.
"""

from __future__ import annotations

from coop_sql_review.rules.base import FABRIC_ONLY, Rule, RuleContext
from coop_sql_review.finding import Finding

# base_type -> the name to show in the message.
_MONEY = {"MONEY": "money", "SMALLMONEY": "smallmoney"}


def check(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    for obj in ctx.parsed.objects:
        if obj.kind != "table":
            continue
        for col in obj.columns:
            label = _MONEY.get(col.base_type)
            if label:
                findings.append(
                    ctx.finding(
                        line=col.line,
                        object=f"{obj.schema}.{obj.name}",
                        message=f"column {col.name} uses {label} — unsupported by Fabric DW; use decimal(19,4) (§9).",
                    )
                )
    return findings


RULE = Rule(
    id="SQL-TYPE-MONEY",
    title="Prefer decimal(19,4) over money/smallmoney",
    severity="warning",
    category="datatypes",
    standard_ref="§9",
    tier=1,
    targets=FABRIC_ONLY,
    check=check,
)
