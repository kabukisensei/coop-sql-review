"""SQL-DATE-FILTER-PARAM (§11): date filters should use parameters.

§11's checklist asks that date filters use parameters rather than hard-coded
date literals, so a reload only needs the parameter changed (and the engine
can reason about the predicate). This rule flags any string literal whose
*entire* value is a plausible ISO date (``'YYYY-MM-DD'`` with a valid month
01-12 and day 01-31) inside a WHERE clause; a parameter (``@process_date``)
parses as ``exp.Parameter``, not ``exp.Literal``, so it is never flagged. The
match is anchored (``re.fullmatch``) so free text that merely contains a date
(``'2026-06-04 customer called'``) and hyphenated codes that are not valid
dates (``'9999-88-77'``) are not flagged, and a non-date string such as
``'Open'`` never matches. Each literal node is reported at most once even when
it sits in a subquery WHERE that an enclosing WHERE's ``find_all`` descends
into.
"""

from __future__ import annotations

import re

from sqlglot import exp

from coop_sql_review.finding import Finding
from coop_sql_review.rules.base import Rule, RuleContext
from coop_sql_review.rules.helpers import enclosing_object

# Anchored, value-validated ISO date: year, month 01-12, day 01-31.
_DATE_LITERAL = re.compile(r"\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])")


def check(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    seen: set[int] = set()
    for batch, where in ctx.parsed.find_all(exp.Where):
        for lit in where.find_all(exp.Literal):
            if id(lit) in seen:
                continue
            if lit.is_string and _DATE_LITERAL.fullmatch(lit.this):
                seen.add(id(lit))
                findings.append(
                    ctx.finding(
                        line=ctx.parsed.node_line(batch, lit),
                        object=enclosing_object(where),
                        message=(
                            "hard-coded date literal in WHERE — prefer a parameter "
                            "(e.g. @process_date) (§11)."
                        ),
                    )
                )
    return findings


RULE = Rule(
    id="SQL-DATE-FILTER-PARAM",
    title="Date filters should use parameters, not hard-coded literals",
    severity="info",
    category="filters",
    standard_ref="§11",
    tier=3,
    check=check,
)
