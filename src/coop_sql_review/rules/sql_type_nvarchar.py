"""SQL-TYPE-NVARCHAR (§9): prefer ``varchar``/``char`` over ``nvarchar``/``nchar``.

Fabric DW does not support ``nchar``/``nvarchar`` for tables and stores character
data as UTF-8, so ``char``/``varchar`` cover the same Unicode data (they may use
more storage — see the MS UTF-8 vs UTF-16 note). Flag every CREATE TABLE column
declared ``nchar`` or ``nvarchar``. Fabric-DW-only — skipped under
``--target azure-sql``.
"""

from __future__ import annotations

from coop_sql_review.rules.base import FABRIC_ONLY, Rule, RuleContext
from coop_sql_review.finding import Finding

# base_type -> (name to show, recommended alternative).
_NCHAR = {"NVARCHAR": ("nvarchar", "varchar"), "NCHAR": ("nchar", "char")}


def check(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    for obj in ctx.parsed.objects:
        if obj.kind != "table":
            continue
        for col in obj.columns:
            entry = _NCHAR.get(col.base_type)
            if entry:
                label, alt = entry
                findings.append(
                    ctx.finding(
                        line=col.line,
                        object=f"{obj.schema}.{obj.name}",
                        message=f"column {col.name} uses {label} — Fabric DW is UTF-8 and doesn't support it; use {alt} (§9).",
                    )
                )
    return findings


RULE = Rule(
    id="SQL-TYPE-NVARCHAR",
    title="Prefer varchar/char over nvarchar/nchar",
    severity="warning",
    category="datatypes",
    standard_ref="§9",
    tier=1,
    targets=FABRIC_ONLY,
    check=check,
)
