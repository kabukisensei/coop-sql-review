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


def _update_sources(update: exp.Update) -> list[exp.Table]:
    """The top-level FROM/JOIN source tables of an ``UPDATE ... FROM``.

    Deliberately does NOT ``find_all(exp.Table)`` — that would descend into
    derived-table subqueries, whose inner tables must not capture the alias.
    sqlglot hangs the join list off the first FROM source (and, defensively,
    the Update node itself); the ``from`` arg key is ``from_`` on sqlglot 30
    and ``from`` on older majors in the pin range.
    """
    frm = update.args.get("from_") or update.args.get("from")
    if frm is None:
        return []
    sources: list[exp.Expression] = []
    base = frm.this
    if base is not None:
        sources.append(base)
        sources.extend(join.this for join in base.args.get("joins") or [])
    sources.extend(join.this for join in update.args.get("joins") or [])
    return [source for source in sources if isinstance(source, exp.Table)]


def _resolve_update_alias(update: exp.Update, target: exp.Table) -> exp.Table | None:
    """The FROM/JOIN source an aliased ``UPDATE alias ... FROM`` binds to, or ``None``.

    T-SQL's idiomatic aliased update (``UPDATE d SET ... FROM silver.dim AS d``)
    parses with the bare alias as ``Update.this``, so the naive target would be
    the nonexistent ``dbo.d`` — an alias-dependent name whose suppression
    fingerprint breaks on an alias rename and collides across procs (issue #14).
    Resolution is attempted only for a one-part, non-temp target name; the alias
    match wins over a table-name match, and no match falls back to today's
    behavior (a genuine one-part table name resolves as before).
    """
    if target.text("db") or target.text("catalog") or is_temp_table(target):
        return None
    key = normalize_identifier(target.name)
    by_alias: dict[str, exp.Table] = {}
    by_name: dict[str, exp.Table] = {}
    for source in _update_sources(update):
        alias = normalize_identifier(source.alias) if source.alias else ""
        if alias:
            by_alias.setdefault(alias, source)
        name = normalize_identifier(source.name)
        if name:
            by_name.setdefault(name, source)
    return by_alias.get(key) or by_name.get(key)


def dml_target(node: exp.Expression) -> str:
    """The name of the table an INSERT/UPDATE/DELETE/MERGE writes to, or "" —
    ``schema.name`` (normalized) for persisted tables, ``#``-/``@``-prefixed
    for temp tables and table variables (see ``table_ref``). For the T-SQL
    aliased-update form (``UPDATE d SET ... FROM silver.dim AS d``) the alias
    is resolved through the FROM/JOIN sources to the real table."""
    target = dml_target_table(node)
    if target is None:
        return ""
    if isinstance(node, exp.Update):
        resolved = _resolve_update_alias(node, target)
        if resolved is not None:
            return table_ref(resolved)
    return table_ref(target)


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


# -- join-key alignment tolerance --------------------------------------------
# Shared by SQL-JOIN-FILTER (§8) and SQL-SARGABILITY (§A) so the two rules never
# give contradictory guidance on the same ON predicate (issue #15): a wrapper
# that one rule documents as idiomatic key alignment must not be a rewrite
# demand in the other.

# Idiomatic wrappers used to align keys; not business logic on their own.
# (``ISNULL`` parses to ``exp.Coalesce`` under the tsql dialect.)
_ALIGNMENT_WRAPPERS = (exp.Coalesce, exp.Cast, exp.Convert, exp.Collate)

# Node types allowed inside an alignment wrapper for it to count as part of the
# key: bare columns/identifiers, literals, type/collation tokens, NULL, and
# nested alignment wrappers (handled separately in ``is_alignment_subtree``).
# ``exp.DataTypeParam`` is the size/precision of a sized type (``VARCHAR(10)``,
# ``DECIMAL(19, 4)``) — it can only hold literals/vars, so it cannot smuggle a
# business function past the tolerance.
_ALIGNMENT_LEAVES = (
    exp.Column,
    exp.Identifier,
    exp.Literal,
    exp.DataType,
    exp.DataTypeParam,
    exp.Var,
    exp.Null,
)


def is_alignment_subtree(node: exp.Expression) -> bool:
    """True if ``node`` is an alignment wrapper containing only key material.

    Such a subtree (e.g. ``COALESCE(a.id, 0)`` or ``CAST(a.id AS INT)`` —
    nesting included, ``CAST(COALESCE(a.id, 0) AS INT)``) is considered part of
    a join key. A wrapper enclosing anything else (notably a real function
    call, ``CAST(YEAR(a.d) AS INT)``) is not benign and is left for the normal
    checks to flag.
    """
    if not isinstance(node, _ALIGNMENT_WRAPPERS):
        return False
    for child in node.walk():
        if child is node:
            continue
        if isinstance(child, _ALIGNMENT_WRAPPERS) or isinstance(child, _ALIGNMENT_LEAVES):
            continue
        return False
    return True


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
