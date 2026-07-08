"""The parsed model the rule engine runs against.

Unlike coop-data-doc (which parses SQL into a lineage graph), the linter
needs every construct kept next to its **file line number** and the file's
**comments** — so findings can point at an exact line and rules like
header-comment / EXISTS-comment can reason about prose. ``ParsedFile`` holds
the sqlglot AST per batch plus the raw text, a position-preserving masked
copy, comment spans, and extracted objects, with helpers to turn any AST
node into a file line.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Optional

from sqlglot import exp

from coop_sql_review.diagnostics import Diagnostic
from coop_sql_review.sql_common import SyntaxIssue

LAYERS = ("bronze", "silver", "gold")


def _min_meta_line(node: exp.Expression) -> Optional[int]:
    """Smallest ``meta['line']`` among ``node`` and its descendants.

    sqlglot only tags leaf ``Identifier``/``Literal``/``Star`` nodes with a
    line, so for a composite node (a ColumnDef, a Table, an Insert) we take
    the earliest line-bearing leaf under it.
    """
    best: Optional[int] = None
    for descendant in node.walk():
        line = (getattr(descendant, "meta", None) or {}).get("line")
        if line is not None and (best is None or line < best):
            best = line
    return best


@dataclass
class Comment:
    """One comment span, with 1-based file line numbers."""

    text: str
    line_start: int
    line_end: int
    kind: str  # "line" | "block"


@dataclass
class ColumnDef:
    """A column in a CREATE TABLE, with its line and normalized type."""

    name: str
    data_type: str  # rendered, e.g. "NVARCHAR(50)"
    base_type: str  # type keyword only, upper-cased, e.g. "NVARCHAR", "DATETIME2"
    line: int
    nullable: Optional[bool] = None
    constraints: list[str] = field(default_factory=list)


@dataclass
class SqlObject:
    """A top-level object created in the file (table / view / proc)."""

    kind: str  # "table" | "view" | "proc"
    schema: str
    name: str
    display_name: str
    line: int
    is_ctas: bool = False
    is_temp: bool = False  # #temp / @table-variable target (not a real estate object)
    columns: list[ColumnDef] = field(default_factory=list)

    @property
    def qualified(self) -> str:
        return f"{self.schema}.{self.display_name}" if self.schema else self.display_name

    @property
    def layer(self) -> Optional[str]:
        """Medallion layer from the schema name, or None."""
        return self.schema.lower() if self.schema.lower() in LAYERS else None


@dataclass
class Batch:
    """One GO-delimited batch: its text, file start line, and parsed AST."""

    index: int
    sql: str
    start_line: int
    expressions: list[exp.Expression] = field(default_factory=list)
    syntax_issues: list[SyntaxIssue] = field(default_factory=list)  # invalid-syntax errors
    syntax_gap: bool = False  # the errors are a sqlglot gap on valid T-SQL (report as degraded)


@dataclass
class ParsedFile:
    """Everything a rule needs about one ``.sql`` file."""

    path: str
    text: str
    masked: str
    dialect: str
    batches: list[Batch] = field(default_factory=list)
    comments: list[Comment] = field(default_factory=list)
    objects: list[SqlObject] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    _line_offsets: list[int] = field(default_factory=list)
    # Lazily-built caches (not part of identity/equality). The node index flattens every
    # AST node once so find_all() serves each of the ~20+ rule walks by filtering the list
    # instead of re-walking the tree per rule. See find_all().
    _nodes: Optional[list] = field(default=None, compare=False, repr=False)
    # Cached EXISTS-predicate sites (helpers.exists_sites): both SQL-EXISTS-COMMENT and
    # SQL-EXISTS-WHY-QUALITY ask for them, so the masked text is regex-scanned just once.
    _exists_sites: Optional[list] = field(default=None, compare=False, repr=False)

    # -- line mapping -------------------------------------------------------

    def line_of_offset(self, offset: int) -> int:
        """1-based file line containing character ``offset`` (for regex hits
        on ``self.masked``, whose offsets match ``self.text`` exactly)."""
        return bisect_right(self._line_offsets, offset)

    def node_line(self, batch: Batch, node: exp.Expression) -> int:
        """1-based file line of an AST ``node`` parsed within ``batch``.

        Falls back to the batch's start line when no descendant leaf carries
        a line (so a finding always has a usable, deterministic location).
        """
        relative = _min_meta_line(node)
        return batch.start_line + (relative - 1) if relative else batch.start_line

    # -- traversal convenience ---------------------------------------------

    def iter_expressions(self) -> Iterator[tuple[Batch, exp.Expression]]:
        """Yield ``(batch, top_level_expression)`` for every parsed statement."""
        for batch in self.batches:
            for expression in batch.expressions:
                yield batch, expression

    def find_all(self, *types: type[exp.Expression]) -> Iterator[tuple[Batch, exp.Expression]]:
        """Yield ``(batch, node)`` for every AST node of the given type(s).

        Backed by a per-file node index built ONCE (one walk per top-level statement),
        then served by ``isinstance`` filtering — so 24 rules don't each re-walk the tree.
        Semantics are unchanged: the index is built with ``find_all(exp.Expression)`` (every
        node, in the exact walk order sqlglot's ``find_all`` uses), so subclass matching and
        document order are byte-identical to the old per-call walk.
        """
        if self._nodes is None:
            nodes: list[tuple[Batch, exp.Expression]] = []
            for batch in self.batches:
                for expression in batch.expressions:
                    for node in expression.find_all(exp.Expression):
                        nodes.append((batch, node))
            self._nodes = nodes
        for batch, node in self._nodes:
            if isinstance(node, types):
                yield batch, node
