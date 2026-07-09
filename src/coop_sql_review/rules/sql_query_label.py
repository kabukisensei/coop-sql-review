"""SQL-QUERY-LABEL (§9): label ETL ``INSERT ... SELECT`` with OPTION(LABEL=...).

Fabric DW surfaces the query label in monitoring/diagnostics views, so a
set-based ETL load should carry ``OPTION (LABEL = '...')`` to be traceable.
Any query-form source is in scope: a plain :class:`exp.Select`, a set operation
(``UNION``/``UNION ALL``/``EXCEPT``/``INTERSECT``, i.e. :class:`exp.SetOperation`),
and a parenthesized source (:class:`exp.Subquery`) — all subclasses of
:class:`exp.Query`. A singleton ``INSERT ... VALUES`` is not ETL and is left to
SQL-SINGLETON-INSERT.

sqlglot parses the hint into a structured ``OPTION`` clause
(``args["options"]`` -> ``exp.QueryOption`` whose ``this`` Var names the option),
so presence is read straight from the AST rather than a text scan — that never
false-matches the word LABEL inside a string literal or comment. The hint can
sit on the node itself (plain SELECT, or the parenthesized ``Subquery`` wrapper)
or, for a set operation, on the rightmost leaf SELECT
(``union.right.args["options"]``); both placements are inspected.
"""

from __future__ import annotations

from sqlglot import exp

from coop_sql_review.finding import Finding
from coop_sql_review.rules.base import FABRIC_ONLY, Rule, RuleContext
from coop_sql_review.rules.helpers import dml_target


def _options_have_label(node: exp.Expression) -> bool:
    """True if ``node`` carries an ``OPTION (LABEL = ...)`` query hint directly."""
    for option in node.args.get("options") or []:
        if (
            isinstance(option, exp.QueryOption)
            and option.this is not None
            and option.this.name.upper() == "LABEL"
        ):
            return True
    return False


def _has_label_option(source: exp.Query) -> bool:
    """True if a query-form ETL source carries an ``OPTION (LABEL = ...)`` hint.

    The hint may attach to the node itself, to the inner query of a parenthesized
    ``Subquery``, or — for a set operation — to its rightmost leaf SELECT.
    """
    if _options_have_label(source):
        return True
    if isinstance(source, exp.Subquery) and isinstance(source.this, exp.Query):
        return _has_label_option(source.this)
    if isinstance(source, exp.SetOperation) and isinstance(source.right, exp.Query):
        return _has_label_option(source.right)
    return False


def check(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    for batch, insert in ctx.parsed.find_all(exp.Insert):
        source = insert.expression
        if not isinstance(source, exp.Query):
            continue  # only set-based ETL; INSERT ... VALUES is not ETL
        if _has_label_option(source):
            continue
        findings.append(
            ctx.finding(
                line=ctx.parsed.node_line(batch, insert),
                object=dml_target(insert),
                message=(
                    "ETL INSERT...SELECT has no OPTION(LABEL=...) — add a query "
                    "label for monitoring/diagnostics (§9)."
                ),
            )
        )
    return findings


RULE = Rule(
    id="SQL-QUERY-LABEL",
    title="ETL INSERT...SELECT should carry OPTION(LABEL=...)",
    severity="info",
    category="observability",
    standard_ref="§9",
    tier=3,
    default_enabled=False,  # query labelling is a Fabric monitoring practice many skip; opt in via rules.yml
    # OPTION(LABEL=...) is a Fabric/Synapse surface — Azure SQL rejects the hint, so
    # recommending it there would be wrong advice, not just noise.
    targets=FABRIC_ONLY,
    check=check,
)
