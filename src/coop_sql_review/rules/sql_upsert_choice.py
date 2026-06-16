"""SQL-UPSERT-CHOICE (§5): a MERGE upsert needs a size/concurrency judgment.

The right upsert pattern (CTAS / DELETE+INSERT / MERGE) depends on table size,
concurrency, and intent — which a linter can't decide. So this rule only
*detects* the construct: it flags every MERGE for the agent to judge against
§5 (Fabric DW prefers DELETE+INSERT or CTAS for large tables; MERGE suits
small dimensions). It is an agent-judgment rule — emitted to ``agent_review``,
never auto-evaluated.
"""

from __future__ import annotations

from sqlglot import exp

from coop_sql_review.finding import AgentReviewItem
from coop_sql_review.rules.base import Rule, RuleContext
from coop_sql_review.rules.helpers import dml_target


def detect(ctx: RuleContext) -> list[AgentReviewItem]:
    items: list[AgentReviewItem] = []
    for batch, merge in ctx.parsed.find_all(exp.Merge):
        items.append(
            ctx.review(
                object=dml_target(merge),
                line=ctx.parsed.node_line(batch, merge),
                note=(
                    "MERGE detected — confirm it is appropriate per §5. Fabric DW prefers "
                    "DELETE+INSERT or CTAS for large tables; reserve MERGE for small dimensions."
                ),
            )
        )
    return items


RULE = Rule(
    id="SQL-UPSERT-CHOICE",
    title="MERGE upsert needs a size/concurrency judgment",
    severity="info",
    category="upsert",
    standard_ref="§5",
    tier=2,
    kind="agent",
    detect=detect,
)
