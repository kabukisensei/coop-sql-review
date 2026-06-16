"""SQL-TABLE-LAYER-NAME (§1): tables/views live in a medallion-layer schema.

§1 names objects ``layer.object_name`` where ``layer`` is one of
``bronze`` / ``silver`` / ``gold``. ``SqlObject.layer`` is ``None`` whenever
the schema is not one of those, so the rule simply flags every table/view
whose ``.layer`` is ``None``. Temp objects (``#temp`` / ``##global`` /
``@table``) are not medallion tables and are skipped: sqlglot strips the
``#``/``@`` prefix off the parsed name, so we rely on ``SqlObject.is_temp``
(set from the rendered DDL) rather than a literal prefix check on the name.
"""

from __future__ import annotations

from coop_sql_review.finding import Finding
from coop_sql_review.rules.base import Rule, RuleContext


def check(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    for obj in ctx.parsed.objects:
        if obj.kind not in ("table", "view") or obj.is_temp:
            continue
        if obj.layer is None:
            findings.append(
                ctx.finding(
                    line=obj.line,
                    object=f"{obj.schema}.{obj.name}",
                    message=(
                        f"{obj.kind} {obj.schema}.{obj.name} is not in a medallion-layer "
                        f"schema (bronze/silver/gold) (§1)."
                    ),
                )
            )
    return findings


RULE = Rule(
    id="SQL-TABLE-LAYER-NAME",
    title="Tables live in a medallion-layer schema",
    severity="info",
    category="naming",
    standard_ref="§1",
    tier=2,
    check=check,
)
