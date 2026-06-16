"""SQL-TRY-CAST-BRONZE (§D): prefer TRY_CAST when parsing raw bronze text.

Raw bronze values fail hard with ``CAST`` — one bad value aborts the whole
load. ``TRY_CAST`` yields NULL on bad input instead, so the load survives.
Conservative + info-only: a batch is flagged only when it *reads* a
``bronze.*`` table as a SOURCE (FROM/JOIN) AND contains a plain ``CAST`` whose
argument references a column (``TRY_CAST`` is exempt; ``CAST`` of a pure
literal is exempt). ``exp.TryCast`` subclasses ``exp.Cast``, so it is filtered
out explicitly. A ``bronze.*`` table that is only the DML *target*
(``INSERT``/``UPDATE``/``MERGE`` into bronze) does not count as a read.

Known limitation: the bronze-read test is per-batch, not per-cast. A plain
``CAST`` on a non-bronze (e.g. ``silver.*``) column is still flagged when the
same batch merely *joins* a bronze table, since the rule does not trace the
cast argument back to its source table.
"""

from __future__ import annotations

from sqlglot import exp

from coop_sql_review.finding import Finding
from coop_sql_review.rules.base import Rule, RuleContext
from coop_sql_review.rules.helpers import enclosing_object


def _target_tables(expression: exp.Expression) -> set[int]:
    """Object ids of ``Table`` nodes that are the DML *target* of an
    INSERT/UPDATE/MERGE (``insert.this`` / ``update.this`` / ``merge.this``),
    so they can be excluded from the bronze *read* check."""
    targets: set[int] = set()
    for dml in expression.find_all(exp.Insert, exp.Update, exp.Merge):
        target = dml.this
        if target is not None:
            for table in target.find_all(exp.Table):
                targets.add(id(table))
    return targets


def check(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    for batch in ctx.parsed.batches:
        targets = {tid for expression in batch.expressions for tid in _target_tables(expression)}
        reads_bronze = any(
            table.text("db").lower() == "bronze" and id(table) not in targets
            for expression in batch.expressions
            for table in expression.find_all(exp.Table)
        )
        if not reads_bronze:
            continue
        for expression in batch.expressions:
            for cast in expression.find_all(exp.Cast):
                if isinstance(cast, exp.TryCast):
                    continue
                if not any(isinstance(n, exp.Column) for n in cast.this.walk()):
                    # CAST of a pure literal (e.g. CAST(1 AS INT)) is harmless.
                    continue
                findings.append(
                    ctx.finding(
                        line=ctx.parsed.node_line(batch, cast),
                        object=enclosing_object(cast),
                        message=(
                            "CAST on bronze-sourced data aborts the load on bad values "
                            "— prefer TRY_CAST (§D)."
                        ),
                    )
                )
    return findings


RULE = Rule(
    id="SQL-TRY-CAST-BRONZE",
    title="Prefer TRY_CAST over CAST on bronze-sourced data",
    severity="info",
    category="bronze",
    standard_ref="§D",
    tier=3,
    check=check,
)
