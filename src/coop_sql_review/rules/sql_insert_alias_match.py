"""SQL-INSERT-ALIAS-MATCH (§3): SELECT items feeding an INSERT must be aliased
to match the INSERT target column.

Per §3, every column in a SELECT that feeds an ``INSERT INTO t (cols) SELECT ...``
must carry an ``AS`` alias whose name matches the corresponding target column,
so column alignment is checkable at a glance. The rule only applies when the
INSERT has an explicit column list (a Schema-wrapped target) and the source is
a plain SELECT — VALUES and set-operation (UNION) sources can't be aligned this
way and are skipped.
"""

from __future__ import annotations

from sqlglot import exp

from coop_sql_review.finding import Finding
from coop_sql_review.identifiers import normalize_identifier
from coop_sql_review.rules.base import Rule, RuleContext
from coop_sql_review.rules.helpers import dml_target


def check(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    for batch, insert in ctx.parsed.find_all(exp.Insert):
        target = insert.this
        if not isinstance(target, exp.Schema):
            continue  # no explicit column list — alignment can't be checked
        cols = [c.name for c in target.expressions]
        src = insert.expression
        if not isinstance(src, exp.Select):
            continue  # skip VALUES / UNION sources
        projs = src.expressions
        for i, col in enumerate(cols):
            if i >= len(projs):
                break
            p = projs[i]
            ok = isinstance(p, exp.Alias) and normalize_identifier(p.alias_or_name) == normalize_identifier(
                col
            )
            if not ok:
                findings.append(
                    ctx.finding(
                        line=ctx.parsed.node_line(batch, p),
                        object=dml_target(insert),
                        message=f"INSERT column '{col}': SELECT item should be aliased AS {col} (§3).",
                    )
                )
    return findings


RULE = Rule(
    id="SQL-INSERT-ALIAS-MATCH",
    title="SELECT alias matches INSERT target column",
    severity="warning",
    category="inserts",
    standard_ref="§3",
    tier=2,
    check=check,
)
