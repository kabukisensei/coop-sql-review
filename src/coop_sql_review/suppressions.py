"""Inline ignore directives + the fingerprint baseline, bound to this tool's name.

The logic lives in ``coop_review_core.suppressions``; here we bake in this tool's
directive marker (``coop-sql-review:ignore``) so the CLI call sites stay terse.
"""

from __future__ import annotations

from pathlib import Path

from coop_review_core import suppressions as _core
from coop_review_core.suppressions import (  # noqa: F401
    BaselineError,
    is_inline_suppressed,
    is_syntax_ignored,
)

TOOL = "coop-sql-review"


def scan_directives(text: str) -> dict[int, set[str]]:
    """Lines carrying a ``coop-sql-review:ignore`` directive -> the rule ids silenced."""
    return _core.scan_directives(text, TOOL)


def scan_syntax_ignores(text: str) -> set[int]:
    """1-based lines whose ``coop-sql-review:ignore`` directive silences a syntax
    error (explicit ``syntax`` token, or a bare/``*`` wildcard). Now lives in core
    (coop-review-core#1) so the whole family shares one directive grammar."""
    return _core.scan_syntax_ignores(text, TOOL)


def write_baseline(path: Path, fingerprints) -> int:
    """Write a baseline file tagged with this tool; returns how many it recorded."""
    return _core.write_baseline(path, fingerprints, TOOL)


def load_baseline(path: Path) -> set[str]:
    """The fingerprints in a baseline file. Raises :class:`BaselineError` on a
    missing/corrupt/wrong-shape file, or one written by a DIFFERENT tool (a
    coop-dax-review baseline handed here is a misconfiguration, not empty)."""
    return _core.load_baseline(path, TOOL)
