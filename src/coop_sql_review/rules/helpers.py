"""Shared helpers for rule modules.

Not a rule module (the name doesn't start with ``sql_``), so the registry
skips it. Rules import from here for the few cross-cutting needs: naming the
object a node sits inside, and recognizing projection stars.
"""

from __future__ import annotations

import re

from sqlglot import exp

from coop_sql_review.identifiers import normalize_identifier
from coop_sql_review.sql_common import is_temp_table, table_parts

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
    if parsed._exists_sites is not None:
        return parsed._exists_sites
    sites: list[tuple[int, bool]] = []
    for match in _EXISTS_RE.finditer(parsed.masked):
        line = parsed.line_of_offset(match.start())
        preceding = parsed.masked[max(0, match.start() - _GUARD_WINDOW) : match.start()]
        sites.append((line, bool(_GUARD_BEFORE_RE.search(preceding))))
    parsed._exists_sites = sites
    return sites


# The #/##/@ prefix at the start of a (bracket-stripped) rendered table name.
_TEMP_PREFIX_RE = re.compile(r"(##?|@)")


def table_ref(table: exp.Table) -> str:
    """How findings name a table: ``schema.name`` (normalized, dbo-defaulted)
    for persisted tables; the ``#``/``##``/``@``-prefixed bare name for temp
    tables and table variables. sqlglot normalizes the prefix away
    (``#staging`` -> name ``staging``), so rendering the normalized parts would
    produce ``dbo.staging`` — the wrong name, whose suppression fingerprint
    collides with a REAL table called ``dbo.staging`` (issue #13). The prefix
    is recovered from the rendered SQL, where sqlglot preserves it.
    """
    if is_temp_table(table):
        name = normalize_identifier(table.name)
        if name.startswith(("#", "@")):
            return name  # some parses keep the prefix on the identifier itself
        rendered = table.sql(dialect="tsql").lstrip("[")
        match = _TEMP_PREFIX_RE.match(rendered)
        prefix = match.group(1) if match else "#"
        return f"{prefix}{name}"
    schema, name = table_parts(table)
    return f"{schema}.{name}"


def enclosing_object(node: exp.Expression) -> str:
    """``schema.name`` (normalized) of the CREATE that encloses ``node``, or ""
    (``#``-/``@``-prefixed for a temp table — same convention as ``table_ref``)."""
    current = node.parent
    while current is not None:
        if isinstance(current, exp.Create):
            target = current.this
            # CREATE PROCEDURE parses to Create(this=StoredProcedure(this=Table)); unwrap
            # the proc wrapper (and a Schema wrapper) so a finding inside a proc BODY is
            # attributed to the proc, not "" — the whole estate is procs, and an empty
            # object collapses the suppression fingerprint to (rule_id, message).
            if isinstance(target, exp.StoredProcedure):
                target = target.this
            if isinstance(target, exp.Schema):
                target = target.this
            if isinstance(target, exp.Table):
                return table_ref(target)
            return ""
        current = current.parent
    return ""


def dml_target_table(node: exp.Expression) -> exp.Table | None:
    """The Table node an INSERT/UPDATE/DELETE/MERGE writes to, or ``None``.
    Handles ``INSERT INTO t (cols)`` where ``this`` is a Schema wrapping the Table."""
    target = node.this
    if isinstance(target, exp.Schema):
        target = target.this
    return target if isinstance(target, exp.Table) else None


def dml_target(node: exp.Expression) -> str:
    """The name of the table an INSERT/UPDATE/DELETE/MERGE writes to, or "" —
    ``schema.name`` (normalized) for persisted tables, ``#``-/``@``-prefixed
    for temp tables and table variables (see ``table_ref``)."""
    target = dml_target_table(node)
    return table_ref(target) if target is not None else ""


def preceding_comment(parsed, line: int, within: int = 3) -> bool:
    """True if a comment explains the construct at ``line``: one ending ON that line
    (a trailing ``-- why`` / ``/* why */``, the ``0 <=`` case) or up to ``within`` lines
    above it, OR a block comment that spans the line. Blank lines between a preceding
    comment and the construct are tolerated up to ``within``.

    ``0 <=`` (not ``0 <``) so a same-line trailing comment — a very common way to write
    exactly the §7 explanation — counts; the old strict ``0 <`` flagged it as missing.
    """
    return any(
        0 <= line - comment.line_end <= within or comment.line_start <= line <= comment.line_end
        for comment in parsed.comments
    )


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
