"""SQL-SILVER-PASCALCASE (§1): silver/gold output columns use PascalCase.

Standard §1 requires silver/gold output columns to be PascalCase
(``CustomerId``), while bronze preserves raw source names. This rule inspects
the *output* projection of every silver/gold view or CTAS and flags any
explicit alias whose name is clearly not PascalCase.

Precision over recall: only an explicit ``AS`` alias is judged. Bare columns
(``SELECT contactid``), ``*``, and already-PascalCase names are never flagged,
and only top-level output projections are examined — aliases inside an inner
CTE or subquery are intermediate, not the object's output.

When the defining query is a set operation (``UNION`` / ``UNION ALL`` /
``EXCEPT`` / ``INTERSECT``), the leftmost ``SELECT`` supplies the object's
output column names, so we descend to it and apply the same alias check.
"""

from __future__ import annotations

import re

from sqlglot import exp

from coop_sql_review.finding import Finding
from coop_sql_review.rules.base import Rule, RuleContext
from coop_sql_review.sql_common import table_parts

_PASCAL_CASE = re.compile(r"^[A-Z][A-Za-z0-9]*$")


def _create_key(create: exp.Create) -> str | None:
    """Normalized ``schema.name`` of a CREATE's target table, or None."""
    target = create.this
    table = target.this if isinstance(target, exp.Schema) else target
    if not isinstance(table, exp.Table):
        return None
    schema, name = table_parts(table)
    return f"{schema}.{name}"


def _output_select(query: exp.Expression | None) -> exp.Select | None:
    """The SELECT whose projections are the object's output columns, or None.

    For a set operation (``UNION``/``EXCEPT``/``INTERSECT``) the leftmost
    SELECT names the outputs, so descend its ``.left`` chain.
    """
    while isinstance(query, exp.SetOperation):
        query = query.left
    return query if isinstance(query, exp.Select) else None


def check(ctx: RuleContext) -> list[Finding]:
    # Silver/gold views and CTAS tables, keyed by normalized schema.name.
    targets = {
        f"{obj.schema}.{obj.name}": obj
        for obj in ctx.parsed.objects
        if (obj.kind == "view" or obj.is_ctas) and obj.layer in ("silver", "gold")
    }
    if not targets:
        return []

    findings: list[Finding] = []
    for batch, create in ctx.parsed.find_all(exp.Create):
        obj = targets.get(_create_key(create) or "")
        if obj is None:
            continue
        # The defining query's top-level projection is the object's output;
        # inner CTE/subquery aliases are not output names, so skip them. For a
        # set operation the leftmost SELECT supplies the output column names.
        select = _output_select(create.expression)
        if select is None:
            continue
        for projection in select.expressions:
            if not isinstance(projection, exp.Alias):
                continue  # bare column / star — raw name not asserted by an alias
            name = projection.alias_or_name
            if name and not _PASCAL_CASE.match(name):
                findings.append(
                    ctx.finding(
                        line=ctx.parsed.node_line(batch, projection),
                        object=f"{obj.schema}.{obj.name}",
                        message=f"silver/gold output '{name}' should be PascalCase (§1).",
                    )
                )
    return findings


RULE = Rule(
    id="SQL-SILVER-PASCALCASE",
    title="Silver/gold output columns use PascalCase",
    severity="info",
    category="naming",
    standard_ref="§1",
    tier=3,
    check=check,
)
