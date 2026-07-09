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

**JOIN ON sites** (issue #15): SQL-JOIN-FILTER (§8) documents ``COALESCE`` /
``CAST``/``CONVERT``/``COLLATE`` around join keys as idiomatic *key alignment*
(``helpers.is_alignment_subtree`` — the shared tolerance; keep the two rules in
lockstep). So by default a join predicate whose only "wrapping" is such an
alignment subtree is NOT flagged here — one tool must not bless a pattern in
one rule and demand its rewrite in another. Teams that want the strict
statistics story back can set ``params: {flag_alignment_joins: true}``. A join
hit that survives (a real function, or the params opt-in) gets a
join-oriented message — the WHERE message's "filter the bare column with a
range" rewrite makes no sense for a join key.
"""

from __future__ import annotations

from sqlglot import exp

from coop_sql_review.finding import Finding
from coop_sql_review.rules.base import Rule, RuleContext
from coop_sql_review.rules.helpers import enclosing_object, is_alignment_subtree

_COMPARISONS = (exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE)
# The §A "col + x" arithmetic connectives; a column wrapped in one of these on
# the column side of a predicate is computed per row, defeating index/statistics.
_ARITHMETIC = (exp.Add, exp.Sub, exp.Mul, exp.Div)

_WHERE_MESSAGE = (
    "non-SARGable predicate: a function or arithmetic on a column "
    "(e.g. YEAR(col), col + 1) defeats index/statistics — filter the "
    "bare column with a range instead (§A)."
)
_JOIN_MESSAGE = (
    "non-SARGable join predicate: a function or arithmetic on a join key "
    "defeats statistics — align the key types/values upstream (e.g. in a CTE) "
    "and join on bare keys (§A)."
)


def _function_on_column(node: exp.Expression) -> bool:
    """True if ``node`` is a column-wrapping function call.

    ``exp.Case`` is an ``exp.Func`` subclass but is not a function applied to a
    column (``CASE WHEN ... END = 5`` is SARGable on its inputs), so it is
    excluded.
    """
    if isinstance(node, exp.Case) or not isinstance(node, exp.Func):
        return False
    return any(True for _ in node.find_all(exp.Column))


def _wraps_column(node: exp.Expression, *, arithmetic: bool, align_ok: bool = False) -> bool:
    """True if ``node`` is a function — or, when ``arithmetic`` is allowed, an
    arithmetic expression — wrapping a column. Arithmetic is only meaningful on
    the *column* side of a predicate; the caller decides where that is. With
    ``align_ok`` a pure key-alignment subtree (see module docstring) counts as
    bare-key material, not a wrapping."""
    if align_ok and is_alignment_subtree(node):
        return False
    if _function_on_column(node):
        return True
    if arithmetic and isinstance(node, _ARITHMETIC):
        return any(True for _ in node.find_all(exp.Column))
    return False


def _hits(predicate: exp.Expression, *, align_ok: bool = False) -> bool:
    """True if the single comparison/membership node wraps a column."""
    if isinstance(predicate, (exp.In, exp.Between)):
        # Only the subject (`this`) side matters: `col IN (SELECT ...)` and
        # `col BETWEEN a AND b` keep the column bare and stay SARGable.
        return _wraps_column(predicate.this, arithmetic=True, align_ok=align_ok)
    # Functions poison either side; arithmetic only counts on the LEFT
    # (column) side — `x > qty + 1` keeps the filtered column bare.
    return _wraps_column(predicate.left, arithmetic=True, align_ok=align_ok) or _wraps_column(
        predicate.right, arithmetic=False, align_ok=align_ok
    )


def _scan(predicate: exp.Expression) -> list[exp.Expression]:
    """Predicates under ``predicate`` that wrap a column in a function/arithmetic."""
    hits: list[exp.Expression] = []
    for comparison in predicate.find_all(*_COMPARISONS):
        if _hits(comparison):
            hits.append(comparison)
    for membership in predicate.find_all(exp.In, exp.Between):
        if _hits(membership):
            hits.append(membership)
    return hits


def _join_site(node: exp.Expression) -> bool:
    """True when ``node``'s predicate site is a ``JOIN ... ON`` clause.

    Walks up to the nearest enclosing Join or Where — whichever comes first
    classifies the site, so a WHERE inside a subquery in an ON clause stays a
    WHERE site (and vice versa), regardless of which outer scan found it.
    """
    current = node.parent
    while current is not None:
        if isinstance(current, exp.Join):
            return True
        if isinstance(current, exp.Where):
            return False
        current = current.parent
    return False


def check(ctx: RuleContext) -> list[Finding]:
    flag_alignment_joins = ctx.param("flag_alignment_joins", False)
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
            join_site = _join_site(comparison)
            if join_site and not flag_alignment_joins and not _hits(comparison, align_ok=True):
                # Pure key-alignment wrappers on a join key — the shape
                # SQL-JOIN-FILTER documents as idiomatic (issue #15).
                continue
            findings.append(
                ctx.finding(
                    line=ctx.parsed.node_line(batch, comparison),
                    object=enclosing_object(comparison),
                    message=_JOIN_MESSAGE if join_site else _WHERE_MESSAGE,
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
