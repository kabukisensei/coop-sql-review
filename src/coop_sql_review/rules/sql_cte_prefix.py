"""SQL-CTE-PREFIX (§1): CTEs follow the ``cte_descriptive_name`` pattern.

Common Table Expressions read better in pipelines when their names announce
their role, so the naming standard asks for a ``cte_`` prefix. Each CTE whose
(normalized) name doesn't start with ``cte_`` is flagged; well-prefixed CTEs
in the same ``WITH`` clause are left alone.
"""

from __future__ import annotations

from sqlglot import exp

from coop_sql_review.rules.base import Rule, RuleContext
from coop_sql_review.rules.helpers import enclosing_object
from coop_sql_review.identifiers import normalize_identifier
from coop_sql_review.finding import Finding


def check(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    for batch, cte in ctx.parsed.find_all(exp.CTE):
        name = cte.alias_or_name
        if not name:
            continue  # error-tolerant parses can fabricate an unnamed CTE
        if not normalize_identifier(name).startswith("cte_"):
            findings.append(
                ctx.finding(
                    line=ctx.parsed.node_line(batch, cte),
                    object=enclosing_object(cte),
                    message=f"CTE '{name}' should be prefixed 'cte_' (§1).",
                )
            )
    return findings


RULE = Rule(
    id="SQL-CTE-PREFIX",
    title="CTEs use the cte_ prefix",
    severity="info",
    category="naming",
    standard_ref="§1",
    tier=1,
    check=check,
)
