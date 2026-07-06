"""Shared SQL helpers — the pure-text/AST layer the linter is built on.

sqlglot (dialect ``tsql``) does the heavy lifting for structure; the
text helpers here exist to (a) split a script into batches while tracking
each batch's starting line in the file, and (b) mask comments and string
literals *without changing character offsets*, so regex-based rules can
scan code only and still report exact line numbers.

Lifted and adapted from coop-data-doc's ``parsers/sql_common.py`` (its
lineage-graph coupling removed). The reusable batch/parse helpers are kept;
the masking + line-aware splitting are new, for rule line reporting.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from coop_sql_review.identifiers import normalize_identifier

# A line that is only a GO batch separator — including T-SQL's repeat form
# ``GO <count>`` (the execution count is irrelevant to linting; what matters is
# that the statements after it stay in their own batch and are still checked).
GO_LINE_RE = re.compile(r"^\s*GO(?:\s+\d+)?\s*;?\s*$", re.IGNORECASE)
PROC_HEADER_RE = re.compile(r"\bCREATE\s+(?:OR\s+ALTER\s+)?PROC(?:EDURE)?\s+([\w\[\].]+)", re.IGNORECASE)


def strip_bom(text: str) -> str:
    """Drop a UTF-8 BOM if present."""
    return text.lstrip("﻿")


def parse_batch(batch: str, dialect: str = "tsql") -> list[exp.Expression]:
    """``sqlglot.parse`` with errors ignored; returns ``[]`` instead of raising.

    sqlglot tags ``Identifier``/``Literal``/``Star`` leaf nodes with
    ``meta['line']`` (1-based, relative to ``batch``); see ``sql_model`` for
    how that maps back to a file line.
    """
    try:
        parsed = sqlglot.parse(batch, read=dialect, error_level=sqlglot.ErrorLevel.IGNORE)
    except Exception:
        return []
    return [expression for expression in parsed if expression is not None]


@dataclass(frozen=True)
class SyntaxIssue:
    """One parser-level syntax error inside a batch.

    ``line``/``col`` are 1-based and **relative to the batch** (the caller adds
    the batch's file start line). ``message`` is the sqlglot error's structured
    ``description``, squeezed to a single ASCII line — never sqlglot's rendered
    message, which embeds a SQL snippet with ANSI underline escapes (would break
    the deterministic, cp1252-safe output contract).
    """

    line: int
    col: int
    message: str


def _issue_from_error(entry: dict) -> SyntaxIssue:
    """Build a :class:`SyntaxIssue` from one entry of ``ParseError.errors``.

    Uses only the structured ``description``/``line``/``col`` keys. The
    description is collapsed to one line and forced to ASCII (replacement char
    for any stray non-ASCII), so the resulting diagnostic is deterministic and
    safe on a legacy Windows console.
    """
    raw = entry.get("description") or "invalid SQL syntax"
    message = " ".join(str(raw).split()).encode("ascii", "replace").decode("ascii")
    line = entry.get("line")
    col = entry.get("col")
    return SyntaxIssue(
        line=line if isinstance(line, int) and line > 0 else 1,
        col=col if isinstance(col, int) and col > 0 else 1,
        message=message or "invalid SQL syntax",
    )


# sqlglot's generic "I hit a token I didn't expect" message. It shows up on both
# genuinely broken SQL (usually alongside a definitive error, or with an
# un-representable statement -> a None in the IGNORE recovery) and on a handful
# of *valid* T-SQL constructs its tsql grammar can't parse. Only the latter,
# None-free, definitive-error-free case is treated as a gap (see _is_sqlglot_gap).
_GENERIC_PARSE_ERROR = "Invalid expression / Unexpected token"

# A T-SQL compound-assignment statement (`SET @v += x`, and -=, *=, /=, %=, &=,
# |=, ^=). Valid T-SQL that sqlglot's tsql dialect cannot parse — it raises a
# "Required keyword: 'this' missing for ..." on the operator. Matched on the
# masked batch so a match inside a string/comment can't fire.
_COMPOUND_ASSIGN_RE = re.compile(r"\bSET\b\s+@\w+\s*[-+*/%&|^]=", re.IGNORECASE)

# A CLUSTERED / NONCLUSTERED index or key constraint (`PRIMARY KEY CLUSTERED
# (col ASC)`). Valid T-SQL that sqlglot's tsql dialect mis-parses — it raises
# "Expecting )" and a "'buckets' missing" (ClusteredByProperty) on the sort spec.
_CLUSTERED_INDEX_RE = re.compile(r"\b(?:NON)?CLUSTERED\b", re.IGNORECASE)


def _description_is_gap(description: str, has_compound_assign: bool, has_clustered_index: bool) -> bool:
    """Whether one sqlglot error description is a known gap on *valid* T-SQL,
    given what constructs the batch actually contains."""
    if description == _GENERIC_PARSE_ERROR:
        # Generic "unexpected token": the had_none guard in _is_sqlglot_gap has
        # already excluded its common genuinely-broken forms.
        return True
    if has_compound_assign and description.startswith("Required keyword: 'this' missing"):
        return True  # compound-assignment operator (SET @v += x)
    if has_clustered_index and (description == "Expecting )" or "'buckets' missing" in description):
        return True  # CLUSTERED / NONCLUSTERED index or key constraint
    return False


def _is_sqlglot_gap(masked_batch: str, descriptions: list[str], had_none: bool) -> bool:
    """Whether a RAISE-level ``ParseError`` is a **sqlglot grammar gap on valid
    T-SQL** (to be reported as a ``parse_degraded`` warning) rather than genuinely
    invalid syntax (a ``syntax_error``).

    Conservative — genuine breakage wins every tie. A batch is a gap only when
    NONE of the genuine-breakage signals is present:

    - ``had_none``: sqlglot couldn't build even an opaque node for some statement
      (the strongest "this is broken" signal), or
    - any error description that is *definitive* of malformed SQL — i.e. one that
      :func:`_description_is_gap` does not explain as a known gap on valid T-SQL.

    The known gaps (see ``AGENTS.md`` "sqlglot caveat") are: the generic
    ``Invalid expression / Unexpected token`` (after the ``had_none`` guard), the
    ``Required keyword: 'this' missing`` on a compound assignment (``SET @v += x``),
    and the ``Expecting )`` / ``'buckets' missing`` on a ``CLUSTERED`` key/index.
    Because the estate's real incident (a mangled CTE inside a stored proc) also
    raises ``column does not support CTE`` — a definitive description — it is never
    mistaken for a gap even though it, like the valid procs, recovers to an opaque
    ``Command``. And a *misclassified* real error is still surfaced (as a
    ``parse_degraded`` warning), so a coverage gap is never silent.
    """
    if had_none or not descriptions:
        return False
    has_compound_assign = _COMPOUND_ASSIGN_RE.search(masked_batch) is not None
    has_clustered_index = _CLUSTERED_INDEX_RE.search(masked_batch) is not None
    return all(
        _description_is_gap(description, has_compound_assign, has_clustered_index)
        for description in descriptions
    )


def parse_batch_strict(
    batch: str, dialect: str = "tsql"
) -> tuple[list[exp.Expression], list[SyntaxIssue], bool]:
    """Parse a batch, returning ``(expressions, syntax_issues, is_gap)``.

    Fast path: parse once at ``RAISE``. Valid T-SQL — including syntax sqlglot
    only *degrades* to an opaque ``Command`` (``ALTER COLUMN ... NOT NULL``),
    which does **not** raise — returns its expressions, no issues, ``is_gap=False``.

    On a real ``ParseError``, record one :class:`SyntaxIssue` per structured
    error and re-parse at ``IGNORE`` to recover the partial AST so rules still see
    the parts that parsed (the tool's partial-analysis promise). ``is_gap`` says
    whether the error is a known sqlglot grammar gap on *valid* T-SQL (see
    :func:`_is_sqlglot_gap`) — the caller reports a gap as a ``parse_degraded``
    warning and a non-gap as a ``syntax_error``. A ``ParseError`` with no
    structured errors still yields one belt-and-braces issue, so genuinely broken
    SQL can never pass as clean. Any other sqlglot failure (e.g. a tokenizer
    error) falls back to the tolerant ``IGNORE`` parse with no issues.
    """
    try:
        parsed = sqlglot.parse(batch, read=dialect, error_level=sqlglot.ErrorLevel.RAISE)
        return ([expression for expression in parsed if expression is not None], [], False)
    except ParseError as error:
        try:
            raw = sqlglot.parse(batch, read=dialect, error_level=sqlglot.ErrorLevel.IGNORE)
        except Exception:
            raw = []
        recovered = [expression for expression in raw if expression is not None]
        had_none = any(expression is None for expression in raw)
        entries = error.errors or []
        issues = [_issue_from_error(entry) for entry in entries] or [
            SyntaxIssue(line=1, col=1, message="invalid SQL syntax")
        ]
        descriptions = [str(entry.get("description") or "") for entry in entries]
        is_gap = _is_sqlglot_gap(mask_noncode(batch), descriptions, had_none)
        return (recovered, issues, is_gap)
    except Exception:
        return (parse_batch(batch, dialect), [], False)


def ident_token_end(sql: str, i: int) -> int:
    """Index just past a bracket-/quote-delimited identifier starting at ``sql[i]``.

    T-SQL delimited identifiers are ``[ ... ]`` (with ``]]`` an escaped ``]``)
    and ``" ... "`` (with ``""`` an escaped ``"``). A ``'``, ``--`` or ``/*``
    *inside* such an identifier is part of the name, not the start of a string
    or comment — e.g. ``[Customer's Name]`` or ``[a--b]`` — so any scanner that
    masks strings/comments must skip the whole token first. Returns the index
    just after the closing delimiter (or ``len(sql)`` if it is unterminated).
    """
    closer = "]" if sql[i] == "[" else sql[i]
    j, n = i + 1, len(sql)
    while j < n:
        if sql[j] == closer:
            if j + 1 < n and sql[j + 1] == closer:  # doubled = escaped delimiter
                j += 2
                continue
            return j + 1
        j += 1
    return n


def mask_noncode(sql: str) -> str:
    """Blank out comment bodies and string-literal contents, preserving every
    character position and newline.

    The returned string has the SAME length and the same newlines as ``sql``,
    so ``masked[:offset].count(chr(10))`` is the exact line offset of any code
    position, and a regex over ``masked`` can never match inside a comment or
    string. Quote delimiters are kept so string tokens still bound correctly.
    """
    out: list[str] = []
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch == "'":
            out.append("'")
            i += 1
            while i < n:
                if sql[i] == "'":
                    if i + 1 < n and sql[i + 1] == "'":
                        out.append("  ")  # escaped quote inside the literal
                        i += 2
                        continue
                    out.append("'")
                    i += 1
                    break
                out.append("\n" if sql[i] == "\n" else " ")
                i += 1
        elif ch == "[" or ch == '"':
            # A delimited identifier is code, not a string/comment: copy it
            # through verbatim so a `'`, `--` or `/*` inside the name (e.g.
            # `[Customer's Name]`) never starts a spurious string/comment that
            # would blank the rest of the file.
            end = ident_token_end(sql, i)
            out.append(sql[i:end])
            i = end
        elif sql.startswith("--", i):
            while i < n and sql[i] != "\n":
                out.append(" ")
                i += 1
        elif sql.startswith("/*", i):
            # T-SQL block comments nest, so pair `/*`/`*/` by depth rather than
            # stopping at the first `*/`.
            depth = 0
            while i < n:
                if sql.startswith("/*", i):
                    depth += 1
                    out.append("  ")
                    i += 2
                elif sql.startswith("*/", i):
                    depth -= 1
                    out.append("  ")
                    i += 2
                    if depth == 0:
                        break
                else:
                    out.append("\n" if sql[i] == "\n" else " ")
                    i += 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def split_batches_with_lines(text: str) -> list[tuple[str, int]]:
    """Split a script on ``GO`` lines into ``(batch_text, start_line)`` pairs.

    ``start_line`` is the 1-based file line of the batch's first line, so a
    construct sqlglot reports at relative line ``L`` within ``batch_text`` is
    at file line ``start_line + L - 1``. Leading blank lines are preserved to
    keep that mapping exact; empty/whitespace-only batches are dropped. GO is
    detected on the masked text so a ``GO`` inside a comment never splits.
    """
    text = strip_bom(text)
    raw_lines = text.split("\n")
    masked_lines = mask_noncode(text).split("\n")
    batches: list[tuple[str, int]] = []
    buf: list[str] = []
    start_line = 1
    for idx, masked_line in enumerate(masked_lines):
        file_line = idx + 1
        if GO_LINE_RE.match(masked_line):
            if any(line.strip() for line in buf):
                batches.append(("\n".join(buf), start_line))
            buf = []
            start_line = file_line + 1
        else:
            if not buf:
                start_line = file_line
            buf.append(raw_lines[idx])
    if any(line.strip() for line in buf):
        batches.append(("\n".join(buf), start_line))
    return batches


def line_starts(text: str) -> list[int]:
    """Character offset at which each (1-based) line begins.

    ``offsets[k]`` is the start offset of line ``k+1``; used to turn a
    character offset into a line number via bisect.
    """
    offsets = [0]
    for i, ch in enumerate(text):
        if ch == "\n":
            offsets.append(i + 1)
    return offsets


def table_parts(table: exp.Table) -> tuple[str, str]:
    """``(schema, name)`` for a sqlglot Table, lowercased, defaulting to dbo."""
    schema = normalize_identifier(table.text("db")) or "dbo"
    return (schema, normalize_identifier(table.name))


def is_temp_table(table: exp.Table) -> bool:
    """True for ``#temp`` / ``##global`` temp tables and ``@table`` variables.

    sqlglot's tsql parser strips the ``#`` prefix from ``table.name`` (and for a
    single ``#`` flags the identifier ``temporary=True``), so a check on the
    bare name alone is not enough -- a global ``##temp`` table loses both signals.
    The rendered ``table.sql()`` still carries the original ``#``/``@`` prefix,
    so use it as the authoritative guard.
    """
    rendered = table.sql(dialect="tsql").lstrip("[")
    if rendered.startswith("#") or rendered.startswith("@"):
        return True
    if table.name.startswith("#") or table.name.startswith("@"):
        return True
    ident = table.this
    return isinstance(ident, exp.Identifier) and bool(ident.args.get("temporary"))


def cte_names(expression: exp.Expression) -> set[str]:
    """Normalized aliases of every CTE under an expression."""
    return {normalize_identifier(cte.alias_or_name) for cte in expression.find_all(exp.CTE)}
