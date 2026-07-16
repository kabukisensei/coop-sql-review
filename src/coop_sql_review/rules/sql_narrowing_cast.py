"""SQL-NARROWING-CAST (§I proposed): no silent-truncation casts.

A ``CAST``/``TRY_CAST``/``CONVERT`` of a string (or binary) column to a SHORTER
sized type silently truncates in T-SQL — ``CAST('abcdef' AS varchar(3))`` yields
``'abc'`` with no error, and ``TRY_CAST`` behaves identically (truncation isn't a
conversion failure). In an ETL projection that silently corrupts data. This rule
uses the SIZES declared by in-file ``CREATE TABLE`` columns (same bare-name binding
as SQL-IMPLICIT-CONVERT — a name declared with conflicting types across tables is
dropped) and flags a cast whose declared source size is greater than the target's.

Applies to both Fabric DW and Azure SQL (silent truncation is a data-loss bug on
either), so it is not target-gated. Relax the ``varchar(max) -> sized`` case from
rules.yml with ``params: {allow_max_to_sized: true}`` for estates that deliberately
size-cap MAX columns.
"""

from __future__ import annotations

import re

from sqlglot import exp

from coop_sql_review.rules.base import Rule, RuleContext
from coop_sql_review.rules.helpers import enclosing_object
from coop_sql_review.finding import Finding

_INF = float("inf")
_STRING_TYPES = {"CHAR", "NCHAR", "VARCHAR", "NVARCHAR"}
_BINARY_TYPES = {"BINARY", "VARBINARY"}


def _family(type_name: str) -> str | None:
    if type_name in _STRING_TYPES:
        return "string"
    if type_name in _BINARY_TYPES:
        return "binary"
    return None


def _column_sizes(ctx: RuleContext) -> dict[str, tuple[str, float]]:
    """``column-name(lower) -> (family, size)`` for in-file CREATE TABLE columns that
    are sized string/binary types (``MAX`` -> inf). Unsized/other types are omitted; a
    name declared with conflicting (family, size) across tables is dropped."""
    sizes: dict[str, tuple[str, float]] = {}
    conflicts: set[str] = set()
    for obj in ctx.parsed.objects:
        for col in obj.columns:
            family = _family(col.base_type)
            if family is None:
                continue
            m = re.search(r"\(\s*(MAX|\d+)", col.data_type, re.IGNORECASE)
            if not m:
                continue  # plain VARCHAR with no size — length unknown, skip
            tok = m.group(1).upper()
            info = (family, _INF if tok == "MAX" else float(int(tok)))
            key = col.name.lower()
            if key in sizes and sizes[key] != info:
                conflicts.add(key)
            else:
                sizes[key] = info
                
    for table_dict in ctx.catalog.tables.values():
        for norm_col, col in table_dict.items():
            family = _family(col.base_type)
            if family is None:
                continue
            m = re.search(r"\(\s*(MAX|\d+)", col.data_type, re.IGNORECASE)
            if not m:
                continue
            tok = m.group(1).upper()
            info = (family, _INF if tok == "MAX" else float(int(tok)))
            
            if col.base_type == "CONFLICT":
                conflicts.add(norm_col)
            elif norm_col in sizes and sizes[norm_col] != info:
                conflicts.add(norm_col)
            elif norm_col not in sizes:
                sizes[norm_col] = info

    for key in conflicts:
        sizes.pop(key, None)
    return sizes


def _target(dt: exp.Expression | None) -> tuple[str, int] | None:
    """(family, size) of a SIZED string/binary cast target, or None (unsized / MAX /
    non-string-binary targets can never narrow, so they don't qualify)."""
    if not isinstance(dt, exp.DataType):
        return None
    family = _family(dt.this.name)
    if family is None or not dt.expressions:
        return None
    tok = dt.expressions[0].sql().strip().upper()
    if tok == "MAX" or not tok.isdigit():
        return None
    return (family, int(tok))


def check(ctx: RuleContext) -> list[Finding]:
    sizes = _column_sizes(ctx)
    if not sizes:
        return []
    allow_max = ctx.param("allow_max_to_sized", False)
    findings: list[Finding] = []
    for batch, node in ctx.parsed.find_all(exp.Cast, exp.Convert):
        if isinstance(node, exp.Convert):
            target_dt, source = node.this, node.args.get("expression")
        else:  # Cast / TryCast (TryCast is a Cast subclass)
            target_dt, source = node.args.get("to"), node.this
        tgt = _target(target_dt)
        if tgt is None or source is None:
            continue
        tfamily, n = tgt
        # Widest known SAME-family column in the source subtree.
        widest: float | None = None
        widest_name = ""
        for col in source.find_all(exp.Column):
            info = sizes.get(col.name.lower())
            if info and info[0] == tfamily and (widest is None or info[1] > widest):
                widest, widest_name = info[1], col.name
        if widest is None:
            continue
        if widest == _INF and allow_max:
            continue
        if widest > n:
            src_desc = "max" if widest == _INF else str(int(widest))
            word = (
                "TRY_CAST"
                if isinstance(node, exp.TryCast)
                else ("CONVERT" if isinstance(node, exp.Convert) else "CAST")
            )
            findings.append(
                ctx.finding(
                    line=ctx.parsed.node_line(batch, node),
                    object=enclosing_object(node),
                    message=(
                        f"{word} narrows {widest_name} ({tfamily} {src_desc}) to {tfamily}({n}) — "
                        f"longer values are SILENTLY TRUNCATED (TRY_CAST does not prevent this). "
                        f"Widen the target to >= {src_desc}, or validate length before load (§I)."
                    ),
                )
            )
    return findings


RULE = Rule(
    id="SQL-NARROWING-CAST",
    title="No silent-truncation casts (narrowing a column to a shorter sized type)",
    severity="warning",
    category="datatypes",
    standard_ref="§I",
    tier=3,
    check=check,
)
