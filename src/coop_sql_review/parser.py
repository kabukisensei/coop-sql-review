"""Parse a ``.sql`` file into a :class:`ParsedFile`.

Pure and deterministic: same text in, same model out, no I/O of its own
(the caller reads the file). Batches are split with line tracking, each is
handed to sqlglot (errors ignored — a file that won't fully parse still
yields findings for the parts that do), comments are scanned out with line
spans, and CREATE TABLE/VIEW/PROC objects are lifted with their columns.
"""

from __future__ import annotations

import re

from sqlglot import exp

from coop_sql_review.diagnostics import PARSE_DEGRADED, PARSE_FAILED, SYNTAX_ERROR, Diagnostic
from coop_sql_review.identifiers import original_name
from coop_sql_review.sql_common import (
    ident_token_end,
    is_temp_table,
    line_starts,
    mask_noncode,
    parse_batch_strict,
    split_batches_with_lines,
    strip_bom,
    table_parts,
)
from coop_sql_review.sql_model import Batch, ColumnDef, Comment, ParsedFile, SqlObject


def extract_comments(text: str) -> list[Comment]:
    """All ``--`` and ``/* */`` comments with 1-based line spans.

    String literals and bracket-/quote-delimited identifiers are respected, so
    a ``--`` inside a string or a name like ``[a--b]`` is not a comment. Block
    comments nest (T-SQL semantics). Lines are counted as the scanner advances.
    """
    text = strip_bom(text)
    comments: list[Comment] = []
    i, n, line = 0, len(text), 1
    while i < n:
        ch = text[i]
        if ch == "\n":
            line += 1
            i += 1
        elif ch == "'":
            i += 1
            while i < n:
                if text[i] == "'":
                    if i + 1 < n and text[i + 1] == "'":
                        i += 2
                        continue
                    i += 1
                    break
                if text[i] == "\n":
                    line += 1
                i += 1
        elif ch == "[" or ch == '"':
            end = ident_token_end(text, i)
            line += text.count("\n", i, end)
            i = end
        elif text.startswith("--", i):
            end = text.find("\n", i)
            end = n if end == -1 else end
            comments.append(Comment(text[i:end], line, line, "line"))
            i = end
        elif text.startswith("/*", i):
            start = i
            start_line = line
            depth = 0
            while i < n:
                if text.startswith("/*", i):
                    depth += 1
                    i += 2
                elif text.startswith("*/", i):
                    depth -= 1
                    i += 2
                    if depth == 0:
                        break
                else:
                    if text[i] == "\n":
                        line += 1
                    i += 1
            comments.append(Comment(text[start:i], start_line, line, "block"))
        else:
            i += 1
    return comments


def _base_type(kind: exp.Expression | None) -> str:
    """The type keyword only, upper-cased (``DATETIME2``, not ``DATETIME2(3)``)."""
    if isinstance(kind, exp.DataType) and kind.this is not None:
        name = getattr(kind.this, "name", None) or str(kind.this)
        return str(name).upper()
    if kind is not None:
        rendered = kind.sql(dialect="tsql")
        return re.split(r"[(\s]", rendered.strip())[0].upper() if rendered else ""
    return ""


def _columns_from_schema(
    schema_expr: exp.Schema, dialect: str, batch: Batch, parsed: ParsedFile
) -> list[ColumnDef]:
    """Column contracts from a CREATE TABLE column list (original casing kept)."""
    columns: list[ColumnDef] = []
    for item in schema_expr.expressions:
        if not isinstance(item, exp.ColumnDef):
            continue
        kind = item.args.get("kind")
        data_type = kind.sql(dialect=dialect).upper() if kind is not None else ""
        nullable: bool | None = True
        constraints: list[str] = []
        for constraint in item.args.get("constraints") or []:
            kind_expr = getattr(constraint, "kind", None)
            if isinstance(kind_expr, exp.NotNullColumnConstraint):
                # sqlglot (>=26) flips the sense vs older releases: a NOT NULL
                # column yields a NotNullColumnConstraint with NO `allow_null`
                # key (-> None -> falsy), while an explicit NULL column yields
                # `allow_null=True`. So `allow_null` *is* the nullability.
                nullable = bool(kind_expr.args.get("allow_null"))
            elif isinstance(kind_expr, exp.PrimaryKeyColumnConstraint):
                constraints.append("PK")
                nullable = False
            elif isinstance(kind_expr, exp.GeneratedAsIdentityColumnConstraint):
                constraints.append("IDENTITY")
        columns.append(
            ColumnDef(
                name=item.name,
                data_type=data_type,
                base_type=_base_type(kind),
                line=parsed.node_line(batch, item),
                nullable=nullable,
                constraints=constraints,
            )
        )
    return columns


