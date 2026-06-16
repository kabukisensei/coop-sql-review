"""SQL-ALIAS-DESCRIPTIVE (§2): descriptive table aliases.

Standard §2 forbids single-letter (and other too-short) table aliases in
favor of 3–5 character descriptive abbreviations (``cust``, ``addr``,
``sales``). Any alias shorter than three characters is flagged; tables
without an alias are left alone.
"""

from __future__ import annotations

from sqlglot import exp

from coop_sql_review.rules.base import Rule, RuleContext
from coop_sql_review.rules.helpers import enclosing_object
from coop_sql_review.finding import Finding


def check(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    for batch, table in ctx.parsed.find_all(exp.Table):
        alias = table.alias  # "" when the table has no alias
        if alias and len(alias) < 3:
            findings.append(
                ctx.finding(
                    line=ctx.parsed.node_line(batch, table),
                    object=enclosing_object(table),
                    message=(
                        f"table alias '{alias}' is too short — use a 3–5 char "
                        "descriptive abbreviation, e.g. dim_customer -> cust (§2)."
                    ),
                )
            )
    return findings


RULE = Rule(
    id="SQL-ALIAS-DESCRIPTIVE",
    title="Descriptive table aliases",
    severity="warning",
    category="aliases",
    standard_ref="§2",
    tier=1,
    default_enabled=False,  # short aliases are common house style; opt in via rules.yml
    check=check,
)
