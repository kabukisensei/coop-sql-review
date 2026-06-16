"""SQL-CTAS-EXPLICIT-CAST (§9): wrap CTAS aggregate outputs in explicit CAST.

§9 (CTAS Best Practices) recommends wrapping aggregate outputs in an explicit
``CAST(...)`` so the materialized column type is pinned rather than inferred
(e.g. ``CAST(SUM(Revenue) AS decimal(19,4))``). This rule scopes to CTAS
selects (``CREATE TABLE ... AS SELECT``, including set-operation CTAS where each
``UNION``/``UNION ALL`` arm is checked independently) and flags any projection
that *produces* an aggregate whose top-level output does not pin a type. A
``CAST``/``TRY_CAST`` or a ``CONVERT(type, ...)`` wrapping the output pins it; an
``ISNULL``/``COALESCE`` is transparent and is unwrapped to its first argument
before that check, so ``COALESCE(CAST(SUM(x) AS int), 0)`` counts as pinned. A
cast *inside* the aggregate (``SUM(CAST(x AS int))``) still leaves the
aggregate's own output type uncontrolled, so it is intentionally still flagged.
Windowed aggregates (``SUM(x) OVER (...)``) are per-row, not the grouped CTAS
aggregate §9 is about, so they are out of scope and skipped.
"""

from __future__ import annotations

from sqlglot import exp

from coop_sql_review.finding import Finding
from coop_sql_review.rules.base import Rule, RuleContext
from coop_sql_review.rules.helpers import enclosing_object

# Wrappers that pin the output type as effectively as a bare CAST.
_PINNING = (exp.Cast, exp.Convert)


def _unwrap_transparent(node: exp.Expression) -> exp.Expression:
    """Peel off type-transparent ``ISNULL``/``COALESCE`` to their first argument.

    These default-substitution wrappers don't change the materialized type, so a
    cast on the value they wrap (``COALESCE(CAST(SUM(x) AS int), 0)``) still pins
    it. ``ISNULL`` parses either as ``exp.Coalesce`` or as an ``exp.Anonymous``
    named ``ISNULL`` depending on dialect, so both are handled.
    """
    while True:
        if isinstance(node, exp.Coalesce):
            args = [node.this, *(node.expressions or [])]
            if not args:
                return node
            node = args[0]
        elif isinstance(node, exp.Anonymous) and node.name.upper() == "ISNULL" and node.expressions:
            node = node.expressions[0]
        else:
            return node


def _output_selects(node: exp.Expression) -> list[exp.Select]:
    """The SELECT(s) whose projections become the CTAS output columns.

    Walks only the set-operation spine (each UNION/EXCEPT/INTERSECT arm,
    unwrapping parentheses) — deliberately NOT into a SELECT's own WHERE/IN/
    scalar subqueries or FROM-clause derived tables, whose aggregates are not
    materialized as output columns and must not be flagged.
    """
    if isinstance(node, exp.Subquery):
        return _output_selects(node.this)
    if isinstance(node, exp.Select):
        return [node]
    if isinstance(node, exp.SetOperation):
        return _output_selects(node.left) + _output_selects(node.right)
    return []


def check(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    for batch, create in ctx.parsed.find_all(exp.Create):
        if create.args.get("kind") != "TABLE":
            continue
        # Plain CTAS is one SELECT; a set-operation CTAS contributes one output
        # SELECT per arm. Only these arms' top-level projections are output
        # columns — nested subqueries/derived tables are not.
        for select in _output_selects(create.expression):
            for projection in select.expressions:
                # The output expression, ignoring any trailing ``AS alias``.
                output = projection.this if isinstance(projection, exp.Alias) else projection
                # Nothing to pin unless this projection produces an aggregate.
                if not any(projection.find_all(exp.AggFunc)):
                    continue
                # A windowed aggregate is per-row, not the grouped CTAS
                # aggregate §9 targets — out of scope.
                if any(projection.find_all(exp.Window)):
                    continue
                # Transparent ISNULL/COALESCE wrappers preserve the inner type.
                pinned = _unwrap_transparent(output)
                # A CAST/TRY_CAST or CONVERT(type, ...) pins the materialized type.
                if isinstance(pinned, _PINNING):
                    continue
                name = projection.alias_or_name
                if not name or name == "*":
                    name = output.sql()
                findings.append(
                    ctx.finding(
                        line=ctx.parsed.node_line(batch, projection),
                        object=enclosing_object(projection),
                        message=(
                            f"CTAS aggregate output '{name}' is not wrapped in CAST(...) "
                            "— pin its type explicitly (§9)."
                        ),
                    )
                )
    return findings


RULE = Rule(
    id="SQL-CTAS-EXPLICIT-CAST",
    title="Wrap CTAS aggregate outputs in explicit CAST",
    severity="info",
    category="ctas",
    standard_ref="§9",
    tier=3,
    check=check,
)
