"""Shared helpers for rule modules.

Not a rule module (the name doesn't start with ``sql_``), so the registry
skips it. Rules import from here for the few cross-cutting needs: naming the
object a node sits inside, and recognizing projection stars.
"""

from __future__ import annotations

import re

from sqlglot import exp

from coop_sql_review.sql_common import table_parts

# EXISTS( as a predicate, located in code (comments/strings already masked out).
_EXISTS_RE = re.compile(r"\b(?:NOT\s+)?EXISTS\s*\(", re.IGNORECASE)
# An IF/WHILE just before it makes this a control/DDL existence guard, not the
# query-predicate EXISTS that §7 is about. Tolerates a parenthesized condition
# (``IF (NOT EXISTS (...))``) — the paren may only sit between the keyword and
# the (NOT) EXISTS, so a ``WHERE (NOT EXISTS ...)`` predicate never matches.
_GUARD_BEFORE_RE = re.compile(r"\b(?:IF|WHILE)\s*\(?\s*(?:NOT\s+)?$", re.IGNORECASE)
# How far back to look for the guard keyword: long enough for
# ``WHILE  ( NOT `` with generous whitespace, short enough to stay local.
_GUARD_WINDOW = 24


def exists_sites(parsed) -> list[tuple[int, bool]]:
    """Every ``EXISTS(`` predicate as ``(file_line, is_guard)``.

    Located by scanning the comment/string-masked text, so the line is the
    actual ``EXISTS`` keyword line (sqlglot tags no leaf there, so an AST
    ``node_line`` would wrongly point inside the subquery). ``is_guard`` is
    True for ``IF EXISTS`` / ``WHILE EXISTS`` existence guards, which §7's
    "explain why over COUNT/JOIN/IN" guidance does not apply to.
    """
    sites: list[tuple[int, bool]] = []
    for match in _EXISTS_RE.finditer(parsed.masked):
        line = parsed.line_of_offset(match.start())
        preceding = parsed.masked[max(0, match.start() - _GUARD_WINDOW) : match.start()]
        sites.append((line, bool(_GUARD_BEFORE_RE.search(preceding))))
    return sites


def enclosing_object(node: exp.Expression) -> str:
    """``schema.name`` (normalized) of the CREATE that encloses ``node``, or ""."""
    current = node.parent
    while current is not None:
        if isinstance(current, exp.Create):
            target = current.this
            table = target.this if isinstance(target, exp.Schema) else target
            if isinstance(table, exp.Table):
                schema, name = table_parts(table)
                return f"{schema}.{name}"
            return ""
        current = current.parent
    return ""


def dml_target(node: exp.Expression) -> str:
    """``schema.name`` (normalized) of the table an INSERT/UPDATE/DELETE/MERGE
    writes to, or "". Handles ``INSERT INTO t (cols)`` where ``this`` is a
    Schema wrapping the Table."""
    target = node.this
    if isinstance(target, exp.Schema):
        target = target.this
    if isinstance(target, exp.Table):
        schema, name = table_parts(target)
        return f"{schema}.{name}"
    return ""


def preceding_comment(parsed, line: int, within: int = 3) -> bool:
    """True if a comment ends on one of the ``within`` lines just above ``line``.

    Used by rules that require an explaining comment immediately above a
    construct (e.g. EXISTS). Blank lines between the comment and the construct
    are tolerated up to ``within``.
    """
    return any(0 < line - comment.line_end <= within for comment in parsed.comments)


def projection_stars(select: exp.Select) -> list[exp.Expression]:
    """Projection items of ``select`` that are an unqualified or qualified
    ``*`` (``SELECT *`` / ``SELECT t.*``) — excludes ``COUNT(*)`` and friends,
    where the star is an argument nested inside a function, not a projection.
    """
    stars: list[exp.Expression] = []
    for projection in select.expressions:
        if isinstance(projection, exp.Star):
            stars.append(projection)
        elif isinstance(projection, exp.Column) and isinstance(projection.this, exp.Star):
            stars.append(projection)
    return stars
