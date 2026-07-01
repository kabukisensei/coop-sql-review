"""SQL-ORDER-BY-IN-VIEW (§E): ORDER BY in a view/CTE/subquery is ignored.

§E (proposed additions): an ``ORDER BY`` inside a view body, a CTE, or a
derived-table subquery is not guaranteed to be honored by the engine (it only
takes effect when paired with ``TOP`` or ``OFFSET``) — so it misleads readers
and adds no ordering. This rule flags an ``exp.Order`` whose nearest enclosing
``SELECT`` (a) has no ``TOP``/``LIMIT``/``FETCH`` (which in T-SQL all parse to
the ``limit`` arg) and no ``OFFSET`` (a bare ``OFFSET n ROWS`` parses to the
``offset`` arg), and (b) sits inside a ``CREATE VIEW`` body, an ``exp.CTE``, or
an ``exp.Subquery``. A top-level ``SELECT ... ORDER BY`` (a real result set), a
``SELECT TOP n ... ORDER BY``, and paging ``ORDER BY ... OFFSET`` are allowed.

An ``ORDER BY`` that belongs to a window function (``OVER (ORDER BY ...)``,
under ``exp.Window``) or to an ordered aggregate (``WITHIN GROUP (ORDER BY
...)``, under ``exp.GroupConcat`` for ``STRING_AGG`` or ``exp.WithinGroup`` for
``PERCENTILE_CONT`` and friends) is meaningful — it orders rows *within* the
function, not the result set — so it is skipped, not flagged.
"""

from __future__ import annotations

from sqlglot import exp

from coop_sql_review.finding import Finding
from coop_sql_review.rules.base import Rule, RuleContext
from coop_sql_review.rules.helpers import enclosing_object


# Wrappers between an ORDER BY and its SELECT that make the ORDER BY meaningful
# (it orders rows inside the function, not the result set): window functions
# ``OVER (ORDER BY ...)`` and ordered aggregates ``WITHIN GROUP (ORDER BY ...)``
# (STRING_AGG -> GroupConcat, PERCENTILE_CONT -> WithinGroup).
_MEANINGFUL_ORDER_WRAPPERS = (exp.Window, exp.WithinGroup, exp.GroupConcat)


def _enclosing_select(node: exp.Expression) -> exp.Select | None:
    """Nearest ``SELECT`` ancestor of ``node`` (the one the ORDER BY belongs to),
    or ``None`` if a window/ordered-aggregate wrapper is hit first — in which
    case the ORDER BY is meaningful and must not be flagged."""
    current = node.parent
    while current is not None:
        if isinstance(current, _MEANINGFUL_ORDER_WRAPPERS):
            return None
        if isinstance(current, exp.Select):
            return current
        current = current.parent
    return None


def _ignored_context(select: exp.Select) -> bool:
    """True if ``select`` is a view body, a CTE, or a subquery (so its ORDER BY
    is ignored unless paired with TOP)."""
    current = select.parent
    while current is not None:
        if isinstance(current, (exp.Subquery, exp.CTE)):
            return True
        if isinstance(current, exp.Create) and current.args.get("kind") == "VIEW":
            return True
        # Stop climbing once we leave this select's own wrappers into another
        # SELECT — a further-out SELECT is a different scope.
        if isinstance(current, exp.Select):
            return False
        current = current.parent
    return False


def check(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    for batch, order in ctx.parsed.find_all(exp.Order):
        select = _enclosing_select(order)
        if select is None or select.args.get("limit") is not None:
            continue
        # OFFSET makes the ORDER BY semantics-bearing too (T-SQL honors ORDER BY
        # in a view/subquery when paired with TOP, OFFSET, or FOR XML). An
        # OFFSET ... FETCH lands in `limit`; a bare OFFSET lands in `offset`.
        if select.args.get("offset") is not None:
            continue
        if not _ignored_context(select):
            continue
        findings.append(
            ctx.finding(
                line=ctx.parsed.node_line(batch, order),
                object=enclosing_object(order),
                message=(
                    "ORDER BY in a view/CTE/subquery is ignored unless paired with TOP "
                    "— remove it or add TOP (§E)."
                ),
            )
        )
    return findings


RULE = Rule(
    id="SQL-ORDER-BY-IN-VIEW",
    title="ORDER BY in a view/CTE/subquery is ignored unless paired with TOP",
    severity="warning",
    category="correctness",
    standard_ref="§E",
    tier=2,
    check=check,
)
