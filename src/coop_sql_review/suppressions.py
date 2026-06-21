"""Inline ignore directives + the fingerprint baseline, bound to this tool's name.

The logic lives in ``coop_review_core.suppressions``; here we bake in this tool's
directive marker (``coop-sql-review:ignore``) so the CLI call sites stay terse.
"""

from __future__ import annotations

from pathlib import Path

from coop_review_core import suppressions as _core
from coop_review_core.suppressions import is_inline_suppressed, load_baseline  # noqa: F401

TOOL = "coop-sql-review"


def scan_directives(text: str) -> dict[int, set[str]]:
    """Lines carrying a ``coop-sql-review:ignore`` directive -> the rule ids silenced."""
    return _core.scan_directives(text, TOOL)


def write_baseline(path: Path, fingerprints) -> int:
    """Write a baseline file tagged with this tool; returns how many it recorded."""
    return _core.write_baseline(path, fingerprints, TOOL)
