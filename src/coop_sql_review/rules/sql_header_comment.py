"""SQL-HEADER-COMMENT (§10): every SQL file starts with a header block.

§10 shows the expected header: a comment carrying File / Purpose / Source /
Author / Date (and a change log). We don't demand every field — that would be
noisy for an info rule — but we do require a top-of-file comment that at least
names the File and its Purpose. Both ``/* */`` block comments and ``--`` line
comments near the top (``line_start <= 5``) count, and their text is combined
so a header split across several ``-- File:`` / ``-- Purpose:`` lines satisfies
the rule. Matching is on word boundaries (``\\bfile\\b`` / ``\\bpurpose\\b``,
case-insensitive) so incidental words like ``datafile`` or ``purposeful`` do
not falsely satisfy it. Empty files (no batches) are skipped; otherwise a
single finding is emitted at line 1.
"""

from __future__ import annotations

import re

from coop_sql_review.finding import Finding
from coop_sql_review.rules.base import Rule, RuleContext

_TOP_LINES = 5
_FILE_RE = re.compile(r"\bfile\b", re.IGNORECASE)
_PURPOSE_RE = re.compile(r"\bpurpose\b", re.IGNORECASE)


def check(ctx: RuleContext) -> list[Finding]:
    # Nothing to header when the file has no SQL content.
    if not ctx.parsed.batches:
        return []

    header_text = "\n".join(
        comment.text for comment in ctx.parsed.comments if comment.line_start <= _TOP_LINES
    )
    if _FILE_RE.search(header_text) and _PURPOSE_RE.search(header_text):
        return []

    return [
        ctx.finding(
            line=1,
            object="",
            message=("file is missing a header comment block (File/Purpose/Source/Author/Date) (§10)."),
        )
    ]


RULE = Rule(
    id="SQL-HEADER-COMMENT",
    title="Every SQL file starts with a header comment block",
    severity="info",
    category="comments",
    standard_ref="§10",
    tier=2,
    check=check,
)
