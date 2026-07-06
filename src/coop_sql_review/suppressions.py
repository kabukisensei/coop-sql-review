"""Inline ignore directives + the fingerprint baseline, bound to this tool's name.

The logic lives in ``coop_review_core.suppressions``; here we bake in this tool's
directive marker (``coop-sql-review:ignore``) so the CLI call sites stay terse.
"""

from __future__ import annotations

import re
from pathlib import Path

from coop_review_core import suppressions as _core
from coop_review_core.suppressions import is_inline_suppressed, load_baseline  # noqa: F401

TOOL = "coop-sql-review"

# `<tool>:ignore` + its trailing tokens. Same shape as core's private directive
# regex; reproduced here because syntax-error suppression keys on a friendly
# lowercase `syntax` token that core's rule-id matcher (upper-cased, hyphenated)
# deliberately can't represent.
_IGNORE_DIRECTIVE_RE = re.compile(rf"(?<![\w-]){re.escape(TOOL)}\s*:\s*ignore\b([^\n]*)", re.IGNORECASE)


def scan_directives(text: str) -> dict[int, set[str]]:
    """Lines carrying a ``coop-sql-review:ignore`` directive -> the rule ids silenced."""
    return _core.scan_directives(text, TOOL)


def scan_syntax_ignores(text: str) -> set[int]:
    """1-based lines whose ``coop-sql-review:ignore`` directive silences a syntax error.

    Fires for an explicit ``syntax`` token (``coop-sql-review:ignore syntax``) or
    a bare / ``*`` wildcard directive (which already means "silence everything on
    this line"). A directive that names only rule ids does **not** silence a
    syntax error — syntax diagnostics aren't rules. The trailing ``reason:`` /
    comment text is ignored, matching the rule-id scanner.
    """
    out: set[int] = set()
    for lineno, line in enumerate(text.splitlines(), start=1):
        match = _IGNORE_DIRECTIVE_RE.search(line)
        if not match:
            continue
        tail = re.split(r"\breason\b|--|//|#", match.group(1), maxsplit=1)[0]
        tokens = tail.split()
        if not tokens or tail.strip() == "*" or any(token.lower() == "syntax" for token in tokens):
            out.add(lineno)
    return out


def is_syntax_ignored(line: int, directive_lines: set[int]) -> bool:
    """True if a syntax-ignore directive sits on this line or the line directly above."""
    if not line:
        return False
    return line in directive_lines or (line - 1) in directive_lines


def write_baseline(path: Path, fingerprints) -> int:
    """Write a baseline file tagged with this tool; returns how many it recorded."""
    return _core.write_baseline(path, fingerprints, TOOL)
