"""SQL-EXISTS-WHY-QUALITY (§7): an EXISTS comment needs a quality judgment.

§7 wants a comment above ``EXISTS`` / ``NOT EXISTS`` that explains *why*
``EXISTS`` beats the alternatives (``COUNT(*)``, ``LEFT JOIN + IS NULL``,
``IN``). SQL-EXISTS-COMMENT (deterministic) handles the *missing* comment.
This rule covers the other half: when a comment *is* present, only the agent
can judge whether it actually explains the reasoning rather than just
restating the code — so it detects the commented case and hands it over.

We anchor on ``helpers.exists_sites`` (the ``EXISTS`` keyword line), exactly
like the now-fixed SQL-EXISTS-COMMENT, instead of an AST ``node_line`` that
would land inside the subquery body and miss the comment above. ``IF EXISTS`` /
``WHILE EXISTS`` existence guards are skipped — §7's "explain why over
COUNT/JOIN/IN" guidance does not apply to them.
"""

from __future__ import annotations

from coop_sql_review.finding import AgentReviewItem
from coop_sql_review.rules.base import Rule, RuleContext
from coop_sql_review.rules.helpers import exists_sites, preceding_comment


def detect(ctx: RuleContext) -> list[AgentReviewItem]:
    items: list[AgentReviewItem] = []
    for line, is_guard in exists_sites(ctx.parsed):
        if is_guard:
            continue
        if preceding_comment(ctx.parsed, line, within=3):
            items.append(
                ctx.review(
                    object="",
                    line=line,
                    note=(
                        "EXISTS has a comment — judge whether it explains WHY EXISTS "
                        "beats the alternatives per §7."
                    ),
                )
            )
    return items


RULE = Rule(
    id="SQL-EXISTS-WHY-QUALITY",
    title="EXISTS comment quality needs a judgment",
    severity="info",
    category="comments",
    standard_ref="§7",
    tier=2,
    kind="agent",
    detect=detect,
)
