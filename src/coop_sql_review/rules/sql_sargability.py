"""SQL-SARGABILITY (§A): avoid functions/arithmetic on filtered/joined columns.

§A (proposed additions): wrapping a filtered or joined column in a function
(``YEAR(SalesDate) = 2026``) or arithmetic (``qty + 1 > 100`` — §A names
``col + x`` verbatim) defeats predicate pushdown and statistics, forcing a
scan. This rule inspects every ``WHERE`` predicate and every ``JOIN`` ON
predicate, and flags:

- a comparison (``= <> > >= < <=``) where either side is a function call
  (``exp.Func`` — which includes ``exp.Anonymous`` — applied to a column), or
  whose *left* (column) side is arithmetic over a column (``col + 1 > @x``);
  arithmetic on the VALUE side (``x > qty + 1``) leaves the filtered column
  bare and is never flagged;
- an ``IN`` membership or ``BETWEEN`` range whose subject (``this``) side is a
  function or arithmetic wrapping a column (``YEAR(d) IN (2024, 2025)``,
  ``YEAR(d) BETWEEN 2024 AND 2025``) — a bare column there stays SARGable and
  is never flagged.

A bare column compared to a range (``SalesDate >= '2026-01-01'``) is SARGable
and is never flagged, nor is a function that takes no column argument (e.g.
``DATEPART(year, 2026)``). A ``CASE`` expression (``exp.Case``, also an
``exp.Func`` subclass) is not a column-wrapping function and is excluded. A
predicate reached twice — once via the outer ``WHERE`` whose ``find_all``
recurses into an ``EXISTS``/``IN`` subquery, and again via that subquery's own
``WHERE`` — is reported only once (de-duplicated by node identity).
"""

from __future__ import annotations

from sqlglot import exp

from coop_sql_review.finding import Finding
from coop_sql_review.rules.base import Rule, RuleContext
from coop_sql_review.rules.helpers import enclosing_object

_COMPARISONS = (exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE)
# The §A "col + x" arithmetic connectives; a column wrapped in one of these on
# the column side of a predicate is computed per row, defeating index/statistics.
_ARITHMETIC = (exp.Add, exp.Sub, exp.Mul, exp.Div)


def _function_on_column(node: exp.Expression) -> bool:
    """True if ``node`` is a column-wrapping function call.

    ``exp.Case`` is an ``exp.Func`` subclass but is not a function applied to a
    column (``CASE WHEN ... END = 5`` is SARGable on its inputs), so it is
    excluded.
    """
    if isinstance(node, exp.Case) or not isinstance(node, exp.Func):
        return False
    return any(True for _ in node.find_all(exp.Column))


def _wraps_column(node: exp.Expression, *, arithmetic: bool) -> bool:
    """True if ``node`` is a function — or, when ``arithmetic`` is allowed, an
    arithmetic expression — wrapping a column. Arithmetic is only meaningful on
    the *column* side of a predicate; the caller decides where that is."""
    if _function_on_column(node):
        return True
    if arithmetic and isinstance(node, _ARITHMETIC):
        return any(True for _ in node.find_all(exp.Column))
    return False


def _scan(predicate: exp.Expression) -> list[exp.Expression]:
    """Predicates under ``predicate`` that wrap a column in a function/arithmetic."""
    hits: list[exp.Expression] = []
    for comparison in predicate.find_all(*_COMPARISONS):
        # Functions poison either side; arithmetic only counts on the LEFT
        # (column) side — `x > qty + 1` keeps the filtered column bare.
        if _wraps_column(comparison.left, arithmetic=True) or _wraps_column(
            comparison.right, arithmetic=False
        ):
            hits.append(comparison)
    for membership in predicate.find_all(exp.In, exp.Between):
        # Only the subject (`this`) side matters: `col IN (SELECT ...)` and
        # `col BETWEEN a AND b` keep the column bare and stay SARGable.
        if _wraps_column(membership.this, arithmetic=True):
            hits.append(membership)
    return hits


def check(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    predicates: list[tuple] = []
    for batch, where in ctx.parsed.find_all(exp.Where):
        predicates.append((batch, where))
    for batch, join in ctx.parsed.find_all(exp.Join):
        on = join.args.get("on")
        if on is not None:
            predicates.append((batch, on))

    seen: set[int] = set()
    for batch, predicate in predicates:
        for comparison in _scan(predicate):
            # An outer WHERE's find_all recurses into EXISTS/IN subquery WHEREs,
            # so the same comparison node can surface twice — report it once.
            if id(comparison) in seen:
                continue
            seen.add(id(comparison))
            findings.append(
                ctx.finding(
                    line=ctx.parsed.node_line(batch, comparison),
                    object=enclosing_object(comparison),
                    message=(
                        "non-SARGable predicate: a function or arithmetic on a column "
                        "(e.g. YEAR(col), col + 1) defeats index/statistics — filter the "
                        "bare column with a range instead (§A)."
                    ),
                )
            )
    return findings


RULE = Rule(
    id="SQL-SARGABILITY",
    title="Avoid functions on filtered/joined columns (non-SARGable)",
    severity="warning",
    category="performance",
    standard_ref="§A",
    tier=2,
    check=check,
)
