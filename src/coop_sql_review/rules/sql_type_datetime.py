"""SQL-TYPE-DATETIME (§9): prefer ``datetime2`` over ``datetime`` and friends.

Fabric DW does not support ``datetime``, ``smalldatetime``, or ``datetimeoffset``
for tables; ``datetime2`` is the recommended alternative (for datetimeoffset you
can still CAST + AT TIME ZONE at query time). ``datetime2`` itself (base_type
``DATETIME2``) is explicitly left alone. Fabric-DW-only — skipped under
``--target azure-sql``.
"""

from __future__ import annotations

from coop_sql_review.rules.base import FABRIC_ONLY, Rule, RuleContext
from coop_sql_review.finding import Finding

# base_type -> the name to show. sqlglot's tsql dialect normalizes datetimeoffset to
# TIMESTAMPTZ (nothing else maps there), so it stands in for datetimeoffset.
_DATETIME = {"DATETIME": "datetime", "SMALLDATETIME": "smalldatetime", "TIMESTAMPTZ": "datetimeoffset"}


def check(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    for obj in ctx.parsed.objects:
        if obj.kind != "table":
            continue
        for col in obj.columns:
            label = _DATETIME.get(col.base_type)
            if label:
                findings.append(
                    ctx.finding(
                        line=col.line,
                        object=f"{obj.schema}.{obj.name}",
                        message=f"column {col.name} uses {label} — unsupported by Fabric DW; use datetime2 (§9).",
                    )
                )
    return findings


RULE = Rule(
    id="SQL-TYPE-DATETIME",
    title="Prefer datetime2 over datetime/smalldatetime/datetimeoffset",
    severity="warning",
    category="datatypes",
    standard_ref="§9",
    tier=1,
    targets=FABRIC_ONLY,
    check=check,
)
