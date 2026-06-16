"""SQL-TYPE-DEPRECATED (§9): no deprecated ``text``/``ntext``/``image`` types.

These large-object types are deprecated; Fabric DW code should use the
``(max)`` variants instead. ``text`` and ``ntext`` both surface as base_type
``TEXT`` (sqlglot folds ntext into text) and map to ``varchar(max)``; ``image``
maps to ``varbinary(max)``.
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
            if col.base_type == "TEXT":
                message = f"column {col.name} uses deprecated type text/ntext — use varchar(max) (§9)."
            elif col.base_type == "IMAGE":
                message = f"column {col.name} uses deprecated type image — use varbinary(max) (§9)."
            else:
                continue
            findings.append(
                ctx.finding(
                    line=col.line,
                    object=f"{obj.schema}.{obj.name}",
                    message=message,
                )
            )
    return findings


RULE = Rule(
    id="SQL-TYPE-DEPRECATED",
    title="No deprecated text/ntext/image types",
    severity="warning",
    category="datatypes",
    standard_ref="§9",
    tier=1,
    check=check,
)
