"""SQL-EXISTS-COMMENT (§7): EXISTS / NOT EXISTS must explain the reasoning.

§7 requires a comment block above any ``EXISTS``/``NOT EXISTS`` saying what is
being checked and why ``EXISTS`` beats the alternative (``COUNT(*)``,
``LEFT JOIN + IS NULL``, ``IN``). We locate each predicate via
``helpers.exists_sites``, which anchors the line on the ``EXISTS`` keyword
itself (an AST ``node_line`` would wrongly land inside the subquery body, both
flagging the standard's own canonical 'Good' examples and missing the comment
above). ``IF EXISTS`` / ``WHILE EXISTS`` existence guards are skipped — §7's
"explain why over COUNT/JOIN/IN" guidance does not apply to them. We accept a
comment ending within a few lines above the keyword (blank lines tolerated) via
``preceding_comment``.
"""

from __future__ import annotations

from coop_sql_review.finding import Finding
from coop_sql_review.rules.base import Rule, RuleContext
from coop_sql_review.rules.helpers import exists_sites, preceding_comment


def check(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    for line, is_guard in exists_sites(ctx.parsed):
        if is_guard:
            continue
        if not preceding_comment(ctx.parsed, line, within=3):
            findings.append(
                ctx.finding(
                    line=line,
                    object="",
                    message=(
                        "EXISTS/NOT EXISTS without an explaining comment — add a comment "
                        "above saying why EXISTS over the alternative (COUNT/JOIN/IN) (§7)."
                    ),
                )
            )
    return findings


RULE = Rule(
    id="SQL-EXISTS-COMMENT",
    title="EXISTS / NOT EXISTS needs a reasoning comment",
    severity="warning",
    category="comments",
    standard_ref="§7",
    tier=2,
    check=check,
)
