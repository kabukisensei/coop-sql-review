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

import sqlglot
from sqlglot import exp

from coop_sql_review.identifiers import normalize_identifier

# A line that is only a GO batch separator.
GO_LINE_RE = re.compile(r"^\s*GO\s*;?\s*$", re.IGNORECASE)
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
        elif sql.startswith("--", i):
            while i < n and sql[i] != "\n":
                out.append(" ")
                i += 1
        elif sql.startswith("/*", i):
            end = sql.find("*/", i)
            end = n if end == -1 else end + 2
            for k in range(i, end):
                out.append("\n" if sql[k] == "\n" else " ")
            i = end
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
