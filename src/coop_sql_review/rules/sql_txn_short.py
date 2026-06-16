"""SQL-TXN-SHORT (§9): an explicit transaction needs a "keep it short" review.

§9: Fabric DW is snapshot-isolation only, so a long-running explicit
transaction widens the conflict window. Whether a given transaction is "short
enough" is a judgment about the work inside it, so this rule only detects the
``BEGIN TRAN`` / ``BEGIN TRANSACTION`` opener and hands it to the agent.

sqlglot parses ``BEGIN TRANSACTION`` as ``exp.Transaction`` but can fall back
to a generic ``Command`` for some surrounding syntax (e.g. ``BEGIN TRY``), so
a regex over ``ctx.parsed.masked`` (comments/strings blanked, offsets intact)
is the reliable signal; the file line comes from ``line_of_offset``.
"""

from __future__ import annotations

import re

from coop_sql_review.finding import AgentReviewItem
from coop_sql_review.rules.base import Rule, RuleContext

_BEGIN_TRAN = re.compile(r"\bBEGIN\s+TRAN(SACTION)?\b", re.IGNORECASE)


def detect(ctx: RuleContext) -> list[AgentReviewItem]:
    items: list[AgentReviewItem] = []
    for match in _BEGIN_TRAN.finditer(ctx.parsed.masked):
        items.append(
            ctx.review(
                object="",
                line=ctx.parsed.line_of_offset(match.start()),
                note=(
                    "explicit transaction — verify it stays short; Fabric DW is "
                    "snapshot-isolation only and long transactions widen the conflict "
                    "window (§9)."
                ),
            )
        )
    return items


RULE = Rule(
    id="SQL-TXN-SHORT",
    title="Explicit transaction should stay short",
    severity="info",
    category="transactions",
    standard_ref="§9",
    tier=2,
    kind="agent",
    detect=detect,
)
