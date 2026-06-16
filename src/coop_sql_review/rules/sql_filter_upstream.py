"""SQL-FILTER-UPSTREAM (§8): a joined+filtered query may want upstream filtering.

§8 says to keep joins simple and push filtering into CTEs so joins operate on
already-filtered datasets. A ``SELECT`` that has both a ``JOIN`` and a ``WHERE``
is a candidate — but whether the filter *should* move upstream depends on row
counts and intent, which a linter can't judge. So this rule detects the
construct and hands it to the agent. We inspect each SELECT's *own* ``joins``
and ``where`` (not descendants), so ``find_all(exp.Select)`` naturally yields
one review per qualifying SELECT.
"""

from __future__ import annotations

from sqlglot import exp

from coop_sql_review.finding import AgentReviewItem
from coop_sql_review.rules.base import Rule, RuleContext
from coop_sql_review.rules.helpers import enclosing_object


def detect(ctx: RuleContext) -> list[AgentReviewItem]:
    items: list[AgentReviewItem] = []
    for batch, select in ctx.parsed.find_all(exp.Select):
        has_join = bool(select.args.get("joins"))
        has_where = select.args.get("where") is not None
        if has_join and has_where:
            items.append(
                ctx.review(
                    object=enclosing_object(select),
                    line=ctx.parsed.node_line(batch, select),
                    note=(
                        "join query with a WHERE filter — consider whether filtering "
                        "should move upstream into a CTE per §8."
                    ),
                )
            )
    return items


RULE = Rule(
    id="SQL-FILTER-UPSTREAM",
    title="Joined query with a WHERE filter may want upstream filtering",
    severity="info",
    category="joins",
    standard_ref="§8",
    tier=2,
    kind="agent",
    detect=detect,
)
