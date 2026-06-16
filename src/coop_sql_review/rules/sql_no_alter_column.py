"""SQL-NO-ALTER-COLUMN (§9): ALTER COLUMN is unsupported in Fabric DW.

Fabric Data Warehouse does not support ``ALTER TABLE ... ALTER COLUMN``; the
schema-evolution workaround is to rebuild the table via CTAS and then RENAME.

Detection is text-based (over the comment/string-masked source) rather than
AST-based on purpose: sqlglot degrades the most common real form —
``ALTER COLUMN c <type> NOT NULL`` and the MASKED variants — to an opaque
``exp.Command`` node, so an AST-only check would miss exactly the statements
this rule most needs to catch. The mask guarantees a match can't come from a
comment or string literal, and offsets map straight to file lines. ``ADD`` /
``DROP COLUMN`` do not match the ``ALTER COLUMN`` pattern, so they are ignored.
"""

from __future__ import annotations

import re

from coop_sql_review.finding import Finding
from coop_sql_review.identifiers import qualify
from coop_sql_review.rules.base import Rule, RuleContext

_ALTER_COLUMN_RE = re.compile(
    r"\bALTER\s+TABLE\s+([#@\w\[\].]+)\s+ALTER\s+COLUMN\b",
    re.IGNORECASE,
)


def check(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    for match in _ALTER_COLUMN_RE.finditer(ctx.parsed.masked):
        schema, name = qualify(match.group(1))
        findings.append(
            ctx.finding(
                line=ctx.parsed.line_of_offset(match.start()),
                object=f"{schema}.{name}",
                message="ALTER COLUMN is not supported in Fabric DW — use the CTAS + RENAME workaround (§9).",
            )
        )
    return findings


RULE = Rule(
    id="SQL-NO-ALTER-COLUMN",
    title="No ALTER COLUMN in Fabric DW",
    severity="error",
    category="schema-evolution",
    standard_ref="§9",
    tier=1,
    check=check,
)
