"""SQL-BRONZE-RAW-NAMES (§1): renaming bronze source columns needs a check.

§1 says bronze must preserve raw source column names exactly; renaming to
PascalCase belongs in silver/gold. So a ``SELECT`` that reads a ``bronze.*``
table *and* renames a raw column (an ``exp.Alias`` over a *bare* ``exp.Column``,
e.g. ``contactid AS CustomerId``) may be renaming raw names too early — but
whether that is wrong depends on intent (it could be a legitimate silver
transform sourcing bronze), which a linter can't decide. This rule detects the
construct and hands it to the agent.

Only a column rename counts: an alias over a computed expression
(``COUNT(*) AS row_count``, ``GETDATE() AS LoadedAt``) is not a raw-name
rename, so ``alias.this`` must be an ``exp.Column`` — otherwise we'd flag every
aggregate or audit-column SELECT over bronze.

To stay precise, "reads a bronze table" means the bronze ``exp.Table`` is a
*direct* source of the SELECT (its FROM / JOIN), not one buried in a nested
CTE or derived table — that keeps a silver SELECT over a bronze-sourced CTE
from being flagged at the wrong layer.
"""

from __future__ import annotations

from sqlglot import exp

from coop_sql_review.finding import AgentReviewItem
from coop_sql_review.rules.base import Rule, RuleContext
from coop_sql_review.rules.helpers import enclosing_object


def _reads_bronze_directly(select: exp.Select) -> bool:
    """True if a ``bronze.*`` table is a direct FROM/JOIN source of ``select``
    (excluding tables inside a nested subquery/derived table)."""
    parts: list[exp.Expression] = []
    from_clause = select.args.get("from") or select.args.get("from_")
    if from_clause is not None:
        parts.append(from_clause)
    parts.extend(select.args.get("joins") or [])
    for part in parts:
        for table in part.find_all(exp.Table):
            if (table.db or "").lower() != "bronze":
                continue
            # Skip tables that live inside a nested subquery / derived select.
            ancestor = table.parent
            nested = False
            while ancestor is not None and ancestor is not part.parent:
                if isinstance(ancestor, (exp.Subquery, exp.Select)) and ancestor is not select:
                    nested = True
                    break
                ancestor = ancestor.parent
            if not nested:
                return True
    return False


def detect(ctx: RuleContext) -> list[AgentReviewItem]:
    items: list[AgentReviewItem] = []
    for batch, select in ctx.parsed.find_all(exp.Select):
        renames_column = any(
            isinstance(proj, exp.Alias) and isinstance(proj.this, exp.Column) for proj in select.expressions
        )
        if renames_column and _reads_bronze_directly(select):
            items.append(
                ctx.review(
                    object=enclosing_object(select),
                    line=ctx.parsed.node_line(batch, select),
                    note=(
                        "bronze source columns are being renamed — confirm raw source "
                        "names are preserved in bronze per §1."
                    ),
                )
            )
    return items


RULE = Rule(
    id="SQL-BRONZE-RAW-NAMES",
    title="Bronze source columns are being renamed",
    severity="info",
    category="naming",
    standard_ref="§1",
    tier=2,
    kind="agent",
    detect=detect,
)