def _extract_object(create: exp.Create, batch: Batch, parsed: ParsedFile, dialect: str) -> SqlObject | None:
    """Build a SqlObject from a CREATE TABLE/VIEW/PROCEDURE, or None."""
    kind = (create.kind or "").upper()
    target = create.this
    if kind == "TABLE":
        schema_expr = target if isinstance(target, exp.Schema) else None
        table = schema_expr.this if schema_expr is not None else target
        if not isinstance(table, exp.Table):
            return None
        schema, name = table_parts(table)
        columns = _columns_from_schema(schema_expr, dialect, batch, parsed) if schema_expr else []
        return SqlObject(
            kind="table",
            schema=schema,
            name=name,
            display_name=original_name(table.name),
            line=parsed.node_line(batch, table),
            is_ctas=isinstance(create.expression, exp.Query),
            is_temp=is_temp_table(table),
            columns=columns,
        )
    view_table = target.this if isinstance(target, exp.Schema) else target
    if kind == "VIEW" and isinstance(view_table, exp.Table):
        schema, name = table_parts(view_table)
        return SqlObject(
            kind="view",
            schema=schema,
            name=name,
            display_name=original_name(view_table.name),
            line=parsed.node_line(batch, view_table),
        )
    if kind == "PROCEDURE":
        # Create(this=StoredProcedure(this=Table)); unwrap the proc (and any Schema)
        # wrapper. Lifting the proc as a SqlObject lets file-level rules and reports name
        # it, and keeps SqlObject.kind's documented "proc" value from being dead.
        proc = target.this if isinstance(target, exp.StoredProcedure) else target
        if isinstance(proc, exp.Schema):
            proc = proc.this
        if isinstance(proc, exp.Table):
            schema, name = table_parts(proc)
            return SqlObject(
                kind="proc",
                schema=schema,
                name=name,
                display_name=original_name(proc.name),
                line=parsed.node_line(batch, proc),
            )
    return None


def parse_sql(path: str, text: str, dialect: str = "tsql") -> ParsedFile:
    """Parse one SQL file's ``text`` into a :class:`ParsedFile`."""
    # Normalize line endings up front so line numbers and offsets are identical
    # whether the source uses CRLF (Windows) or LF — read_text already does this
    # for files, but a library caller may pass raw CRLF text.
    text = strip_bom(text).replace("\r\n", "\n").replace("\r", "\n")
    masked = mask_noncode(text)
    parsed = ParsedFile(
        path=path,
        text=text,
        masked=masked,
        dialect=dialect,
        comments=extract_comments(text),
        _line_offsets=line_starts(text),
    )
    for index, (batch_sql, start_line) in enumerate(split_batches_with_lines(text)):
        expressions, syntax_issues, syntax_gap = parse_batch_strict(batch_sql, dialect)
        batch = Batch(
            index=index,
            sql=batch_sql,
            start_line=start_line,
            expressions=expressions,
            syntax_issues=syntax_issues,
            syntax_gap=syntax_gap,
        )
        parsed.batches.append(batch)
        _record_parse_diagnostics(parsed, batch)
        for create in (e for e in batch.expressions if isinstance(e, exp.Create)):
            obj = _extract_object(create, batch, parsed, dialect)
            if obj is not None:
                parsed.objects.append(obj)
    return parsed


def _record_parse_diagnostics(parsed: ParsedFile, batch: Batch) -> None:
    """Note where analysis was degraded so coverage gaps aren't silent.

    A batch a real T-SQL parser rejects as invalid syntax (one error per issue),
    a valid-but-unsupported construct sqlglot can't parse (a grammar gap), a
    non-empty batch sqlglot couldn't parse at all, or a statement it could only
    represent as an opaque ``Command`` (unsupported T-SQL syntax) — each means
    rules can't see inside that region, and the user should know.
    """
    if batch.syntax_gap:
        # A sqlglot grammar gap on VALID T-SQL (compound assignment, a proc/
        # function body it can't fully parse): report the coverage gap as a
        # warning at the first flagged line — not a syntax error — so working
        # estate SQL is never reported as broken, while the gap stays visible.
        issues = sorted(batch.syntax_issues, key=lambda i: (i.line, i.col))
        line = batch.start_line - 1 + issues[0].line if issues else batch.start_line
        parsed.diagnostics.append(
            Diagnostic(
                severity="warning",
                category=PARSE_DEGRADED,
                file=parsed.path,
                line=line,
                message=(
                    "valid but unsupported T-SQL syntax here — sqlglot could not fully parse it, "
                    "so rules may under-report in this batch."
                ),
            )
        )
        return
    # Real invalid syntax first: severity "error" (the rules.yml `syntax_errors`
    # knob and inline `ignore syntax` are applied at the CLI edge, keeping this
    # function pure). Sorted by (line, col) for deterministic output.
    for issue in sorted(batch.syntax_issues, key=lambda i: (i.line, i.col)):
        parsed.diagnostics.append(
            Diagnostic(
                severity="error",
                category=SYNTAX_ERROR,
                file=parsed.path,
                line=batch.start_line - 1 + issue.line,
                message=f"syntax error: {issue.message} (col {issue.col})",
            )
        )
    if batch.sql.strip() and not batch.expressions:
        parsed.diagnostics.append(
            Diagnostic(
                severity="warning",
                category=PARSE_FAILED,
                file=parsed.path,
                line=batch.start_line,
                message="could not parse this SQL batch — rules may under-report here.",
            )
        )
        return
    for expression in batch.expressions:
        if isinstance(expression, exp.Command):
            parsed.diagnostics.append(
                Diagnostic(
                    severity="warning",
                    category=PARSE_DEGRADED,
                    file=parsed.path,
                    line=parsed.node_line(batch, expression),
                    message=(
                        "statement parsed as an opaque command (unsupported syntax) — "
                        "rules that inspect its structure may not apply here."
                    ),
                )
            )
