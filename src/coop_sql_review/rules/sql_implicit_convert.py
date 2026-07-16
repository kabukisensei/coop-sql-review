"""SQL-IMPLICIT-CONVERT (§C): avoid implicit conversions in predicates.

Comparing mismatched types forces a runtime conversion. Which side gets
converted follows SQL Server data-type precedence, and the two directions are
NOT equally harmful, so each gets its own message:

- **string column vs numeric literal** (``code = 5``): numeric outranks
  string, so the COLUMN is converted per row — index seeks are lost. Message:
  hurts SARGability.
- **numeric column vs string literal** (``qty = '5'``): the LITERAL is
  converted once and the predicate stays fully SARGable. Message: harmless to
  SARGability; match the literal type for clarity.

This is only checkable when the column's type is *known* from a ``CREATE
TABLE`` in the same file. Conservative + info-only: a comparison (``=``,
``<>``, ``<``, ``<=``, ``>``, ``>=``) is flagged solely when the bare column's
type is known AND clearly mismatched against the literal kind AND it sits in a
*predicate* context — a ``WHERE`` or ``HAVING`` clause, or a JOIN / MERGE
``ON`` clause. Non-predicate comparisons — ``UPDATE ... SET col = lit``
assignments (including a MERGE's ``WHEN MATCHED ... SET``) and SELECT-list
boolean expressions like ``SELECT (col = lit)`` — are excluded.

Known limitation: column types are matched by *bare name* across the whole
file, so a column name reused with different types in different tables can be
mis-bound (such names are dropped only when their CREATE TABLE types conflict).
"""

from __future__ import annotations

from sqlglot import exp

from coop_sql_review.finding import Finding
from coop_sql_review.rules.base import Rule, RuleContext
from coop_sql_review.rules.helpers import enclosing_object

_STRING_TYPES = {"VARCHAR", "CHAR", "NVARCHAR", "NCHAR", "TEXT"}
_NUMERIC_TYPES = {
    "INT",
    "BIGINT",
    "DECIMAL",
    "NUMERIC",
    "MONEY",
    "FLOAT",
    "REAL",
    "SMALLINT",
    "TINYINT",
}

_COMPARISONS = (exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE)


def _column_types(ctx: RuleContext) -> dict[str, str]:
    """Map ``column-name(lower) -> base_type`` for every CREATE TABLE column
    in the file. A name defined with conflicting types across tables is dropped
    to avoid a wrong guess."""
    types: dict[str, str] = {}
    conflicts: set[str] = set()
    for obj in ctx.parsed.objects:
        for column in obj.columns:
            key = column.name.lower()
            if key in types and types[key] != column.base_type:
                conflicts.add(key)
            else:
                types[key] = column.base_type
                
    for table_dict in ctx.catalog.tables.values():
        for norm_col, col_def in table_dict.items():
            if col_def.base_type == "CONFLICT":
                conflicts.add(norm_col)
            elif norm_col in types and types[norm_col] != col_def.base_type:
                conflicts.add(norm_col)
            elif norm_col not in types:
                types[norm_col] = col_def.base_type
                
    for key in conflicts:
        types.pop(key, None)
    return types


def _is_predicate(comp: exp.Binary) -> bool:
    """True when the comparison is a comparison predicate — inside a WHERE or
    HAVING clause, or a JOIN / MERGE ON clause — rather than an UPDATE SET
    assignment (including a MERGE WHEN-MATCHED SET) or a SELECT-list boolean
    expression."""
    if comp.find_ancestor(exp.Where, exp.Having) is not None:
        return True
    # A JOIN's or a MERGE's ON match predicate carries the comparison in its
    # ``on`` arg; the MERGE's WHEN-MATCHED SET assignments must stay excluded,
    # so match only comparisons that actually live under that ``on`` subtree.
    for owner in (comp.find_ancestor(exp.Join), comp.find_ancestor(exp.Merge)):
        if owner is not None:
            on = owner.args.get("on")
            if on is not None and any(node is comp for node in on.walk()):
                return True
    return False


def check(ctx: RuleContext) -> list[Finding]:
    types = _column_types(ctx)
    if not types:
        return []

    findings: list[Finding] = []
    for batch, comp in ctx.parsed.find_all(*_COMPARISONS):
        if not _is_predicate(comp):
            continue

        # Identify the (column, literal) sides in either order.
        left, right = comp.this, comp.expression
        if isinstance(left, exp.Column) and isinstance(right, exp.Literal):
            column, literal = left, right
        elif isinstance(right, exp.Column) and isinstance(left, exp.Literal):
            column, literal = right, left
        else:
            continue

        base_type = types.get(column.name.lower())
        if base_type is None:
            continue

        # Data-type precedence decides which side is converted: numeric outranks
        # string, so a string COLUMN vs a numeric literal converts the column
        # (per row — seeks lost), while a numeric column vs a string LITERAL
        # converts the literal once (harmless to SARGability).
        column_converted = base_type in _STRING_TYPES and literal.is_number
        literal_converted = base_type in _NUMERIC_TYPES and literal.is_string
        if not (column_converted or literal_converted):
            continue

        if column_converted:
            message = (
                f"column {column.name} ({base_type}) compared to a mismatched literal "
                "— implicit conversion hurts SARGability (§C)."
            )
        else:
            message = (
                f"column {column.name} ({base_type}) compared to a string literal — "
                "implicit conversion of the literal is harmless to SARGability; "
                "match the literal type for clarity (§C)."
            )
        findings.append(
            ctx.finding(
                line=ctx.parsed.node_line(batch, comp),
                object=enclosing_object(comp),
                message=message,
            )
        )
    return findings


RULE = Rule(
    id="SQL-IMPLICIT-CONVERT",
    title="Avoid implicit conversions in predicates",
    severity="info",
    category="performance",
    standard_ref="§C",
    tier=3,
    check=check,
)
