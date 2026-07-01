"""SQL-JOIN-FILTER (§8): keep JOIN conditions to simple key equality.

Per §8, join conditions should be simple key equality (``ON a.id = b.id``,
optionally several AND-ed together). Business logic — literals, business
function calls, CASE expressions, ``OR``, ``IS [NOT] NULL``, or non-equality
comparisons — belongs in a CTE or earlier in the procedure, not in the ON
clause, and is flagged.

The heuristic intentionally tolerates idiomatic *key-alignment wrappers*:
``COALESCE``/``ISNULL``, ``CAST``/``CONVERT`` and ``COLLATE`` are common ways
to make two keys comparable (e.g. ``ON COALESCE(a.id, 0) = COALESCE(b.id, 0)``
or ``ON a.name = b.name COLLATE X``). When such a wrapper contains only
columns, literals, type/collation tokens, or other alignment wrappers it is
treated as part of the key — it neither counts as a business function nor lets
its wrapped literal trip the literal check. A wrapper that contains a genuine
business function (``CAST(YEAR(a.d) AS INT)``) is *not* benign and still flags.
"""

from __future__ import annotations

from sqlglot import exp

from coop_sql_review.finding import Finding
from coop_sql_review.rules.base import Rule, RuleContext
from coop_sql_review.rules.helpers import enclosing_object

# Non-equality comparisons that signal a filter rather than a key join.
_FILTER_COMPARISONS = (exp.GT, exp.GTE, exp.LT, exp.LTE, exp.NEQ, exp.Like, exp.In, exp.Between)

# Idiomatic wrappers used to align keys; not business logic on their own.
# (``ISNULL`` parses to ``exp.Coalesce`` under the tsql dialect.)
_ALIGNMENT_WRAPPERS = (exp.Coalesce, exp.Cast, exp.Convert, exp.Collate)

# Node types allowed inside an alignment wrapper for it to count as part of the
# key: bare columns/identifiers, literals, type/collation tokens, NULL, and
# nested alignment wrappers (handled separately in ``_is_alignment_subtree``).
# ``exp.DataTypeParam`` is the size/precision of a sized type (``VARCHAR(10)``,
# ``DECIMAL(19, 4)``) — it can only hold literals/vars, so it cannot smuggle a
# business function past the tolerance.
_ALIGNMENT_LEAVES = (
    exp.Column,
    exp.Identifier,
    exp.Literal,
    exp.DataType,
    exp.DataTypeParam,
    exp.Var,
    exp.Null,
)


def _is_alignment_subtree(node: exp.Expression) -> bool:
    """True if ``node`` is an alignment wrapper containing only key material.

    Such a subtree (e.g. ``COALESCE(a.id, 0)`` or ``CAST(a.id AS INT)``) is
    considered part of the join key, so the walk in :func:`_has_filter` prunes
    it. A wrapper enclosing anything else (notably a real function call) is not
    benign and is left for the normal checks to flag.
    """
    if not isinstance(node, _ALIGNMENT_WRAPPERS):
        return False
    for child in node.walk():
        if child is node:
            continue
        if isinstance(child, _ALIGNMENT_WRAPPERS) or isinstance(child, _ALIGNMENT_LEAVES):
            continue
        return False
    return True


def _has_filter(on: exp.Expression) -> bool:
    """True if the ON tree contains business logic rather than pure key equality.

    A clean ON is only ``exp.EQ`` of columns AND-ed together. We flag literals,
    CASE, ``OR`` (:class:`exp.Or`), ``IS [NOT] NULL`` (:class:`exp.Is`), real
    business function calls, and non-equality comparisons. ``AND``/``OR``
    (``exp.Connector``) are ``exp.Func`` subclasses, so they are excluded from
    the function check (``OR`` is handled explicitly via :class:`exp.Or`).
    Idiomatic alignment wrappers (see module docstring) are pruned so they
    neither count as functions nor expose their wrapped literals.
    """
    for node in on.walk(prune=_is_alignment_subtree):
        if _is_alignment_subtree(node):
            continue
        if isinstance(node, (exp.Literal, exp.Case, exp.Anonymous, exp.Or, exp.Is)):
            return True
        if isinstance(node, exp.Func) and not isinstance(node, exp.Connector):
            return True
        if isinstance(node, _FILTER_COMPARISONS):
            return True
    return False


def check(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    for batch, join in ctx.parsed.find_all(exp.Join):
        on = join.args.get("on")
        if on is None:
            continue
        if _has_filter(on):
            findings.append(
                ctx.finding(
                    line=ctx.parsed.node_line(batch, join),
                    object=enclosing_object(join),
                    message=(
                        "JOIN ON contains a filter/expression — keep joins to key "
                        "equality and push filters into a CTE (§8)."
                    ),
                )
            )
    return findings


RULE = Rule(
    id="SQL-JOIN-FILTER",
    title="Keep JOIN conditions to simple key equality",
    severity="warning",
    category="joins",
    standard_ref="§8",
    tier=2,
    check=check,
)
